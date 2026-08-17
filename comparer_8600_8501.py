#!/usr/bin/env python3
"""Compare À ARMES ÉGALES l'outil de comparaison (8600) et l'assistant déployé (8501).

POURQUOI C'EST POSSIBLE MAINTENANT — la première comparaison était faussée : 8600 rendait
jusqu'à 10 fiches quand le serveur en rendait 8 (`keep=8` en dur), alors que la précision
était divisée par le k du golden dans les deux cas. Cinq points d'écart venaient de là, pas
de la qualité. Depuis, `keep` suit `top_k` côté serveur : on peut demander le MÊME nombre
aux deux, et l'écart restant devient interprétable.

Ce qu'on mesure : la RÉCUPÉRATION seule (quelles fiches remontent), sur la même vérité
terrain. Pas la génération, pas l'affichage.

Réserve assumée : les deux n'interrogent plus la même chose depuis les correctifs du jour
(collection, seuils, filtre piste, vivier). L'écart mesuré est donc « produit d'aujourd'hui »
contre « outil figé ce matin » — pas deux variantes d'un même système.
"""
import json
import statistics
import sys
import time
import urllib.parse
import urllib.request

GOLD = "golden_voies.jsonl"
OUT = "/home/yie0070/retex-split/retex-ingestion/resultats_8600_vs_8501.md"
NQ = int(sys.argv[1]) if len(sys.argv) > 1 else 999


def outil(q, k, mode="recherche", coll="incident_chunks_v2c"):
    """8600 — l'outil de comparaison local (réimplémentation).

    La réponse est indexée par NOM DE COLLECTION, pas par libellé : on interroge la même
    collection que le serveur (v2c), sans quoi on comparerait deux bases différentes.
    """
    u = (f"http://localhost:8600/api/search?q={urllib.parse.quote(q)}"
         f"&mode={mode}&k={k}")
    d = json.load(urllib.request.urlopen(u, timeout=300))
    r = d.get(coll, {})
    return [] if r.get("abstention") else [x["fe"] for x in r.get("res", [])][:k]


def produit(q, k):
    """8501 — l'assistant déployé, endpoint réel."""
    b = json.dumps({"question": q, "top_k": k}).encode()
    r = urllib.request.Request("http://172.16.6.10:8000/ask/incident-v2", data=b,
                               headers={"Content-Type": "application/json"}, method="POST")
    d = json.load(urllib.request.urlopen(r, timeout=400))
    return [s.get("numero_fe") for s in (d.get("sources") or []) if s.get("numero_fe")][:k]


def main():
    G = [json.loads(l) for l in open(GOLD, encoding="utf-8")][:NQ]
    lignes = []
    for i, g in enumerate(G, 1):
        k = g.get("k", 10)
        att = set(g.get("fne_attendus") or [])
        row = {"id": g["id"], "voie": g.get("voie", ""), "k": k}
        for nom, fn in (("8600", outil), ("8501", produit)):
            try:
                t = time.time()
                fes = fn(g["question"], k)
                row[nom] = {"n": len(fes), "bonnes": sum(1 for f in fes if f in att),
                            "s": time.time() - t}
            except Exception as e:
                row[nom] = {"n": 0, "bonnes": 0, "s": 0.0, "err": type(e).__name__}
        lignes.append(row)
        a, b = row["8600"], row["8501"]
        print(f"  [{i}/{len(G)}] {g['id']:9} 8600 {a['bonnes']:2d}/{a['n']:2d}  ·  "
              f"8501 {b['bonnes']:2d}/{b['n']:2d}", flush=True)

    def bloc(nom):
        v = [x[nom] for x in lignes]
        n = len(v)
        return {
            "prec": sum(x["bonnes"] / max(1, lignes[i]["k"]) for i, x in enumerate(v)) / n,
            "succes": sum(1 for x in v if x["bonnes"]) / n,
            "med": statistics.median(x["bonnes"] for x in v),
            "abst": sum(1 for x in v if x["n"] == 0),
            "rendues": sum(x["n"] for x in v),
            "bonnes": sum(x["bonnes"] for x in v),
            "s": sum(x["s"] for x in v) / n,
        }

    A, B = bloc("8600"), bloc("8501")
    L = ["# 8600 (outil de comparaison) vs 8501 (assistant déployé)\n",
         f"*{time.strftime('%Y-%m-%d')} · {len(lignes)} questions du golden · même vérité "
         "terrain, MÊME k demandé aux deux. Récupération seule.*\n",
         "\n| | 8600 — outil | 8501 — produit |", "|---|---:|---:|",
         f"| précision@k | {A['prec']:.0%} | **{B['prec']:.0%}** |",
         f"| **succès@k** | {A['succes']:.0%} | **{B['succes']:.0%}** |",
         f"| médiane de fiches utiles | {A['med']:.0f} | **{B['med']:.0f}** |",
         f"| fiches rendues (total) | {A['rendues']} | {B['rendues']} |",
         f"| fiches attendues trouvées | {A['bonnes']} | **{B['bonnes']}** |",
         f"| abstentions | {A['abst']}/{len(lignes)} | {B['abst']}/{len(lignes)} |",
         f"| latence moyenne | {A['s']:.1f} s | {B['s']:.1f} s |",
         "\n## Par type de question\n",
         "| type | 8600 succès | 8501 succès |", "|---|---:|---:|"]
    for voie in ("recherche", "cause", "action"):
        sel = [x for x in lignes if x["voie"] == voie]
        if not sel:
            continue
        sa = sum(1 for x in sel if x["8600"]["bonnes"]) / len(sel)
        sb = sum(1 for x in sel if x["8501"]["bonnes"]) / len(sel)
        L.append(f"| {voie} ({len(sel)} q.) | {sa:.0%} | {sb:.0%} |")
    open(OUT, "w", encoding="utf-8").write("\n".join(L) + "\n")
    json.dump(lignes, open(OUT.replace(".md", ".json"), "w"), ensure_ascii=False)
    print(f"\n  8600 : prec {A['prec']:.0%} · succès {A['succes']:.0%} · méd {A['med']:.0f} · abst {A['abst']}")
    print(f"  8501 : prec {B['prec']:.0%} · succès {B['succes']:.0%} · méd {B['med']:.0f} · abst {B['abst']}")
    print(f"écrit : {OUT}")


if __name__ == "__main__":
    main()
