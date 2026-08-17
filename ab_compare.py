"""
A/B récupération : ancien index (incident_chunks, 1 chunk/champ) vs nouveau
(incident_chunks_v2b, 1 chunk/fiche enrichie). Même modèle bge-m3, même pipeline.

Mesure sur FICHES DISTINCTES (dédup) — indispensable : l'ancien a ~3 chunks/fiche,
le nouveau 1 ; comparer « top-k chunks » serait truqué.
Métrique principale = précision@k (part du top-k réellement pertinente = l'inverse
des faux positifs). Rappel@k affiché relatif à min(k, |pertinent|).

À lancer dans ia-build : docker exec -w /app ia-build python ab_compare.py
"""
from __future__ import annotations
import json, unicodedata, re, statistics
from collections import defaultdict

from clients import OllamaClient
from qdrant_client import QdrantClient
from qdrant_client.http.models import Filter, FieldCondition, MatchValue

OLD = "incident_chunks"
NEW = "incident_chunks_v2b"
KS = [5, 10, 20, 25]
FETCH = 200               # chunks récupérés avant dédup (large pour l'ancien)
SOURCE = "data/samples/incidents_avec_actions.json"
QDRANT_URL = "http://qdrant:6333"
OLLAMA_URL = "http://ollama:11434"

def nz(s):
    s = str(s or "").lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()

# ---- source indexée par numero_fe pour évaluer la pertinence ----
D = json.load(open(SOURCE))
FICHE = {r.get("Num F.E."): r for r in D if r.get("Num F.E.")}

def champ(r, k): return nz(r.get(k))
def annee(r):
    m = re.search(r"\b(\d{4})\b", str(r.get("date de l'évènement (ECC)") or ""))
    return m.group(1) if m else ""
def typ(r): return champ(r, "type d'événement (ECC)")
def lieu(r): return champ(r, "lieu de l'évènement (ECC)")
def prec(r): return champ(r, "précisions sur le lieu (ECC)")
def cond(r): return champ(r, "Lors de l'évènement, il faisait")
def compagnie(r): return champ(r, "la compagnie (ECC)") + " " + champ(r, "autre compagnie")
def titre(r): return champ(r, "titre")

# ---- jeu de requêtes stratifié par QUADRANT (texte, prédicat, quadrant) ----
# Deux mécanismes orthogonaux (H-métadonnées × duplication de titres) :
#   fusion        titres dupliqués + métadonnées constantes  -> gain attendu par FUSION
#   metadonnees   titres uniques + métadonnées variées        -> gain attendu par MÉTADONNÉES
#   les-deux      les deux effets
#   fusion-faible fusion mais peu de matière
# Stratifier évite qu'un jeu dominé par un quadrant conclue à tort sur l'autre.
QUERIES = [
    ("collisions aviaires sur la 36L",
     lambda r: "collision aviaire" in typ(r) and ("36l" in prec(r) or "36l" in titre(r)), "fusion"),
    ("collisions aviaires en 2024",
     lambda r: "collision aviaire" in typ(r) and annee(r) == "2024", "fusion"),
    ("quasi-collision entre aéronefs",
     lambda r: "quasi-collision" in typ(r) or "quasi collision" in typ(r), "fusion"),
    ("fuite hydraulique",
     lambda r: "fuite hydraulique" in titre(r) or ("fod" in typ(r) and "hydraulique" in titre(r)), "fusion"),
    ("déroutement sur Lyon",
     lambda r: "deroutement" in titre(r) or "deroutement" in typ(r), "fusion"),
    ("les baisses de niveau du SSLIA",
     lambda r: "sslia" in titre(r) or ("baisse" in titre(r) and ("np" in titre(r) or "niveau" in titre(r))), "fusion"),
    ("les collisions animales",
     lambda r: "collision animale" in typ(r), "fusion-faible"),
    ("défaillances de balisage ou d'éclairage",
     lambda r: "balisage" in typ(r) or "eclairage" in typ(r) or "balisage" in titre(r), "metadonnees"),
    ("incidents de nuit sur une aire de trafic",
     lambda r: "nuit" in cond(r) and "aire" in lieu(r), "metadonnees"),
    ("incidents impliquant Air France",
     lambda r: "air france" in compagnie(r), "metadonnees"),
    ("FOD sur l'aire de trafic",
     lambda r: "fod" in typ(r) and "aire de trafic" in lieu(r), "les-deux"),
    ("FOD en 2019",
     lambda r: "fod" in typ(r) and annee(r) == "2019", "les-deux"),
    ("incursion sur piste",
     lambda r: "incursion" in typ(r), "les-deux"),
    ("les refus de priorité au roulage",
     lambda r: "refus" in titre(r) and "priorit" in titre(r), "les-deux"),
]

def fiches_ordonnees(client, coll, vector, limit_chunks):
    """Recherche top-chunks puis dédup en fiches (ordre de score préservé)."""
    res = client.query_points(
        collection_name=coll, query=vector, limit=limit_chunks, with_payload=True,
        query_filter=Filter(must_not=[FieldCondition(key="is_test_data", match=MatchValue(value=True))]),
    ).points
    vus, ordre = set(), []
    for p in res:
        fe = (p.payload or {}).get("numero_fe")
        if fe and fe not in vus:
            vus.add(fe); ordre.append(fe)
    return ordre

def main():
    ollama = OllamaClient(url=OLLAMA_URL)
    client = QdrantClient(url=QDRANT_URL)
    # agrégats : agg[coll][k] = liste des précisions ; idem rappel
    prec_agg = {OLD: defaultdict(list), NEW: defaultdict(list)}
    rec_agg  = {OLD: defaultdict(list), NEW: defaultdict(list)}
    detail = []

    for texte, predicat, nature in QUERIES:
        total_rel = sum(1 for r in FICHE.values() if predicat(r))
        vec = ollama.embed(texte)
        ligne = {"q": texte, "nature": nature, "total_rel": total_rel}
        for coll in (OLD, NEW):
            ordre = fiches_ordonnees(client, coll, vec, FETCH)
            for k in KS:
                topk = ordre[:k]
                tp = sum(1 for fe in topk if fe in FICHE and predicat(FICHE[fe]))
                prec_agg[coll][k].append(tp / k)
                rec_agg[coll][k].append(tp / min(k, total_rel) if total_rel else 0.0)
                if k == 10:
                    ligne[f"p@10_{'old' if coll==OLD else 'new'}"] = round(tp/10, 2)
            # exemples de faux positifs (nouveau) au k=10
            if coll == NEW:
                fps = [fe for fe in ordre[:10] if not (fe in FICHE and predicat(FICHE[fe]))][:3]
                ligne["fp_new@10"] = fps
        detail.append(ligne)

    print("="*78)
    print("A/B RÉCUPÉRATION — ancien (par champ) vs nouveau (fiche enrichie)")
    print("fiches distinctes · bge-m3 · précision@k (macro-moyenne)")
    print("="*78)
    print(f"\n{'k':>4} | {'précision ANCIEN':>18} | {'précision NOUVEAU':>18} | {'Δ':>7}")
    print("-"*56)
    for k in KS:
        po = statistics.mean(prec_agg[OLD][k]); pn = statistics.mean(prec_agg[NEW][k])
        print(f"{k:>4} | {po:>17.1%} | {pn:>17.1%} | {pn-po:>+6.1%}")
    print(f"\n{'k':>4} | {'rappel ANCIEN':>18} | {'rappel NOUVEAU':>18} | {'Δ':>7}")
    print("-"*56)
    for k in KS:
        ro = statistics.mean(rec_agg[OLD][k]); rn = statistics.mean(rec_agg[NEW][k])
        print(f"{k:>4} | {ro:>17.1%} | {rn:>17.1%} | {rn-ro:>+6.1%}")

    print("\n--- précision@10 PAR QUADRANT (isole fusion vs métadonnées) ---")
    q_old, q_new = defaultdict(list), defaultdict(list)
    for l in detail:
        q_old[l["nature"]].append(l.get("p@10_old", 0))
        q_new[l["nature"]].append(l.get("p@10_new", 0))
    print(f"  {'quadrant':14} {'n':>2} | {'ANCIEN':>7} {'NOUVEAU':>8} {'Δ':>7}")
    for quad in ("fusion", "fusion-faible", "metadonnees", "les-deux"):
        if quad in q_old:
            o = statistics.mean(q_old[quad]); n = statistics.mean(q_new[quad])
            print(f"  {quad:14} {len(q_old[quad]):>2} | {o:>6.0%} {n:>7.0%} {n-o:>+6.0%}")

    print("\n--- par requête (précision@10) ---")
    for l in detail:
        print(f"  [{l['nature'][:12]:12}] {l['q'][:40]:40} | pert={l['total_rel']:4} | "
              f"old={l.get('p@10_old',0):.0%}  new={l.get('p@10_new',0):.0%}")
    print("\n--- exemples de faux positifs NOUVEAU @10 (fiches remontées non pertinentes) ---")
    for l in detail:
        if l.get("fp_new@10"):
            print(f"  {l['q'][:42]:42} -> {l['fp_new@10']}")

if __name__ == "__main__":
    main()
