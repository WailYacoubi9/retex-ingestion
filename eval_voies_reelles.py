#!/usr/bin/env python3
"""Évalue les TROIS voies sur les VRAIS endpoints de l'assistant déployé.

CE QUE CE HARNAIS CORRIGE — `eval_voies.py` interrogeait `localhost:8600`, c'est-à-dire mon
outil de comparaison : une RÉIMPLÉMENTATION du pipeline, pas le produit. Il réutilisait les
vrais modules (hybrid_retrieval, rrf_fuse, le reranker) mais pas le vrai chemin — pas le même
assemblage, pas les mêmes seuils appliqués au même endroit, pas le même enrichissement Neo4j.
Tous les chiffres qui en sortaient décrivaient donc un système voisin, jamais celui que
l'utilisateur interroge.

Ici, un seul principe : on tape sur ce que le front tape.

  recherche sémantique  ->  POST /ask/incident-v2
  recommandation        ->  POST /ask/incident-v2/recommande
  synthèse              ->  POST /ask/incident-v2/synthese

Le routeur `/auto` n'est PAS testé ici : chaque onglet du front appelle sa voie directement,
donc mesurer les voies est fidèle à l'usage. (Le routage est un étage distinct, défaillant par
ailleurs — 10 divergences sur 12 mesurées — et il mérite son propre harnais.)

LIMITE ASSUMÉE — la collection est désormais une variable d'environnement du conteneur. On ne
peut donc plus comparer deux collections dans un même run : il faudrait redémarrer l'API entre
les deux. Ce harnais mesure L'ÉTAT COURANT du déployé, pas un comparatif.
"""
import json
import statistics
import sys
import time
import urllib.request

API = "http://172.16.6.10:8000"
GOLD_RECH = "golden_voies.jsonl"
GOLD_RECO = "golden_recommandation.jsonl"
OUT = "/home/yie0070/retex-split/retex-ingestion/resultats_voies_reelles.md"
NQ = int(sys.argv[1]) if len(sys.argv) > 1 else 999

VOIES = {
    "recherche sémantique": "/ask/incident-v2",
    "recommandation":       "/ask/incident-v2/recommande",
    "synthèse":             "/ask/incident-v2/synthese",
}


def post(chemin, corps, timeout=300):
    r = urllib.request.Request(API + chemin, data=json.dumps(corps).encode(),
                               headers={"Content-Type": "application/json"}, method="POST")
    t = time.time()
    return json.load(urllib.request.urlopen(r, timeout=timeout)), time.time() - t


def fiches_rendues(d):
    """Les numéros de fiche rendus, quel que soit le format de la voie."""
    out = []
    # Chaque voie nomme sa liste autrement : `sources` (recherche), `incidents_similaires`
    # (recommandation), `precedents` (synthèse). En oublier une fait mesurer zéro fiche et
    # conclure à tort à une abstention.
    for cle in ("sources", "incidents_similaires", "incidents", "precedents"):
        for x in (d.get(cle) or []):
            fe = x.get("numero_fe") or x.get("fe")
            if fe and fe not in out:
                out.append(fe)
    return out


def mesurer(nom, chemin, questions):
    """precision@k, succès@k, n brut — les métriques retenues, jamais la moyenne seule."""
    lignes = []
    for g in questions:
        k = g.get("k", 10)
        attendus = set(g.get("fne_attendus") or [])
        try:
            d, dt = post(chemin, {"question": g["question"], "top_k": k})
        except Exception as e:
            print(f"    {g['id']:9} ERREUR {type(e).__name__} {str(e)[:50]}", flush=True)
            continue
        fes = fiches_rendues(d)[:k]
        bonnes = sum(1 for f in fes if f in attendus)
        lignes.append({"id": g["id"], "voie_q": g.get("voie", ""), "k": k,
                       "rendues": len(fes), "bonnes": bonnes,
                       "prec": bonnes / k if k else 0.0,
                       "succes": 1 if bonnes else 0,
                       "abstention": len(fes) == 0, "s": dt})
        print(f"    {g['id']:9} {bonnes}/{len(fes)} bonnes · {dt:.0f}s", flush=True)
    return lignes


def bloc(nom, lignes):
    if not lignes:
        return [f"\n### {nom}\n", "*aucune mesure*\n"]
    n = len(lignes)
    prec = sum(x["prec"] for x in lignes) / n
    succ = sum(x["succes"] for x in lignes) / n
    med = statistics.median(x["bonnes"] for x in lignes)
    abst = sum(1 for x in lignes if x["abstention"])
    lat = sum(x["s"] for x in lignes) / n
    return [f"\n### {nom} — {n} questions\n", "| | |", "|---|---:|",
            f"| précision@k | {prec:.0%} |",
            f"| **succès@k** (au moins une bonne fiche) | **{succ:.0%}** |",
            f"| **médiane de fiches utiles** | **{med:.0f}** |",
            f"| abstentions | {abst}/{n} |",
            f"| latence moyenne | {lat:.0f} s |"]


def main():
    rech = [json.loads(l) for l in open(GOLD_RECH, encoding="utf-8")][:NQ]
    reco = [json.loads(l) for l in open(GOLD_RECO, encoding="utf-8")][:NQ]

    print(f"recherche sémantique — {len(rech)} questions", flush=True)
    l_rech = mesurer("recherche", VOIES["recherche sémantique"], rech)
    print(f"\nrecommandation — {len(reco)} questions", flush=True)
    l_reco = mesurer("recommandation", VOIES["recommandation"], reco)
    print(f"\nsynthèse — {len(reco)} questions", flush=True)
    l_synt = mesurer("synthèse", VOIES["synthèse"], reco)

    L = ["# Les trois voies, mesurées sur les VRAIS endpoints\n",
         f"*{time.strftime('%Y-%m-%d')} · serveur déployé. Remplace `eval_voies.py`, qui "
         "interrogeait une réimplémentation locale et non le produit.*\n",
         "\n## Résultats\n"]
    L += bloc("Recherche sémantique — `/ask/incident-v2`", l_rech)
    L += bloc("Recommandation — `/recommande`", l_reco)
    L += bloc("Synthèse — `/synthese`", l_synt)

    # La moyenne cache la bimodalité : on publie la distribution, comme pour la recherche.
    if l_rech:
        from collections import Counter
        c = Counter(x["bonnes"] for x in l_rech)
        L += ["\n## Distribution — recherche sémantique\n",
              "*La moyenne masque la forme : ce qui compte est le nombre de questions à zéro.*\n",
              "| fiches utiles | questions |", "|---:|---|"]
        for b in sorted(c):
            L.append(f"| {b} | {'█' * c[b]} {c[b]} |")
        par_type = {}
        for x in l_rech:
            if not x["bonnes"]:
                par_type[x["voie_q"]] = par_type.get(x["voie_q"], 0) + 1
        if par_type:
            det = ", ".join(f"**{v} en {k}**" for k, v in
                            sorted(par_type.items(), key=lambda i: -i[1]))
            L.append(f"\nLes questions sans aucune fiche utile se répartissent ainsi : {det}.")
    open(OUT, "w", encoding="utf-8").write("\n".join(L) + "\n")
    with open(OUT.replace(".md", ".jsonl"), "w", encoding="utf-8") as f:
        for nom, lot in (("recherche", l_rech), ("recommandation", l_reco), ("synthese", l_synt)):
            for x in lot:
                f.write(json.dumps({**x, "voie": nom}, ensure_ascii=False) + "\n")
    print(f"\nécrit : {OUT}")


if __name__ == "__main__":
    main()
