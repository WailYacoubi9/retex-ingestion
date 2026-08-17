#!/usr/bin/env python3
"""Rapport de mesure consolidé -> rapport_mesures.md

Reprend le run CORRIGÉ (eval_voies.jsonl) et y ajoute un diagnostic au niveau chunk
(rappel@50 / rang de la 1re bonne) pour distinguer « jamais vue » de « mal classée ».
"""
import json, statistics, datetime, urllib.request
from collections import defaultdict

BASE = "/home/yie0070/retex-split/retex-ingestion/"
QD, OL, SM = "http://172.16.6.10:6333", "http://172.16.6.10:11434", "incident_securite_v2"
PROF = 50
COLLS = [("incident_chunks", "Ancien"), ("incident_chunks_v2b", "Enrichi"), ("incident_chunks_v2c", "Hybride")]
MODES = ["dense", "recherche", "reco", "causes"]

G = [json.loads(l) for l in open(BASE + "golden_voies.jsonl", encoding="utf-8")]
E = [json.loads(l) for l in open(BASE + "eval_voies.jsonl", encoding="utf-8")]


def post(u, b):
    r = urllib.request.Request(u, data=json.dumps(b).encode(),
                               headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(r, timeout=90))


def emb(q):
    return post(f"{OL}/api/embed", {"model": "bge-m3", "input": q})["embeddings"][0]


def fiches_chunks(coll, v, limit):
    r = post(f"{QD}/collections/{coll}/points/query",
             {"query": v, "limit": limit, "with_payload": ["numero_fe"],
              "filter": {"must": [{"key": "source_module", "match": {"value": SM}}],
                         "must_not": [{"key": "is_test_data", "match": {"value": True}}]}})["result"]["points"]
    return [(p.get("payload") or {}).get("numero_fe") for p in r]


# ── diagnostic niveau chunk ───────────────────────────────────────────────────
print("diagnostic chunk (46 questions × 3 collections)…", flush=True)
diag = {}
for i, g in enumerate(G, 1):
    v = emb(g["question"]); rel = set(g["fne_attendus"])
    for coll, lab in COLLS:
        fes = fiches_chunks(coll, v, PROF)
        vues = {f for f in fes if f in rel}
        top10 = sum(1 for f in fes[:10] if f in rel)
        rang1 = next((j + 1 for j, f in enumerate(fes) if f in rel), None)
        diag[(g["id"], lab)] = {"vues": len(vues), "top10": top10, "rang1": rang1}
    if i % 10 == 0:
        print(f"  {i}/{len(G)}", flush=True)

m = statistics.mean
agg = defaultdict(lambda: defaultdict(list))
par_voie = defaultdict(lambda: defaultdict(list))
for d in E:
    for k in ("prec", "couv", "mrr", "abst"):
        agg[(d["mode"], d["collection"])][k].append(d[k] if k != "abst" else (1.0 if d["abstention"] else 0.0))
        par_voie[(d["voie"], d["mode"], d["collection"])][k].append(d[k] if k != "abst" else (1.0 if d["abstention"] else 0.0))

L = []
L.append("# Mesures de récupération — 46 questions golden × 4 voies × 3 collections\n")
L.append(f"*{datetime.date.today().isoformat()} · vérité terrain exacte fournie (listes `fne_attendus`).*\n")

L.append("## Méthode — ce qui est mesuré, et comment\n")
L.append("**Vérité terrain** : pour chaque question, un **ensemble non ordonné** de fiches, "
         "à **pertinence binaire** — toutes les fiches de l'ensemble sont également pertinentes, "
         "aucune n'est « plus » pertinente. Le test est une appartenance à l'ensemble.\n")
L.append("| Métrique | Définition | Plafond |")
L.append("|---|---|---|")
L.append("| **précision@k** | bonnes fiches rendues / k | **100 % pour les 46 questions** "
         "(toutes ont n ≥ k, donc assez de bonnes réponses disponibles) |")
L.append("| **couverture** | bonnes rendues / min(k, n) — rappel normalisé | 100 % |")
L.append("| **MRR** | 1 / rang de la 1ʳᵉ bonne fiche | 1.00 |")
L.append(f"| **rappel@{PROF}** *(diagnostic)* | bonnes fiches présentes dans les {PROF} premiers chunks | n |")
L.append(f"\n> ⚠️ **Il n'y a aucun plafond sur la précision@k** : les 46 questions ont au moins k bonnes "
         f"réponses disponibles. Une précision de 40 % signifie donc que **6 fiches rendues sur 10 sont "
         f"fausses**, alors que la matière correcte existait en quantité suffisante. Les scores bas sont "
         f"de vrais échecs, pas un artefact du jeu de référence.\n")
L.append(f"*Le **rappel brut** est en revanche plafonné par construction* (on ne rend que k fiches "
         f"sur n, jusqu'à 73) : `rappel_max` moyen = {m(g['rappel_max'] for g in G):.0%}. "
         f"D'où la **couverture**, qui neutralise ce plafond.\n")

L.append("\n## 1. Résultats — toutes questions confondues\n")
L.append("| Voie (méthode) | Collection | précision@k | couverture | MRR | abstentions |")
L.append("|---|---|---:|---:|---:|---:|")
for mode in MODES:
    for _, lab in COLLS:
        a = agg[(mode, lab)]
        if not a["prec"]:
            continue
        L.append(f"| {mode} | {lab} | {m(a['prec']):.0%} | {m(a['couv']):.0%} | {m(a['mrr']):.2f} | "
                 f"{int(sum(a['abst']))}/{len(a['abst'])} |")

L.append("\n## 2. Par type de question — précision@k\n")
for voie in ("recherche", "cause", "action"):
    nq = sum(1 for g in G if g["voie"] == voie)
    L.append(f"\n**Questions « {voie} »** ({nq} questions)\n")
    L.append("| Méthode | Ancien | Enrichi | Hybride |")
    L.append("|---|---:|---:|---:|")
    for mode in MODES:
        cells = []
        for _, lab in COLLS:
            a = par_voie[(voie, mode, lab)]
            cells.append(f"{m(a['prec']):.0%}" if a["prec"] else "—")
        L.append(f"| {mode} | " + " | ".join(cells) + " |")

L.append(f"\n## 3. Diagnostic — panne de rappel vs panne de classement\n")
L.append(f"Mesuré sur les **{PROF} premiers chunks** (récupération dense pure, avant tout reranking).\n")
L.append("- **Jamais vue** : aucune bonne fiche dans les 50 chunks → problème d'**embedding / de chunk**. "
         "Augmenter k ou brancher un reranker **n'y changera rien**.\n")
L.append("- **Vue mais mal classée** : au moins une bonne fiche dans les 50, aucune dans les 10 premiers "
         "→ problème de **classement**, récupérable par un reranker ou un k plus grand.\n")
L.append("| Collection | jamais vue | vue mais mal classée | bonne dès le top 10 | rappel@50 moyen |")
L.append("|---|---:|---:|---:|---:|")
for _, lab in COLLS:
    jamais = sum(1 for g in G if diag[(g["id"], lab)]["vues"] == 0)
    malcl = sum(1 for g in G if diag[(g["id"], lab)]["vues"] > 0 and diag[(g["id"], lab)]["top10"] == 0)
    ok = sum(1 for g in G if diag[(g["id"], lab)]["top10"] > 0)
    rap = m(diag[(g["id"], lab)]["vues"] / g["n_pertinents"] for g in G)
    L.append(f"| {lab} | **{jamais}**/{len(G)} | {malcl}/{len(G)} | {ok}/{len(G)} | {rap:.0%} |")

L.append("\n## 4. Détail par question\n")
L.append(f"`P` = précision@k (meilleure méthode) · `vues` = bonnes fiches dans les {PROF} chunks · "
         "`r1` = rang de la 1ʳᵉ bonne.\n")
L.append("| id | question | voie | n | k | Ancien P / vues / r1 | Enrichi P / vues / r1 | Hybride P / vues / r1 |")
L.append("|---|---|---|---:|---:|---|---|---|")
for g in G:
    cells = []
    for _, lab in COLLS:
        best = max((d["prec"] for d in E if d["id"] == g["id"] and d["collection"] == lab), default=0)
        dg = diag[(g["id"], lab)]
        cells.append(f"{best:.0%} / {dg['vues']} / {dg['rang1'] or '—'}")
    L.append(f"| {g['id']} | {g['question'][:44]} | {g['voie']} | {g['n_pertinents']} | {g['k']} | "
             + " | ".join(cells) + " |")

L.append("\n## 5. Limites assumées\n")
L.append("1. **La vérité terrain fait foi.** Une fiche retrouvée mais absente de l'ensemble compte comme "
         "fausse, même si elle paraît pertinente. C'est la discipline qui évite de rationaliser les échecs.\n")
L.append("2. **On mesure la récupération, pas la réponse rédigée.** La génération LLM n'est pas évaluée ici.\n")
L.append("3. **Les blocs `cause` et `action`** testent une recherche *par* la cause / l'action. Or les voies "
         "de production récupèrent **par la description** puis **lisent** la cause et les actions dans le "
         "graphe. Ces blocs mesurent donc une capacité réelle des chunks, mais **non routée** aujourd'hui.\n")
L.append("4. **Asymétrie résiduelle** : dans l'Enrichi (v2b), le texte d'action est fusionné dans le chunk "
         "`fiche` — l'exclusion « problème↔problème » y est impossible, contrairement aux deux autres.\n")

open(BASE + "rapport_mesures.md", "w", encoding="utf-8").write("\n".join(L) + "\n")
print(f"\nécrit : {BASE}rapport_mesures.md")
for _, lab in COLLS:
    jamais = sum(1 for g in G if diag[(g["id"], lab)]["vues"] == 0)
    malcl = sum(1 for g in G if diag[(g["id"], lab)]["vues"] > 0 and diag[(g["id"], lab)]["top10"] == 0)
    print(f"  {lab:8} jamais vue={jamais:2}/46  mal classée={malcl:2}/46")
