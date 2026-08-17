#!/usr/bin/env python3
"""Golden CLIENT — chaque question testée sur L'ONGLET qui la traiterait réellement.

POURQUOI CE HARNAIS — les questions du client ne passent pas toutes par la même voie. Les
tester toutes sur un seul endpoint mesurerait un usage que personne n'a. On les route donc
vers l'onglet du front qui leur correspond, et on vérifie ce que CHAQUE STATUT exige :

  EXACTE     l'oracle donne la bonne réponse chiffrée -> les valeurs doivent apparaître
  PLAFOND    la réponse est possible MAIS incomplète  -> la limite doit être ANNONCÉE
  ABSTENTION la base ne permet pas de répondre        -> l'assistant doit REFUSER

Certaines questions échoueront, et c'est attendu : le client demande des choses que le
corpus ne trace pas (efficacité des actions, typologie par type d'acteur, plan de
déploiement). L'échec devient alors une information — pas un défaut à masquer.

Ce qu'on mesure est l'EXTRACTION, pas la rédaction : les bons chiffres sont-ils remontés ?
"""
import json
import re
import sys
import time
import unicodedata
import urllib.request

API = "http://172.16.6.10:8000"
GOLD = "golden_client_v2 (1).jsonl"
OUT = "/home/yie0070/retex-split/retex-ingestion/resultats_golden_client.md"
NQ = int(sys.argv[1]) if len(sys.argv) > 1 else 999

# Correspondance voie du golden -> ONGLET du front -> endpoint réellement appelé.
# L'abstention passe par l'assistant : c'est le point d'entrée unique, et c'est son routeur
# qui porte la branche de refus.
VOIES = {
    "analyse":        ("📈 Tendances & proportions", "/ask/incident-v2/analyste"),
    "liste":          ("📊 Statistiques & requêtes", "/ask/incident-v2/query"),
    "recherche":      ("🔍 Recherche sémantique",    "/ask/incident-v2"),
    "recommandation": ("💡 Recommandation",          "/ask/incident-v2/recommande"),
    "abstention":     ("🤖 Assistant",               "/ask/incident-v2/auto"),
}

_REFUS = re.compile(
    r"aucun[e]? (?:incident|action|cas|fiche|donnée)|sort du périmètre|pas de (?:cas|synthèse|"
    r"recommandation)|ne permet pas|n'est pas trac|je préfère ne pas|hors périmètre|"
    r"pas en mesure|impossible de", re.I)


def nz(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def post(chemin, corps, timeout=600):
    r = urllib.request.Request(API + chemin, data=json.dumps(corps).encode(),
                               headers={"Content-Type": "application/json"}, method="POST")
    t = time.time()
    return json.load(urllib.request.urlopen(r, timeout=timeout)), time.time() - t


def texte_reponse(d):
    """La réponse, quel que soit le nom du champ selon la voie."""
    for cle in ("answer", "reponse", "brouillon"):
        if d.get(cle):
            return str(d[cle])
    return ""


def controler(g, rep):
    """Ce que le STATUT exige — objectif, sans juge."""
    o = g.get("oracle") or {}
    st = g.get("statut")
    n = nz(rep)
    res = {"statut": st, "type_oracle": o.get("type")}

    if st == "ABSTENTION":
        res["ok"] = bool(_REFUS.search(rep)) or not rep.strip()
        res["detail"] = "refus explicite" if res["ok"] else "a RÉPONDU au lieu de refuser"
        return res

    # Valeurs attendues, selon la forme de l'oracle.
    attendus, trouves = [], 0
    v = o.get("valeur")
    if o.get("type") == "classement" and isinstance(v, list):
        attendus = [str(x) for x in v]
    elif o.get("type") == "distribution" and isinstance(v, dict):
        attendus = [str(k) for k in v]                       # les clés (jours, mois, années)
    elif o.get("type") == "nombre" and v is not None:
        attendus = [f"{int(v):,}".replace(",", " "), str(v)]  # « 6 217 » ou « 6217 »
    elif o.get("type") == "comparaison" and isinstance(v, dict):
        attendus = [str(x) for x in v.values()]
    for a in attendus:
        # un libellé long compte s'il est présent en partie ; un nombre doit être exact
        cle = nz(a)
        if (cle and cle in n) or (len(cle) > 25 and cle[:25] in n):
            trouves += 1
    res["attendus"] = len(attendus)
    res["trouves"] = trouves

    if st == "PLAFOND":
        # La réserve doit être DITE : c'est tout l'objet de ce statut.
        plaf = g.get("plafond_a_annoncer") or {}
        indices = [plaf.get("mesure"), plaf.get("detail")]
        mots = {m for i in indices if i for m in nz(i).split() if len(m) > 5}
        res["plafond_annonce"] = bool(mots & set(n.split()))
        res["ok"] = res["plafond_annonce"]
        res["detail"] = ("réserve annoncée" if res["ok"]
                         else "répond SANS annoncer la limite")
    else:                                                     # EXACTE
        res["ok"] = bool(attendus) and trouves >= max(1, len(attendus) // 2)
        # Un REFUS et un CHIFFRE FAUX échouent tous deux, mais n'appellent pas le même
        # correctif : le premier est un trou de couverture (la voie ne sait pas traiter ce
        # patron), le second une erreur de calcul. Les confondre masquerait le plus grave.
        if not res["ok"]:
            res["nature"] = "refus" if _REFUS.search(rep) or "périmètre" in n else "réponse fausse"
        res["detail"] = (f"{trouves}/{len(attendus)} valeurs de l'oracle"
                         + (f" — {res['nature']}" if res.get("nature") else ""))
    return res


def main():
    G = [json.loads(l) for l in open(GOLD, encoding="utf-8") if l.strip()][:NQ]
    print(f"{len(G)} questions client · routées vers l'onglet correspondant\n", flush=True)
    lignes = []
    for i, g in enumerate(G, 1):
        voie = g.get("voie_attendue")
        onglet, ep = VOIES.get(voie, VOIES["abstention"])
        corps = {"question": g["question"]}
        if ep != "/ask/incident-v2/analyste":
            corps["top_k"] = 10
        try:
            d, dt = post(ep, corps)
            rep = texte_reponse(d)
        except Exception as e:
            print(f"  [{i}/{len(G)}] {g['id']:8} ERREUR {type(e).__name__}", flush=True)
            lignes.append({"id": g["id"], "onglet": onglet, "erreur": type(e).__name__,
                           "statut": g.get("statut"), "ok": False, "s": 0})
            continue
        c = controler(g, rep)
        lignes.append({"id": g["id"], "question": g["question"], "onglet": onglet,
                       "endpoint": ep, "rep": rep[:400], "s": round(dt, 1), **c})
        print(f"  [{i}/{len(G)}] {g['id']:8} {onglet:28} "
              f"{'✅' if c.get('ok') else '❌'} {c.get('detail','')} · {dt:.0f}s", flush=True)

    n = len(lignes) or 1
    ok = sum(1 for x in lignes if x.get("ok"))
    L = ["# Golden client — chaque question sur SON onglet\n",
         f"*{time.strftime('%Y-%m-%d')} · {len(lignes)} questions · endpoints réels du serveur. "
         "On mesure l'EXTRACTION (les bons chiffres remontent-ils), pas la rédaction.*\n",
         f"\n**{ok}/{n} questions satisfont l'exigence de leur statut.**\n",
         "\n| statut | ce qui est exigé | réussi |", "|---|---|---:|"]
    for st, exig in (("EXACTE", "les valeurs de l'oracle apparaissent"),
                     ("PLAFOND", "la limite est explicitement annoncée"),
                     ("ABSTENTION", "l'assistant refuse de répondre")):
        sel = [x for x in lignes if x.get("statut") == st]
        if sel:
            L.append(f"| {st} | {exig} | {sum(1 for x in sel if x.get('ok'))}/{len(sel)} |")
    refus = [x for x in lignes if x.get("nature") == "refus"]
    faux = [x for x in lignes if x.get("nature") == "réponse fausse"]
    if refus or faux:
        L += [f"\nParmi les échecs : **{len(refus)} refus** (la voie ne sait pas traiter le "
              f"patron — trou de couverture) et **{len(faux)} réponses fausses** (un chiffre "
              f"est produit, mais il ne correspond pas à l'oracle — plus grave).\n"]
    L += ["\n## Détail\n",
          "| id | onglet | statut | résultat | s |", "|---|---|---|---|---:|"]
    for x in lignes:
        L.append(f"| {x['id']} | {x['onglet']} | {x.get('statut','')} | "
                 f"{'✅ ' if x.get('ok') else '❌ '}{x.get('detail', x.get('erreur',''))} | {x.get('s',0)} |")
    L.append("\n## Réponses\n")
    for x in lignes:
        L.append(f"\n### {x['id']} — {x.get('question','')[:90]}\n")
        L.append(f"*{x['onglet']} · `{x.get('endpoint','')}` · {x.get('statut','')}*\n")
        L.append(f"> {' '.join((x.get('rep') or '').split())[:380]}\n")
    open(OUT, "w", encoding="utf-8").write("\n".join(L) + "\n")
    json.dump(lignes, open(OUT.replace(".md", ".json"), "w"), ensure_ascii=False, indent=1)
    print(f"\n  {ok}/{n} conformes à leur statut")
    print(f"écrit : {OUT}")


if __name__ == "__main__":
    main()
