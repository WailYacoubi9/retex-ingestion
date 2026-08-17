#!/usr/bin/env python3
"""Pour chaque question du golden : liste les chunks récupérés et marque ceux qui
appartiennent au jeu de référence (fne_attendus).

  ✓ = la fiche du chunk est dans fne_attendus     ✗ = elle n'y est pas

Sortie : inspect_chunks.md  (+ affichage résumé)
Usage :  python3 inspect_chunks.py [profondeur] [n_questions]
"""
import json, sys, urllib.request

QD = "http://172.16.6.10:6333"; OL = "http://172.16.6.10:11434"; SM = "incident_securite_v2"
GOLD = "/home/yie0070/retex-split/retex-ingestion/golden_voies.jsonl"
OUT = "/home/yie0070/retex-split/retex-ingestion/inspect_chunks.md"
COLLS = [("incident_chunks", "Ancien"), ("incident_chunks_v2b", "Enrichi"), ("incident_chunks_v2c", "Hybride")]
PROF = int(sys.argv[1]) if len(sys.argv) > 1 else 50      # profondeur de récupération
NQ = int(sys.argv[2]) if len(sys.argv) > 2 else 999       # nb de questions


def post(u, b):
    r = urllib.request.Request(u, data=json.dumps(b).encode(),
                               headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(r, timeout=90))


def emb(q):
    return post(f"{OL}/api/embed", {"model": "bge-m3", "input": q})["embeddings"][0]


def chunks(coll, v, limit):
    r = post(f"{QD}/collections/{coll}/points/query",
             {"query": v, "limit": limit, "with_payload": ["numero_fe", "field_canonical", "texte"],
              "filter": {"must": [{"key": "source_module", "match": {"value": SM}}],
                         "must_not": [{"key": "is_test_data", "match": {"value": True}}]}})["result"]["points"]
    return [{"score": p.get("score", 0.0), **(p.get("payload") or {})} for p in r]


def main():
    G = [json.loads(l) for l in open(GOLD, encoding="utf-8")][:NQ]
    L = [f"# Chunks récupérés vs jeu de référence\n",
         f"*Récupération dense pure, profondeur {PROF} chunks · ✓ = la fiche est dans `fne_attendus`.*\n",
         "Les colonnes clés : à quel **rang** apparaît la 1ʳᵉ bonne fiche, combien de bonnes "
         "fiches sont **vues** dans les N chunks, et combien sont **atteignables** au total.\n"]
    print(f"{'question':44} {'coll':8} {'✓ dans top10':>12} {'✓ dans les '+str(PROF):>14} {'/ attendues':>12} {'1er ✓ au rang':>14}")
    for g in G:
        rel = set(g["fne_attendus"])
        v = emb(g["question"])
        L.append(f"\n---\n\n## {g['id']} — « {g['question']} »\n")
        L.append(f"*voie **{g['voie']}** · {g['n_pertinents']} fiches attendues · k={g['k']}*\n")
        for coll, lab in COLLS:
            cs = chunks(coll, v, PROF)
            vus, top10, rang1 = set(), 0, None
            L.append(f"\n**{lab}**\n")
            L.append("| # | ✓ | score | fiche | chunk | extrait |")
            L.append("|---:|:-:|---:|---|---|---|")
            for i, c in enumerate(cs, 1):
                fe = c.get("numero_fe"); hit = fe in rel
                if hit:
                    vus.add(fe)
                    if rang1 is None: rang1 = i
                    if i <= 10: top10 += 1
                if i <= 25:   # on n'écrit que les 25 premiers pour rester lisible
                    ex = " ".join((c.get("texte") or "").split())[:70]
                    L.append(f"| {i} | {'✓' if hit else '✗'} | {c['score']:.3f} | `{fe}` | "
                             f"{c.get('field_canonical')} | {ex} |")
            L.append(f"\n> **{len(vus)}** fiches attendues vues dans les {PROF} chunks "
                     f"(sur {g['n_pertinents']}) · 1ʳᵉ bonne au rang **{rang1 or '—'}**\n")
            print(f"{g['question'][:44]:44} {lab:8} {top10:>12} {len(vus):>14} "
                  f"{g['n_pertinents']:>12} {str(rang1 or '—'):>14}")
    open(OUT, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"\nécrit : {OUT}")


if __name__ == "__main__":
    main()
