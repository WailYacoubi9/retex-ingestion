"""
Démo désambiguïsation : requêtes « collision aviaire 36L » CONTRAINTES.
Montre les fiches réelles remontées top-10, ancien (par champ) vs nouveau (fiche
enrichie), avec leurs attributs — pour voir si le nouveau index respecte la
contrainte (année/phase/nuit) là où l'ancien tirait au hasard parmi 212 titres
identiques.
À lancer dans un conteneur builder (réseau ia-net).
"""
from __future__ import annotations
import json, re, unicodedata
from clients import OllamaClient
from qdrant_client import QdrantClient
from qdrant_client.http.models import Filter, FieldCondition, MatchValue

OLD, NEW = "incident_chunks", "incident_chunks_v2b"
SRC = "data/samples/incidents_avec_actions.json"

def nz(s):
    s="".join(c for c in unicodedata.normalize("NFD",str(s or "").lower()) if unicodedata.category(c)!="Mn")
    return re.sub(r"\s+"," ",s).strip()
D=json.load(open(SRC)); FICHE={r.get("Num F.E."):r for r in D if r.get("Num F.E.")}
def annee(r):
    m=re.search(r"\b(\d{4})\b", str(r.get("date de l'évènement (ECC)") or "")); return m.group(1) if m else "----"
def phase(r): return nz(r.get("phase de vol (ECC)"))[:12] or "-"
def nuit(r): return "nuit" if "nuit" in nz(r.get("Lors de l'évènement, il faisait")) else "jour"
def prec(r): return nz(r.get("précisions sur le lieu (ECC)"))[:10]
def typ(r): return nz(r.get("type d'événement (ECC)"))
def est_36l(r): return "36l" in prec(r) or "36l" in nz(r.get("titre"))
def est_aviaire(r): return "collision aviaire" in typ(r)

# requête -> (texte, prédicat de la contrainte)
QUERIES = [
    ("collision aviaire sur la 36L en 2010", lambda r: est_aviaire(r) and est_36l(r) and annee(r)=="2010"),
    ("collision aviaire sur la 36L en 2024", lambda r: est_aviaire(r) and est_36l(r) and annee(r)=="2024"),
    ("collision aviaire sur la 36L de nuit", lambda r: est_aviaire(r) and est_36l(r) and nuit(r)=="nuit"),
    ("collision aviaire sur la 36L au décollage", lambda r: est_aviaire(r) and est_36l(r) and "decoll" in phase(r)),
]

def fiches_top(client, coll, vec, k=10, fetch=150):
    res=client.query_points(collection_name=coll, query=vec, limit=fetch, with_payload=True,
        query_filter=Filter(must_not=[FieldCondition(key="is_test_data", match=MatchValue(value=True))])).points
    vus,out=set(),[]
    for p in res:
        fe=(p.payload or {}).get("numero_fe")
        if fe and fe not in vus: vus.add(fe); out.append(fe)
        if len(out)>=k: break
    return out

def main():
    ol=OllamaClient(url="http://ollama:11434"); cl=QdrantClient(url="http://qdrant:6333")
    for texte,pred in QUERIES:
        tot=sum(1 for r in FICHE.values() if pred(r))
        vec=ol.embed(texte)
        print("\n"+"="*94); print(f"REQUÊTE : {texte}   (pertinents dans le corpus : {tot})"); print("="*94)
        for coll,lib in ((OLD,"ANCIEN (par champ)"),(NEW,"NOUVEAU (fiche enrichie)")):
            top=fiches_top(cl,coll,vec)
            ok=sum(1 for fe in top if fe in FICHE and pred(FICHE[fe]))
            print(f"\n  {lib}  — précision@10 = {ok}/10")
            for fe in top:
                r=FICHE.get(fe,{})
                mark="✓" if (fe in FICHE and pred(FICHE[fe])) else "·"
                print(f"    {mark} {fe:16s} {annee(r):>4}  {nuit(r):4}  {phase(r):12s} lieu:{prec(r):10s} {'AVIAIRE' if est_aviaire(r) else typ(r)[:16]}")

if __name__=="__main__":
    main()
