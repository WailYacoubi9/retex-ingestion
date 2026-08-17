"""
Banc CONTRAINT : mesure la désambiguïsation (là où precision@10 sur requête large
est aveugle). Pour chaque « base × discriminant enregistré » à ≥8 fiches réponses :
precision@10 contrainte + MRR (rang du 1er pertinent), ancien vs nouveau.
Agrégé + par catégorie de discriminant (année/piste/lieu/compagnie/aéronef).
"""
from __future__ import annotations
import json, re, unicodedata, statistics
from collections import defaultdict
from clients import OllamaClient
from qdrant_client import QdrantClient
from qdrant_client.http.models import Filter, FieldCondition, MatchValue

OLD, NEW = "incident_chunks", "incident_chunks_v2b"
SRC = "data/samples/incidents_avec_actions.json"
MIN_REL = 8

def nz(s):
    s="".join(c for c in unicodedata.normalize("NFD",str(s or "").lower()) if unicodedata.category(c)!="Mn")
    return re.sub(r"\s+"," ",s).strip()
D=json.load(open(SRC)); FICHE={r.get("Num F.E."):r for r in D if r.get("Num F.E.")}
def annee(r):
    m=re.search(r"\b(\d{4})\b",str(r.get("date de l'évènement (ECC)") or "")); return m.group(1) if m else ""
def typ(r): return nz(r.get("type d'événement (ECC)"))
def titre(r): return nz(r.get("titre"))
def prec(r): return nz(r.get("précisions sur le lieu (ECC)"))
def lieu(r): return nz(r.get("lieu de l'évènement (ECC)"))
def comp(r): return nz(r.get("la compagnie (ECC)"))+" "+nz(r.get("autre compagnie"))
def taero(r): return nz(r.get("type d'aéronef (ECC)"))

BASES = [
    ("collision aviaire", lambda r:"collision aviaire" in typ(r)),
    ("FOD", lambda r:"fod" in typ(r)),
    ("quasi-collision", lambda r:"quasi-collision" in typ(r) or "quasi collision" in typ(r)),
    ("incursion sur piste", lambda r:"incursion" in typ(r)),
    ("refus de priorité", lambda r:"refus" in titre(r) and "priorit" in titre(r)),
    ("déroutement", lambda r:"deroutement" in titre(r) or "deroutement" in typ(r)),
]
DISCS = [
    ("année","en 2009", lambda r:annee(r)=="2009"), ("année","en 2010", lambda r:annee(r)=="2010"),
    ("année","en 2015", lambda r:annee(r)=="2015"), ("année","en 2019", lambda r:annee(r)=="2019"),
    ("année","en 2022", lambda r:annee(r)=="2022"), ("année","en 2024", lambda r:annee(r)=="2024"),
    ("piste","sur la 36L", lambda r:"36l" in prec(r) or "36l" in titre(r)),
    ("piste","sur la 35L", lambda r:"35l" in prec(r) or "35l" in titre(r)),
    ("piste","sur la 36R", lambda r:"36r" in prec(r) or "36r" in titre(r)),
    ("lieu","sur l'aire de trafic", lambda r:"aire de trafic" in lieu(r)),
    ("lieu","sur la piste", lambda r:lieu(r)=="piste"),
    ("lieu","au parking", lambda r:"parking" in lieu(r)),
    ("compagnie","impliquant Air France", lambda r:"air france" in comp(r)),
    ("compagnie","impliquant Easyjet", lambda r:"easyjet" in comp(r)),
    ("aéronef","avec un A320", lambda r:"a320" in taero(r)),
    ("aéronef","avec un A319", lambda r:"a319" in taero(r)),
]

def fiches_top(cl, coll, vec, k=10, fetch=150):
    res=cl.query_points(collection_name=coll, query=vec, limit=fetch, with_payload=True,
        query_filter=Filter(must_not=[FieldCondition(key="is_test_data", match=MatchValue(value=True))])).points
    vus,out=set(),[]
    for p in res:
        fe=(p.payload or {}).get("numero_fe")
        if fe and fe not in vus: vus.add(fe); out.append(fe)
        if len(out)>=k: break
    return out

def main():
    ol=OllamaClient(url="http://ollama:11434"); cl=QdrantClient(url="http://qdrant:6333")
    P={OLD:[],NEW:[]}; RR={OLD:[],NEW:[]}
    parcat={OLD:defaultdict(list),NEW:defaultdict(list)}
    lignes=[]
    for blab,bp in BASES:
        for cat,dsuf,dp in DISCS:
            pred=lambda r,bp=bp,dp=dp: bp(r) and dp(r)
            rel=sum(1 for r in FICHE.values() if pred(r))
            if rel<MIN_REL: continue
            vec=ol.embed(f"{blab} {dsuf}")
            row={"q":f"{blab} {dsuf}","cat":cat,"rel":rel}
            for coll in (OLD,NEW):
                top=fiches_top(cl,coll,vec)
                hits=[i for i,fe in enumerate(top) if fe in FICHE and pred(FICHE[fe])]
                p10=len(hits)/10; rr=1/(hits[0]+1) if hits else 0.0
                P[coll].append(p10); RR[coll].append(rr); parcat[coll][cat].append(p10)
                row[f"p_{coll}"]=p10; row[f"rr_{coll}"]=rr
            lignes.append(row)

    print("="*82); print(f"BANC CONTRAINT — {len(lignes)} requêtes (base × discriminant, ≥{MIN_REL} réponses)")
    print("précision@10 CONTRAINTE + MRR · fiches distinctes · ancien vs nouveau"); print("="*82)
    print(f"\n  {'métrique':22} {'ANCIEN':>8} {'NOUVEAU':>9} {'Δ':>8}")
    print(f"  {'précision@10 (moy.)':22} {statistics.mean(P[OLD]):>7.0%} {statistics.mean(P[NEW]):>8.0%} {statistics.mean(P[NEW])-statistics.mean(P[OLD]):>+7.0%}")
    print(f"  {'MRR (rang 1er bon)':22} {statistics.mean(RR[OLD]):>7.2f} {statistics.mean(RR[NEW]):>8.2f} {statistics.mean(RR[NEW])-statistics.mean(RR[OLD]):>+7.2f}")
    print("\n  précision@10 par catégorie de discriminant :")
    print(f"    {'catégorie':12} {'n':>2} {'ANCIEN':>8} {'NOUVEAU':>9} {'Δ':>8}")
    for cat in ("année","piste","lieu","compagnie","aéronef"):
        if parcat[OLD].get(cat):
            o=statistics.mean(parcat[OLD][cat]); n=statistics.mean(parcat[NEW][cat])
            print(f"    {cat:12} {len(parcat[OLD][cat]):>2} {o:>7.0%} {n:>8.0%} {n-o:>+7.0%}")
    print("\n  détail par requête (précision@10) :")
    for r in sorted(lignes,key=lambda x:-(x['p_'+NEW]-x['p_'+OLD])):
        print(f"    [{r['cat']:9}] {r['q'][:38]:38} rel={r['rel']:4}  old={r['p_'+OLD]:.0%}  new={r['p_'+NEW]:.0%}  Δ={r['p_'+NEW]-r['p_'+OLD]:+.0%}")

if __name__=="__main__":
    main()
