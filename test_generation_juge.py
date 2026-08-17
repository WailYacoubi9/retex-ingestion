#!/usr/bin/env python3
"""A/B de la GÉNÉRATION — ce que l'assistant RÉPOND, jugé contre le golden enrichi.

A = API de production (ancien code)   B = API locale (correctif reranker)

Deux niveaux de vérification, volontairement séparés :

  MÉCANIQUE (objectif, sans LLM) — c'est le plus fiable, et ça attrape l'hallucination :
    citation_hors_contexte : une fiche citée qui n'était PAS dans le contexte fourni
    citation_hors_ancrage  : une fiche citée absente de `ancrage.fne_citables`
    chiffre_global_invente : la réponse annonce un total de fiches (interdit : on ne voit qu'un échantillon)
    faits_obligatoires     : présence des valeurs attendues (type, lieu, période)

  JUGE LLM (subjectif) — sur les critères de `criteres_juge` : ancrage, pertinence,
    pas_confusion (cause ≠ action ≠ description), honnêteté du plafond.

Usage : python3 test_generation_juge.py [chemin_golden] [n_questions]
"""
import json, re, sys, urllib.request, time, datetime, unicodedata

PROD = "http://172.16.6.10:8000"
LOCAL = "http://localhost:6001"
OLLAMA = "http://172.16.6.10:11434"
JUGE_MODELE = "qwen2.5:32b"
OUT = "/home/yie0070/retex-split/retex-ingestion/resultats_generation.md"
OUT_JSONL = "/home/yie0070/retex-split/retex-ingestion/resultats_generation.jsonl"

GOLD = sys.argv[1] if len(sys.argv) > 1 else "/home/yie0070/Téléchargements/golden_generation.jsonl"
NQ = int(sys.argv[2]) if len(sys.argv) > 2 else 999

# Détection des citations : on ne DEVINE pas le format (le premier motif ratait tout le
# format historique « FNE-AAAAADLNNN »). On cherche les identifiants RÉELS du corpus, plus
# un motif large pour repérer les identifiants INVENTÉS (ressemblants mais inexistants).
_SRC_FE = "/home/yie0070/retex-split/retex-ingestion/data/samples/incidents_avec_actions.json"
_CORPUS = {r["Num F.E."].upper().replace(" ", "")
           for r in json.load(open(_SRC_FE, encoding="utf-8")) if r.get("Num F.E.")}
_FE_LARGE = re.compile(r"\b(?:FNE|AFIS|CSA|REX|LRST|SGS)(?:\s?SURT)?[/\-][0-9A-Z]{2,12}"
                       r"(?:[/\-][0-9A-Z]{2,6}){0,2}")  # sans re.I : les identifiants sont en majuscules
# La borne haute doit valoir 12, pas 10 : la forme historique la plus longue a 11 caractères après le tiret.
# Avec {2,10} la regex le la TRONQUAIT d'un caractère, la rendant absente du corpus, donc compté comme
# identifiant INVENTÉ — 5 fausses hallucinations par run, sur le gabarit qui couvre 2 143 fiches
# (23 % du corpus). Le {0,2} final capte le préfixe « AFIS- » (3 fiches).
# Critère de couverture : chaque identifiant du corpus doit être relu EXACTEMENT (pas seulement
# détecté — une détection tronquée est précisément ce qui créait les fausses hallucinations).
# Vérifié : 9 189/9 191 relus exactement (7 043/9 191 avec l'ancienne borne). Les 2 restants sont
# MALFORMÉS dans la source (« /25/0001 », « FNE-/24/0001 ») — cf. defauts_qualite_donnees.md (D18).


def citations(rep: str) -> tuple[set, set]:
    """(identifiants réels cités, identifiants inventés).

    On EXTRAIT d'abord les candidats, puis on teste l'appartenance au corpus — jamais
    l'inverse : chercher les 9 191 identifiants par sous-chaîne créait de faux appariements
    (26 identifiants font ≤8 caractères, et « REX/25/0001 » contient « /25/0001 »).
    """
    reels, inventes = set(), set()
    for brut in _FE_LARGE.findall(rep or ""):
        c = brut.upper().replace(" ", "").rstrip(".,;:)")
        (reels if c in _CORPUS else inventes).add(c)
    return reels, inventes
# « 52 fiches », « 12 incidents », « au total 30 » -> annonce d'une population
_GLOBAL = re.compile(r"\b(\d{2,4})\s*(fiches?|incidents?|évènements?|evenements?|cas)\b", re.I)


def nz(s):
    s = "".join(c for c in unicodedata.normalize("NFD", str(s or "").lower())
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def ask(base, question, timeout=240):
    body = json.dumps({"question": question, "top_k": 8}).encode()
    r = urllib.request.Request(f"{base}/ask/incident-v2", data=body,
                               headers={"Content-Type": "application/json"}, method="POST")
    t = time.time()
    d = json.load(urllib.request.urlopen(r, timeout=timeout))
    return d, time.time() - t


def sources_de(d):
    for src in (d, d.get("diagnostic") or {}):
        v = src.get("sources")
        if isinstance(v, list):
            return [x.get("numero_fe") for x in v if isinstance(x, dict) and x.get("numero_fe")]
    return []


def juge(question, reponse, contexte_fe, criteres):
    """Juge LLM — note chaque critère 0/1 avec justification, en sortie structurée."""
    schema = {"type": "object", "properties": {
        c["critere"]: {"type": "object", "properties": {
            "ok": {"type": "boolean"}, "pourquoi": {"type": "string"}},
            "required": ["ok", "pourquoi"]} for c in criteres},
        "required": [c["critere"] for c in criteres]}
    regles = "\n".join(f"- {c['critere']} : {c['verification']}" for c in criteres)
    p = (f"Tu évalues la réponse d'un assistant sécurité aéroportuaire.\n\n"
         f"QUESTION : {question}\n\nFICHES FOURNIES EN CONTEXTE : {', '.join(contexte_fe) or '(aucune)'}\n\n"
         f"RÉPONSE À ÉVALUER :\n{reponse}\n\nCRITÈRES :\n{regles}\n\n"
         "Pour chaque critère, réponds ok=true seulement si la réponse le satisfait clairement.")
    body = {"model": JUGE_MODELE, "prompt": p, "stream": False, "format": schema,
            "options": {"temperature": 0}}
    r = urllib.request.Request(f"{OLLAMA}/api/generate", data=json.dumps(body).encode(),
                               headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(json.load(urllib.request.urlopen(r, timeout=300))["response"])


_ABST_MARQUEURS = ("n'ai pas trouvé", "aucune source", "aucun incident", "aucune fiche",
                   "hors du périmètre", "pas de fiche", "ne permet pas", "n'est pas renseigné",
                   "donnée absente", "pas disponible", "je ne peux pas", "aucune donnée")


def a_abstenu(rep, sources):
    """L'assistant a-t-il refusé de répondre ? (aucune source, ou refus explicite)"""
    return (not sources) or any(m in nz(rep) for m in (nz(x) for x in _ABST_MARQUEURS))


def controles_mecaniques(rep, sources, g):
    """Vérifications objectives — aucune LLM, donc aucune contestation possible."""
    anc = set((g.get("ancrage") or {}).get("fne_citables") or g.get("fne_attendus") or [])
    cites, inventes = citations(rep)
    ctx = {s.upper().replace(" ", "") for s in sources}
    ancn = {a.upper().replace(" ", "") for a in anc}
    att = (g.get("attendu_generation") or {})
    faits = att.get("faits_obligatoires") or []
    presents = 0
    par_type = {}                                          # type -> [ok, total]
    for f in faits:
        v = f.get("valeur")
        vals = v if isinstance(v, list) else [v]          # exemple_cause : une liste d'extraits
        # un fait est « présent » si sa valeur, ou un fragment significatif, apparaît
        ok = any(nz(str(x))[:60] in nz(rep) or nz(str(x)) in nz(rep) for x in vals if x)
        presents += 1 if ok else 0
        t = f.get("type") or "?"
        c = par_type.setdefault(t, [0, 0])
        c[0] += 1 if ok else 0
        c[1] += 1
    return {
        "cites": len(cites),
        "inventes": sorted(inventes),              # identifiant qui n'existe PAS dans le corpus
        "hors_contexte": sorted(cites - ctx),      # existe, mais n'était pas fourni au LLM
        "hors_ancrage": sorted(cites - ancn),      # cité mais hors vérité terrain
        "chiffre_global": _GLOBAL.findall(rep or ""),
        "faits_ok": presents, "faits_total": len(faits), "faits_par_type": par_type,
    }


# Tous les « faits obligatoires » ne sont pas vérifiables par sous-chaîne.
#   - periode      : la valeur est « 2012-2024 » ; un assistant n'écrit jamais cet intervalle
#                    littéralement. 36 des 77 critères (47 %) — inéchouables ET impassables.
#   - exemple_cause / exemple_action : on exige 60 caractères d'un extrait source mot pour mot,
#                    alors que le modèle reformule. 20 critères de plus (26 %).
# Soit 73 % des critères impassables par construction : c'est ce qui produisait le « 3 % / 7 % ».
# Ces types relèvent du juge, pas d'un test de sous-chaîne. Seuls ceux-ci sont mécaniques :
TYPES_MECANIQUES = {"type_evenement", "lieu", "motif"}


def main():
    G = [json.loads(l) for l in open(GOLD, encoding="utf-8")][:NQ]
    enrichi = any("criteres_juge" in g for g in G)
    print(f"{len(G)} questions · golden {'ENRICHI (juge actif)' if enrichi else 'simple (contrôles mécaniques seuls)'}\n")
    lignes, agg = [], {"A": {}, "B": {}}
    for k in ("A", "B"):
        agg[k] = {"invente": 0, "halluc": 0, "hors_ancrage": 0, "chiffre": 0, "faits": 0,
                  "faits_tot": 0, "sans_source": 0, "abst_attendue_ok": 0, "sec": 0.0,
                  "juge_ok": 0, "juge_tot": 0, "faits_mec": 0, "faits_mec_tot": 0}
    n_abst = sum(1 for g in G if (g.get("attendu_generation") or {}).get("type_reponse") == "abstention")
    for i, g in enumerate(G, 1):
        q = g["question"]
        doit_abstenir = (g.get("attendu_generation") or {}).get("type_reponse") == "abstention"
        row = {"q": q, "id": g.get("id", ""), "abst_attendue": doit_abstenir}
        for nom, base in (("A", PROD), ("B", LOCAL)):
            try:
                d, dt = ask(base, q)
                rep = d.get("answer") or d.get("reponse") or ""
                src = sources_de(d)
                m = controles_mecaniques(rep, src, g)
                m["invente_id"] = len(m["inventes"])
                a = agg[nom]
                a["invente"] += len(m["inventes"])
                a["halluc"] += len(m["hors_contexte"]); a["hors_ancrage"] += len(m["hors_ancrage"])
                a["chiffre"] += 1 if m["chiffre_global"] else 0
                a["sec"] += dt
                if doit_abstenir:
                    # ici, s'abstenir est le comportement ATTENDU
                    m["abst_ok"] = a_abstenu(rep, src)
                    a["abst_attendue_ok"] += 1 if m["abst_ok"] else 0
                else:
                    a["faits"] += m["faits_ok"]; a["faits_tot"] += m["faits_total"]
                    for t, (o, n) in m["faits_par_type"].items():
                        if t in TYPES_MECANIQUES:
                            a["faits_mec"] += o; a["faits_mec_tot"] += n
                    a["sans_source"] += 1 if not src else 0
                if enrichi and src and g.get("criteres_juge"):
                    try:
                        j = juge(q, rep, src, g["criteres_juge"])
                        m["juge"] = j
                        a["juge_ok"] += sum(1 for v in j.values() if v.get("ok"))
                        a["juge_tot"] += len(j)
                    except Exception as e:
                        m["juge"] = {"erreur": str(e)[:80]}
                row[nom] = {"rep": rep, "src": src, "m": m, "s": dt}
            except Exception as e:
                row[nom] = {"rep": f"ERREUR {e}", "src": [], "m": None, "s": 0}
        a, b = row["A"], row["B"]
        # on affiche les DEUX compteurs : n'afficher que « hors contexte » masquait les
        # identifiants inventés, qui sont le défaut le plus grave.
        def _c(x):
            return (f"{len(x['m']['inventes'])}inv/{len(x['m']['hors_contexte'])}hctx"
                    if x['m'] else "?")
        print(f"  [{i}/{len(G)}] {q[:44]:44} A:{len(a['src'])}src {_c(a)} · "
              f"B:{len(b['src'])}src {_c(b)}", flush=True)
        lignes.append(row)

    L = ["# A/B de la génération — ce que l'assistant RÉPOND\n",
         f"*{datetime.date.today().isoformat()} · **A** = production (ancien code) · "
         "**B** = local (correctif reranker). Même collection, même Ollama, même reranker.*\n",
         f"\n## Contrôles mécaniques (objectifs, sans juge)\n",
         f"*{len(G)-n_abst} questions attendent une réponse · {n_abst} attendent une **abstention**.*\n",
         "| | A — production | B — corrigé |", "|---|---:|---:|"]
    for lib, cle in (("identifiants INVENTÉS (n'existent pas)", "invente"),
                     ("citations hors contexte (existent, non fournies)", "halluc"),
                     ("citations hors vérité terrain", "hors_ancrage"),
                     ("réponses annonçant un total inventé", "chiffre"),
                     (f"sans source alors qu'une réponse est attendue (/{len(G)-n_abst})", "sans_source"),
                     (f"**abstention correcte quand elle est attendue** (/{n_abst})", "abst_attendue_ok")):
        L.append(f"| {lib} | {agg['A'][cle]} | **{agg['B'][cle]}** |")
    for k in ("A", "B"):
        agg[k]["faits_pct"] = agg[k]["faits_mec"] / agg[k]["faits_mec_tot"] if agg[k]["faits_mec_tot"] else 0
    L.append(f"| faits vérifiables mécaniquement présents "
             f"(/{agg['A']['faits_mec_tot']}) | {agg['A']['faits_mec']} ({agg['A']['faits_pct']:.0%}) "
             f"| **{agg['B']['faits_mec']} ({agg['B']['faits_pct']:.0%})** |")
    L.append(f"| latence moyenne | {agg['A']['sec']/len(G):.0f} s | {agg['B']['sec']/len(G):.0f} s |")
    if enrichi:
        L.append("\n## Juge LLM (critères du golden)\n")
        # Le juge ne tourne que sur les questions où l'assistant a fourni des sources. A
        # s'abstenant plus souvent, il est jugé sur MOINS de questions : comparer 90/108 à
        # 151/174 compare deux échantillons différents, et avantage mécaniquement celui qui
        # s'est tu sur les questions difficiles. Le seul comparatif honnête est l'INTERSECTION.
        def _sc(row, k):
            m = (row.get(k) or {}).get("m") or {}
            j = m.get("juge") or {}
            if not j or "erreur" in j:
                return None
            return sum(1 for v in j.values() if v.get("ok")), len(j)

        inter = [(a, b) for r in lignes
                 for a, b in [(_sc(r, "A"), _sc(r, "B"))] if a and b]
        L.append("| | A — production | B — corrigé |"); L.append("|---|---:|---:|")
        L.append(f"| critères satisfaits (toutes questions jugées) "
                 f"| {agg['A']['juge_ok']}/{agg['A']['juge_tot']} "
                 f"| **{agg['B']['juge_ok']}/{agg['B']['juge_tot']}** |")
        if inter:
            ao, at = sum(a[0] for a, _ in inter), sum(a[1] for a, _ in inter)
            bo, bt = sum(b[0] for _, b in inter), sum(b[1] for _, b in inter)
            L.append(f"| **critères satisfaits — {len(inter)} questions jugées des DEUX côtés** "
                     f"| **{ao}/{at}** ({ao/at:.0%}) | **{bo}/{bt}** ({bo/bt:.0%}) |")
        L.append("\n*Les deux lignes ne mesurent pas la même chose : la première compare des "
                 "échantillons différents (A est jugé sur moins de questions, puisqu'il s'abstient "
                 "davantage), la seconde compare à question égale. C'est la seconde qui tranche.*")
    L.append("\n## Détail par question\n")
    for r in lignes:
        L.append(f"\n### {r['id']} — « {r['q']} »\n")
        for nom, lib in (("A", "production"), ("B", "corrigé")):
            x = r[nom]; m = x["m"]
            L.append(f"**{nom} — {lib}** · {len(x['src'])} sources · {x['s']:.0f} s")
            if m:
                pb = []
                if m["hors_contexte"]: pb.append(f"⚠️ cite hors contexte : {', '.join(m['hors_contexte'][:4])}")
                if m["chiffre_global"]: pb.append(f"⚠️ annonce un total : {m['chiffre_global'][:2]}")
                L.append(f"  · faits {m['faits_ok']}/{m['faits_total']}" + ("  · " + " · ".join(pb) if pb else ""))
            L.append(f"\n> {' '.join((x['rep'] or '').split())[:500]}\n")
    open(OUT, "w", encoding="utf-8").write("\n".join(L) + "\n")
    # Réponses BRUTES, non tronquées. Le rapport .md coupe à 500 caractères : sans ce dump,
    # revérifier un détecteur (regex de citations, contrôle de faits) impose de relancer
    # 40 questions × 2 API × juge — ~50 min de GPU pour une question de post-traitement.
    with open(OUT_JSONL, "w", encoding="utf-8") as f:
        for row in lignes:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"\ninventés  : A={agg['A']['invente']}  B={agg['B']['invente']}")
    print(f"sans source: A={agg['A']['sans_source']}  B={agg['B']['sans_source']}   ·   abstention correcte: A={agg['A']['abst_attendue_ok']}/{n_abst}  B={agg['B']['abst_attendue_ok']}/{n_abst}")
    print(f"écrit : {OUT}")


if __name__ == "__main__":
    main()
