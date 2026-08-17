#!/usr/bin/env python3
"""Éval du golden 46 questions sur les 4 voies × 3 collections (via l'outil 8600).

Métriques par (question, voie, collection) :
  precision@k  = bonnes / k            (k propre à la question : 10 ou 5)
  couverture   = bonnes / min(k, n)    (= rappel normalisé par le rappel_max atteignable)
  MRR          = 1 / rang de la 1re bonne
Sortie : eval_voies.md + eval_voies.jsonl (détail brut)
"""
import json, urllib.request, urllib.parse, statistics, datetime, sys
from collections import defaultdict

GOLD = "/home/yie0070/retex-split/retex-ingestion/golden_voies.jsonl"
OUT_MD = "/home/yie0070/retex-split/retex-ingestion/eval_voies.md"
OUT_JS = "/home/yie0070/retex-split/retex-ingestion/eval_voies.jsonl"
MODES = ["dense", "recherche", "reco", "causes"]
COLLS = [("incident_chunks", "Ancien"), ("incident_chunks_v2b", "Enrichi"), ("incident_chunks_v2c", "Hybride")]

G = [json.loads(l) for l in open(GOLD, encoding="utf-8")]


def api(q, mode, k):
    u = f"http://localhost:8600/api/search?q={urllib.parse.quote(q)}&mode={mode}&k={k}"
    return json.load(urllib.request.urlopen(u, timeout=180))


def main():
    detail = []
    agg = defaultdict(lambda: defaultdict(list))          # (mode,coll) -> metric -> []
    par_voie = defaultdict(lambda: defaultdict(list))     # (voie,mode,coll) -> metric -> []
    n = len(G)
    for i, g in enumerate(G, 1):
        k, rel = g["k"], set(g["fne_attendus"])
        for mode in MODES:
            try:
                d = api(g["question"], mode, k)
            except Exception as e:
                print(f"  [{i}/{n}] {mode} ERREUR {e}", flush=True)
                continue
            for coll, lab in COLLS:
                r = d.get(coll, {})
                # liste complète rendue (avant troncature à k) : le pooling et le rappel@profondeur
                # en ont besoin, et la recalculer coûte une ré-exécution GPU complète.
                fes_tous = [] if r.get("abstention") else [x["fe"] for x in r.get("res", [])]
                fes = fes_tous[:k]
                hits = [j for j, fe in enumerate(fes) if fe in rel]
                prec = len(hits) / k
                couv = len(hits) / min(k, g["n_pertinents"])
                mrr = 1 / (hits[0] + 1) if hits else 0.0
                abst = bool(r.get("abstention"))
                for m, v in (("prec", prec), ("couv", couv), ("mrr", mrr), ("abst", 1.0 if abst else 0.0)):
                    agg[(mode, lab)][m].append(v)
                    par_voie[(g["voie"], mode, lab)][m].append(v)
                detail.append({"id": g["id"], "question": g["question"], "voie": g["voie"],
                               "mecanisme": g["mecanisme"], "famille": g.get("famille", ""),
                               "n_pertinents": g["n_pertinents"], "k": k, "mode": mode,
                               "collection": lab, "prec": round(prec, 3), "couv": round(couv, 3),
                               "mrr": round(mrr, 3), "abstention": abst, "rendues": len(fes),
                               # Sans ces trois champs, aucune métrique robuste à l'incomplétude
                               # (bpref, RBP et son résidu), aucun pooling et aucun jugement par
                               # paires n'est calculable a posteriori : il faut tout relancer.
                               "fes": fes,                     # top-k, dans l'ordre du classement
                               "fes_tous": fes_tous[:100],     # profondeur, pour le pooling
                               "pertinence": [1 if fe in rel else 0 for fe in fes]})
        print(f"  [{i}/{n}] {g['id']:12} {g['question'][:52]}", flush=True)

    with open(OUT_JS, "w", encoding="utf-8") as f:
        for d in detail:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    m = statistics.mean
    L = ["# Éval des voies — 46 questions golden × 4 voies × 3 collections\n",
         f"*{datetime.date.today().isoformat()} · vérité terrain exacte (listes FNE) · "
         f"k propre à chaque question (10 ou 5).*\n",
         "`précision@k` = bonnes / k · `couverture` = bonnes / min(k, n) "
         "(= rappel normalisé par le maximum atteignable) · `MRR` = rang de la 1ʳᵉ bonne.\n",
         "\n## 1. Vue d'ensemble — toutes questions confondues\n",
         "| Voie (méthode) | Collection | précision@k | couverture | MRR | abstentions |",
         "|---|---|---:|---:|---:|---:|"]
    for mode in MODES:
        for _, lab in COLLS:
            a = agg[(mode, lab)]
            if not a["prec"]:
                continue
            L.append(f"| {mode} | {lab} | {m(a['prec']):.0%} | {m(a['couv']):.0%} | "
                     f"{m(a['mrr']):.2f} | {int(sum(a['abst']))}/{len(a['abst'])} |")

    L.append("\n## 2. Par type de question (la voie que la question vise)\n")
    for voie in ("recherche", "cause", "action"):
        nq = sum(1 for g in G if g["voie"] == voie)
        L.append(f"\n### Questions « {voie} » ({nq} questions)\n")
        L.append("| Méthode | Ancien | Enrichi | Hybride |")
        L.append("|---|---:|---:|---:|")
        for mode in MODES:
            cells = []
            for _, lab in COLLS:
                a = par_voie[(voie, mode, lab)]
                cells.append(f"{m(a['prec']):.0%}" if a["prec"] else "—")
            L.append(f"| {mode} | " + " | ".join(cells) + " |")

    L.append("\n## 3. Détail par question (précision@k, meilleure méthode par collection)\n")
    L.append("| id | question | n | k | voie | Ancien | Enrichi | Hybride | meilleure voie |")
    L.append("|---|---|---:|---:|---|---:|---:|---:|---|")
    for g in G:
        best_mode, best_val = "—", -1
        cells = {}
        for _, lab in COLLS:
            vals = [(mode, dd["prec"]) for dd in detail
                    if dd["id"] == g["id"] and dd["collection"] == lab for mode in [dd["mode"]]]
            if not vals:
                cells[lab] = "—"; continue
            bm, bv = max(vals, key=lambda x: x[1])
            cells[lab] = f"{bv:.0%}"
            if bv > best_val:
                best_val, best_mode = bv, bm
        L.append(f"| {g['id']} | {g['question'][:46]} | {g['n_pertinents']} | {g['k']} | {g['voie']} | "
                 f"{cells.get('Ancien','—')} | {cells.get('Enrichi','—')} | {cells.get('Hybride','—')} | {best_mode} |")

    open(OUT_MD, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"\nécrit : {OUT_MD}\n       {OUT_JS}")
    print("\n=== VUE D'ENSEMBLE (précision@k) ===")
    for mode in MODES:
        row = "  ".join(f"{lab}={m(agg[(mode,lab)]['prec']):.0%}" for _, lab in COLLS if agg[(mode, lab)]["prec"])
        print(f"  {mode:10} {row}")


if __name__ == "__main__":
    main()
