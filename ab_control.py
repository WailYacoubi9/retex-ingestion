"""
A/B CONTRÔLE + PARAPHRASE — teste la zone où on n'attend PAS de gain (anti biais
de sélection). CTRL : requêtes standard où l'ancien est déjà bon -> vérifier qu'on
ne régresse pas. PARA : même intention formulée AUTREMENT que le vocabulaire du
titre/type -> l'enrichi généralise-t-il, ou sur-apprend-il la formulation standard ?
Précision@25 + MRR, par classe, + bootstrap CI apparié.
"""
from __future__ import annotations
import json, re, unicodedata, statistics, random
from clients import OllamaClient
from qdrant_client import QdrantClient
from qdrant_client.http.models import Filter, FieldCondition, MatchValue

OLD, NEW = "incident_chunks", "incident_chunks_v2b"
SRC = "data/samples/incidents_avec_actions.json"
def nz(s):
    s="".join(c for c in unicodedata.normalize("NFD",str(s or "").lower()) if unicodedata.category(c)!="Mn")
    return re.sub(r"\s+"," ",s).strip()
D=json.load(open(SRC)); FICHE={r.get("Num F.E."):r for r in D if r.get("Num F.E.")}
def typ(r): return nz(r.get("type d'événement (ECC)"))
def titre(r): return nz(r.get("titre"))
CH=["Description de l'événement et de son contexte","Analyse à chaud","titre","desc cause 1","desc cause 3"]
def txt(r): return nz(" ".join(str(r.get(k) or "") for k in CH))

QUERIES = [
 ("CTRL","collision aviaire", lambda r:"collision aviaire" in typ(r)),
 ("CTRL","FOD sur la piste", lambda r:"fod" in typ(r)),
 ("CTRL","quasi-collision entre un avion et un véhicule", lambda r:"quasi-collision" in typ(r) or "quasi collision" in typ(r)),
 ("CTRL","déroutement d'un vol vers Lyon", lambda r:"deroutement" in titre(r) or "deroutement" in typ(r)),
 ("CTRL","incursion sur la piste", lambda r:"incursion" in typ(r)),
 ("PARA","un oiseau a été percuté au décollage", lambda r:"collision aviaire" in typ(r)),
 ("PARA","un objet traînait sur le tarmac et présentait un risque", lambda r:"fod" in typ(r)),
 ("PARA","l'appareil a renoncé à se poser et s'est dérouté", lambda r:"deroutement" in titre(r) or "deroutement" in typ(r)),
 ("PARA","un camion a failli heurter un avion sur l'aire", lambda r:("quasi-collision" in typ(r) or "quasi collision" in typ(r))),
 ("PARA","une personne non autorisée a pénétré en zone", lambda r:bool(re.search(r"intrusion|penetr|zone reservee|non autorise|presence indesirable",txt(r))) or "presence indesirable" in typ(r)),
 ("PARA","incident pendant le remplissage en carburant", lambda r:bool(re.search(r"avitaillement|plein.{0,10}carburant|remplissage",txt(r))) or "avitaillement" in typ(r)),
]

def top_fiches(cl, coll, vec, k=25, fetch=200):
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
    from collections import defaultdict
    P={OLD:[],NEW:[]}; RR={OLD:[],NEW:[]}; perclasse={OLD:defaultdict(list),NEW:defaultdict(list)}; rows=[]
    for cls,q,pred in QUERIES:
        rel=set(fe for fe,r in FICHE.items() if pred(r))
        vec=ol.embed(q); row={"cls":cls,"q":q,"rel":len(rel)}
        for coll in (OLD,NEW):
            top=top_fiches(cl,coll,vec)
            hit=[i for i,fe in enumerate(top) if fe in rel]
            p25=len(hit)/25; rr=1/(hit[0]+1) if hit else 0.0
            P[coll].append(p25); RR[coll].append(rr); perclasse[coll][cls].append(p25); row[f"p_{coll}"]=p25
        rows.append(row)
    n=len(rows); m=statistics.mean
    print("="*80); print(f"A/B CONTRÔLE + PARAPHRASE — {n} requêtes (zone SANS gain attendu)"); print("="*80)
    print(f"\n  {'métrique':16} {'ANCIEN':>8} {'NOUVEAU':>9} {'Δ':>7}")
    print(f"  {'précision@25':16} {m(P[OLD]):>7.0%} {m(P[NEW]):>8.0%} {m(P[NEW])-m(P[OLD]):>+6.0%}")
    print(f"  {'MRR':16} {m(RR[OLD]):>7.2f} {m(RR[NEW]):>8.2f} {m(RR[NEW])-m(RR[OLD]):>+6.2f}")
    print("\n  précision@25 par classe :")
    for cls in ("CTRL","PARA"):
        o=m(perclasse[OLD][cls]); nn=m(perclasse[NEW][cls])
        print(f"    {cls} (n={len(perclasse[OLD][cls])}) : old={o:.0%}  new={nn:.0%}  Δ={nn-o:+.0%}")
    deltas=[a-b for a,b in zip(P[NEW],P[OLD])]; B=3000; mm=[]
    for _ in range(B): mm.append(sum(random.choice(deltas) for _ in range(n))/n)
    mm.sort(); lo,hi=mm[int(0.025*B)],mm[int(0.975*B)]
    print(f"\n  Δ précision@25 = {m(deltas):+.1%}   IC95 [{lo:+.1%} ; {hi:+.1%}]"
          f"  -> {'régression significative' if hi<0 else ('gain significatif' if lo>0 else 'neutre (IC contient 0) = PAS de régression')}")
    print("\n  détail (précision@25) :")
    for r in sorted(rows,key=lambda x:x['p_'+NEW]-x['p_'+OLD]):
        print(f"    [{r['cls']}] {r['q'][:46]:46} rel={r['rel']:4} old={r['p_'+OLD]:.0%} new={r['p_'+NEW]:.0%} Δ={r['p_'+NEW]-r['p_'+OLD]:+.0%}")

if __name__=="__main__":
    main()
