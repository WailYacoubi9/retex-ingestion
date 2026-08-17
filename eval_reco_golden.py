#!/usr/bin/env python3
"""Évalue la voie RECOMMANDATION sur le golden RECO — contrôles mécaniques puis juge.

CE QUE CE HARNAIS REMPLACE — ma première évaluation comparait le THÈME de l'action réelle à
celui des actions proposées. Résultat : 55 % contre une référence triviale à 48 %, écart non
significatif (McNemar p = 0,45). Cette proxy avait deux défauts que le golden RECO corrige :
elle comptait comme un échec une action pertinente mais différente de celle réellement prise,
et elle ne vérifiait NI l'ancrage, NI l'honnêteté de la réponse.

Le golden mesure ce qui compte vraiment pour cette voie :
  · la réponse s'appuie-t-elle sur des précédents RÉELS du contexte ?
  · distingue-t-elle ce qui A ÉTÉ FAIT de ce qu'elle SUGGÈRE ?
  · annonce-t-elle son plafond — « 113 fiches sur 1 273 portent une action structurée » ?
  · évite-t-elle d'affirmer qu'une action a été EFFICACE, alors que le corpus ne trace
    aucune inefficacité (le champ « actions jugées efficaces » ne contient que « oui »
    sur 709 fiches) et ne permet donc aucune comparaison ?

Les contrôles mécaniques d'abord : ils sont objectifs et incontestables. Le juge ensuite.
"""
import json
import re
import sys
import time
import unicodedata
import urllib.request

API = "http://172.16.6.10:8000"
GOLD = sys.argv[1] if len(sys.argv) > 1 else "golden_reco.jsonl"
NQ = int(sys.argv[2]) if len(sys.argv) > 2 else 999
OUT = "/home/yie0070/retex-split/retex-ingestion/resultats_reco_golden.md"
JUGE_MODELE = "qwen2.5:32b"

_SRC_FE = "/home/yie0070/retex-split/retex-ingestion/data/samples/incidents_avec_actions.json"
_CORPUS = {r["Num F.E."].upper().replace(" ", "")
           for r in json.load(open(_SRC_FE, encoding="utf-8")) if r.get("Num F.E.")}
# Borne haute à 12, pas 10 : la forme historique la plus longue a 11 caractères après le tiret (cf. le
# défaut corrigé dans test_generation_juge.py, qui produisait 5 fausses hallucinations/run).
_FE = re.compile(r"\b(?:FNE|AFIS|CSA|REX|LRST|SGS)(?:\s?SURT)?[/\-][0-9A-Z]{2,12}"
                 r"(?:[/\-][0-9A-Z]{2,6}){0,2}")

# Affirmer qu'une action a marché est INVÉRIFIABLE ici : le corpus ne trace aucune
# inefficacité, donc aucune comparaison n'est possible. C'est un interdit du golden.
_EFFICACITE = re.compile(
    r"\b(a|ont)\s+(?:été\s+)?(?:efficace|efficaces|permis de (?:résoudre|éviter|supprimer))"
    r"|\bavec succès\b|\ba (?:bien )?fonctionné\b|\bs'est révélé[e]?s? efficace"
    r"|\bmesure la plus efficace\b|\bont porté leurs fruits\b", re.I)

# Marqueurs qui séparent le CONSTAT de la SUGGESTION.
_FAIT = re.compile(r"\b(a été|ont été|a fait|ont fait|dans (?:ce|ces) cas|précédent|"
                   r"il a été|on a|les équipes ont|constaté)\b", re.I)
_SUGGERE = re.compile(r"\b(je (?:recommande|suggère|propose)|il (?:est|serait) recommandé|"
                      r"vous pourriez|à envisager|piste[s]? d'action|nous recommandons|"
                      r"il conviendrait|préconis)\b", re.I)


def nz(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def citations(rep):
    """(identifiants réels cités, identifiants inventés)."""
    reels, inventes = set(), set()
    for brut in _FE.findall(rep or ""):
        c = brut.upper().replace(" ", "").rstrip(".,;:)")
        (reels if c in _CORPUS else inventes).add(c)
    return reels, inventes


def recommande(question, timeout=300):
    b = json.dumps({"question": question, "top_k": 10}).encode()
    r = urllib.request.Request(f"{API}/ask/incident-v2/recommande", data=b,
                               headers={"Content-Type": "application/json"}, method="POST")
    t = time.time()
    return json.load(urllib.request.urlopen(r, timeout=timeout)), time.time() - t


def contexte_fe(d):
    """Les fiches réellement fournies au générateur — la référence de l'ancrage."""
    fes = {str(i.get("numero_fe") or "").upper().replace(" ", "")
           for i in (d.get("incidents_similaires") or [])}
    for a in (d.get("actions") or []):
        fes |= {str(x).upper().replace(" ", "") for x in (a.get("fe_sources") or [])}
    return {f for f in fes if f}


_ABST = re.compile(r"aucun[e]? (?:incident|action|cas|fiche)|pas de (?:cas comparable|synthèse|"
                   r"recommandation)|sort du périmètre|ne permet pas de recommander|"
                   r"trop peu d'actions|aucune action structurée", re.I)


def controles(rep, d, g):
    """Vérifications objectives, sans LLM — donc incontestables."""
    ctx = contexte_fe(d)
    # Certaines questions attendent une ABSTENTION : sur « collision aviaire sur la 36L »,
    # 1 seule fiche sur 1 683 porte une action structurée. Recommander quelque chose là-dessus
    # serait une faute, pas une performance — le système doit dire qu'il n'a pas la matière.
    if g.get("mode_attendu") == "abstention":
        abst = bool(_ABST.search(rep or "")) or not (d.get("actions") or [])
        return {"abstention_attendue": True, "abstention_ok": abst,
                "cites": [], "inventes": [], "hors_contexte": [], "n_contexte": len(ctx),
                "plafond_annonce": None, "categorie_attendue_presente": None,
                "affirme_efficacite": bool(_EFFICACITE.search(rep or "")),
                "distingue_fait_suggestion": None, "categories_observees": []}
    cites, inventes = citations(rep)
    att = g.get("attendu_generation") or {}
    plaf = att.get("plafond_a_annoncer") or {}

    # Le plafond est annoncé si le nombre de fiches à action structurée apparaît dans la
    # réponse. C'est la mesure d'honnêteté : dire sur COMBIEN de cas on s'appuie.
    n, sur = plaf.get("n"), plaf.get("sur")
    chiffres = set(re.findall(r"\b(\d{1,5})\b", rep or ""))
    plafond_ok = bool(plaf) and (str(n) in chiffres or str(sur) in chiffres)

    # Au moins une catégorie d'action réellement observée doit apparaître.
    cats = []
    for f in att.get("faits_obligatoires") or []:
        if f.get("type") == "categorie_action":
            v = f.get("valeur")
            cats = v if isinstance(v, list) else [v]
    obs = [c.get("categorie") for c in (g.get("actions_observees") or [])]
    def _cat_presente(c):
        # « collecte / remise en état » -> on cherche chaque mot-clé significatif
        mots = [m for m in re.split(r"[ /]+", nz(c)) if len(m) > 4]
        return any(m in nz(rep) for m in mots)
    cat_ok = any(_cat_presente(c) for c in cats) if cats else None

    return {
        "cites": sorted(cites),
        "inventes": sorted(inventes),                    # n'existe nulle part
        "hors_contexte": sorted(cites - ctx),            # existe, mais non fourni
        "n_contexte": len(ctx),
        "plafond_annonce": plafond_ok,
        "categorie_attendue_presente": cat_ok,
        "affirme_efficacite": bool(_EFFICACITE.search(rep or "")),
        "distingue_fait_suggestion": bool(_FAIT.search(rep or "")) and bool(_SUGGERE.search(rep or "")),
        "categories_observees": obs[:3],
    }


def juge(question, reponse, ctx, criteres):
    """Juge LLM sur les critères du golden, en sortie structurée."""
    schema = {"type": "object", "properties": {
        c["critere"]: {"type": "object", "properties": {
            "ok": {"type": "boolean"}, "pourquoi": {"type": "string"}},
            "required": ["ok", "pourquoi"]} for c in criteres},
        "required": [c["critere"] for c in criteres]}
    regles = "\n".join(f"- {c['critere']} : {c['verification']}" for c in criteres)
    p = (f"Tu évalues la réponse d'un assistant RETEX sécurité aéroportuaire.\n\n"
         f"QUESTION :\n{question}\n\nFICHES FOURNIES À L'ASSISTANT :\n{', '.join(sorted(ctx))}\n\n"
         f"RÉPONSE À ÉVALUER :\n{reponse}\n\nCRITÈRES :\n{regles}\n\n"
         "Sois STRICT et FACTUEL. Pour chaque critère, réponds ok=true seulement si la "
         "vérification est clairement satisfaite. Justifie en une phrase.")
    b = json.dumps({"model": JUGE_MODELE, "prompt": p, "stream": False,
                    "format": schema, "options": {"temperature": 0}}).encode()
    r = urllib.request.Request("http://172.16.6.10:11434/api/generate", data=b,
                               headers={"Content-Type": "application/json"}, method="POST")
    d = json.load(urllib.request.urlopen(r, timeout=300))
    return json.loads(d["response"])


def main():
    G = [json.loads(l) for l in open(GOLD, encoding="utf-8") if l.strip()][:NQ]
    print(f"{len(G)} questions · golden RECO\n", flush=True)
    lignes = []
    agg = {"invente": 0, "hors_ctx": 0, "plafond": 0, "cat": 0, "efficacite": 0,
           "distingue": 0, "juge_ok": 0, "juge_tot": 0, "sec": 0.0}
    for i, g in enumerate(G, 1):
        try:
            d, dt = recommande(g["question"])
        except Exception as e:
            print(f"  [{i}/{len(G)}] {g['id']} ERREUR {type(e).__name__}", flush=True)
            continue
        rep = d.get("answer") or ""
        m = controles(rep, d, g)
        agg["invente"] += len(m["inventes"]); agg["hors_ctx"] += len(m["hors_contexte"])
        agg["plafond"] += 1 if m["plafond_annonce"] else 0
        agg["cat"] += 1 if m["categorie_attendue_presente"] else 0
        agg["efficacite"] += 1 if m["affirme_efficacite"] else 0
        agg["distingue"] += 1 if m["distingue_fait_suggestion"] else 0
        agg["sec"] += dt
        if g.get("criteres_juge"):
            try:
                j = juge(g["question"], rep, contexte_fe(d), g["criteres_juge"])
                m["juge"] = j
                agg["juge_ok"] += sum(1 for v in j.values() if v.get("ok"))
                agg["juge_tot"] += len(j)
            except Exception as e:
                m["juge"] = {"erreur": str(e)[:80]}
        lignes.append({"id": g["id"], "q": g["question"], "rep": rep, "m": m, "s": dt})
        print(f"  [{i}/{len(G)}] {g['id']:9} {len(m['cites'])} citées · "
              f"{len(m['inventes'])}inv/{len(m['hors_contexte'])}hctx · "
              f"plafond={'oui' if m['plafond_annonce'] else 'NON'} · "
              f"efficacité={'AFFIRMÉE' if m['affirme_efficacite'] else 'non'}", flush=True)

    n = len(lignes) or 1
    L = ["# Voie Recommandation — évaluation sur le golden RECO\n",
         f"*{len(lignes)} questions. Contrôles mécaniques d'abord (objectifs), juge ensuite.*\n",
         "\n## Contrôles mécaniques\n", "| | résultat |", "|---|---:|",
         f"| identifiants inventés | {agg['invente']} |",
         f"| citations hors contexte fourni | {agg['hors_ctx']} |",
         f"| **plafond annoncé** (sur combien de fiches la réponse s'appuie) | **{agg['plafond']}/{n}** |",
         f"| catégorie d'action réellement observée citée | {agg['cat']}/{n} |",
         f"| **distingue le fait de la suggestion** | **{agg['distingue']}/{n}** |",
         f"| ⚠️ affirme qu'une action a été efficace (interdit) | {agg['efficacite']}/{n} |",
         f"| latence moyenne | {agg['sec']/n:.0f} s |"]
    if agg["juge_tot"]:
        L += ["\n## Juge LLM\n", "| | résultat |", "|---|---:|",
              f"| critères satisfaits | {agg['juge_ok']}/{agg['juge_tot']} "
              f"({agg['juge_ok']/agg['juge_tot']:.0%}) |"]
    L.append("\n## Détail\n")
    for r in lignes:
        m = r["m"]
        L.append(f"\n### {r['id']} — « {r['q']} »\n")
        L.append(f"*{len(m['cites'])} fiches citées sur {m['n_contexte']} fournies · "
                 f"plafond {'annoncé' if m['plafond_annonce'] else 'NON annoncé'} · "
                 f"{r['s']:.0f} s*\n")
        if m["inventes"]:
            L.append(f"- ⚠️ inventés : {m['inventes']}")
        if m["hors_contexte"]:
            L.append(f"- ⚠️ hors contexte : {m['hors_contexte']}")
        if m["affirme_efficacite"]:
            L.append("- ⚠️ affirme une efficacité (invérifiable dans ce corpus)")
        for c, v in (m.get("juge") or {}).items():
            if isinstance(v, dict) and "ok" in v:
                L.append(f"- {'✅' if v['ok'] else '❌'} **{c}** — {v.get('pourquoi','')[:150]}")
        L.append(f"\n> {' '.join(r['rep'].split())[:600]}\n")
    open(OUT, "w", encoding="utf-8").write("\n".join(L) + "\n")
    with open(OUT.replace(".md", ".jsonl"), "w", encoding="utf-8") as f:
        for r in lignes:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nplafond annoncé : {agg['plafond']}/{n} · distingue fait/suggestion : "
          f"{agg['distingue']}/{n} · efficacité affirmée : {agg['efficacite']}/{n}")
    print(f"écrit : {OUT}")


if __name__ == "__main__":
    main()
