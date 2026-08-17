#!/usr/bin/env python3
"""Mesure le gain du FILTRAGE STRUCTURÉ avant classement sémantique.

Compare, sur les questions du golden portant une contrainte structurée :
   A. dense pur sur tout le corpus            (ce que fait le système aujourd'hui)
   B. filtre payload exact PUIS classement dense  (l'architecture proposée)

Le filtre est ici fourni à la main : on mesure donc le PLAFOND de l'approche
(ce qu'on obtiendrait si le routeur extrayait correctement la contrainte),
pas le système de bout en bout.
"""
import json, urllib.request, urllib.parse, statistics

QD, OL, SM = "http://172.16.6.10:6333", "http://172.16.6.10:11434", "incident_securite_v2"
COLL = "incident_chunks_v2c"
GOLD = "/home/yie0070/retex-split/retex-ingestion/golden_voies.jsonl"
OUT = "/home/yie0070/retex-split/retex-ingestion/resultats_filtrage.md"

# question du golden -> filtre structuré correspondant
FILTRES = {
    "refus de priorité au poste D61": [{"key": "poste", "match": {"value": "D61"}}],
    "incidents survenus au poste C83 en 2024 ou 2025": [
        {"key": "poste", "match": {"value": "C83"}},
        {"key": "annee", "match": {"any": ["2024", "2025"]}}],
    "baisse du niveau de protection incendie en 2026": [{"key": "annee", "match": {"value": "2026"}}],
    "fuite de kérosène lors du plein de l'avion en 2025": [{"key": "annee", "match": {"value": "2025"}}],
}


def post(u, b):
    r = urllib.request.Request(u, data=json.dumps(b).encode(),
                               headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(r, timeout=120))


def emb(q):
    return post(f"{OL}/api/embed", {"model": "bge-m3", "input": q})["embeddings"][0]


def cherche(v, k, extra=None, fetch=400):
    must = [{"key": "source_module", "match": {"value": SM}}] + (extra or [])
    r = post(f"{QD}/collections/{COLL}/points/query",
             {"query": v, "limit": fetch, "with_payload": ["numero_fe"],
              "filter": {"must": must,
                         "must_not": [{"key": "is_test_data", "match": {"value": True}}]}})["result"]["points"]
    out, vus = [], set()
    for p in r:
        fe = (p.get("payload") or {}).get("numero_fe")
        if fe and fe not in vus:
            vus.add(fe); out.append(fe)
        if len(out) >= k:
            break
    return out


def compte(extra):
    must = [{"key": "source_module", "match": {"value": SM}}] + extra
    return post(f"{QD}/collections/{COLL}/points/count",
                {"exact": True, "filter": {"must": must}})["result"]["count"]


def main():
    G = {g["question"]: g for g in (json.loads(l) for l in open(GOLD, encoding="utf-8"))}
    tot = post(f"{QD}/collections/{COLL}/points/count", {"exact": True})["result"]["count"]
    L = ["# Filtrage structuré avant classement — mesure du gain\n",
         "*Comparaison sur les questions du golden portant une contrainte structurée.*\n",
         "**A** = dense pur sur tout le corpus (système actuel) · "
         "**B** = filtre payload exact **puis** classement dense (architecture proposée).\n",
         "> Le filtre est fourni à la main : on mesure le **plafond** de l'approche — "
         "ce qu'on obtiendrait si le routeur extrayait correctement la contrainte. "
         "Ce n'est pas une mesure de bout en bout.\n",
         "| Question | n | chunks après filtre | précision@10 **A** | précision@10 **B** | Δ |",
         "|---|---:|---:|---:|---:|---:|"]
    pa, pb = [], []
    for q, filt in FILTRES.items():
        g = G.get(q)
        if not g:
            print(f"  [absent du golden] {q}"); continue
        rel, k = set(g["fne_attendus"]), g["k"]
        v = emb(q)
        a = len([f for f in cherche(v, k) if f in rel]) / k
        b = len([f for f in cherche(v, k, filt) if f in rel]) / k
        n = compte(filt)
        pa.append(a); pb.append(b)
        L.append(f"| {q} | {g['n_pertinents']} | {n} / {tot} ({n/tot:.1%}) | "
                 f"{a:.0%} | **{b:.0%}** | {b-a:+.0%} |")
        print(f"  {q[:50]:50} A={a:.0%}  B={b:.0%}  ({b-a:+.0%})", flush=True)
    m = statistics.mean
    L.append(f"| **MOYENNE** | | | **{m(pa):.0%}** | **{m(pb):.0%}** | **{m(pb)-m(pa):+.0%}** |")
    L.append(f"\n## Lecture\n")
    L.append(f"Le filtre réduit l'espace de recherche de **{tot} chunks** à quelques dizaines, "
             "puis le classement sémantique ordonne à l'intérieur. Les 207 titres identiques "
             "« collision aviaire » ne se disputent plus les premières places : dans un "
             "sous-ensemble contraint, l'ordre arbitraire ne coûte plus rien.\n")
    L.append("**Ce que ça ne dit pas** : l'extraction automatique de la contrainte depuis la "
             "question n'est pas mesurée ici. C'est le travail du routeur, et il faudra le "
             "mesurer séparément — un filtre mal extrait dégraderait le résultat.\n")
    open(OUT, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"\nMOYENNE  A={m(pa):.0%}  ->  B={m(pb):.0%}   ({m(pb)-m(pa):+.0%})")
    print(f"écrit : {OUT}")


if __name__ == "__main__":
    main()
