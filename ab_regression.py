"""
A/B ZONE DE RÉGRESSION ATTENDUE — requêtes qui ciblent le contenu d'UN champ
(cause OU action). Dans l'ancien, ce champ a un vecteur DÉDIÉ -> match précis.
Dans l'enrichi, il est DILUÉ dans le document-fiche. Hypothèse : le par-champ
(ANCIEN) devrait BATTRE le fusionné (NOUVEAU) ici. On cherche la régression.
Précision@25 + MRR + bootstrap CI apparié.
"""
from __future__ import annotations
import os, json, re, unicodedata, statistics, random
from clients import OllamaClient
from qdrant_client import QdrantClient
from qdrant_client.http.models import Filter, FieldCondition, MatchValue

OLD = "incident_chunks"
NEW = os.environ.get("NEW_COLL", "incident_chunks_v2b")
SRC="data/samples/incidents_avec_actions.json"
def nz(s):
    s="".join(c for c in unicodedata.normalize("NFD",str(s or "").lower()) if unicodedata.category(c)!="Mn")
    return re.sub(r"\s+"," ",s).strip()
D=json.load(open(SRC)); FICHE={r.get("Num F.E."):r for r in D if r.get("Num F.E.")}
CAUSES=["desc cause 1","desc cause 2","desc cause 3","desc cause 5","desc cause 6"]
def cause_txt(r): return nz(" ".join(str(r.get(k) or "") for k in CAUSES))
def action_txt(r):
    a=str(r.get("Action corrective immédiate") or "")
    for arr in ("actions_correctives","actions_preventives"):
        for act in (r.get(arr) or []):
            if isinstance(act,dict): a+=" "+str(act.get("titre de l'action") or "")+" "+str(act.get("détail") or "")
    return nz(a)

QUERIES=[
 ("CAUSE","erreur humaine ou manque de vigilance de l'agent", lambda r:bool(re.search(r"vigilance|inattention|erreur.{0,12}(humain|agent)|facteur humain",cause_txt(r)))),
 ("CAUSE","non-respect d'une procédure ou consigne", lambda r:bool(re.search(r"non.?respect|procedure non|consigne non|non conforme.{0,10}procedure",cause_txt(r)))),
 ("CAUSE","défaut de communication ou de coordination", lambda r:bool(re.search(r"communication|coordination|transmission.{0,10}info|defaut.{0,10}info",cause_txt(r)))),
 ("ACTION","rappel aux équipes ou sensibilisation", lambda r:bool(re.search(r"rappel.{0,15}equipe|sensibilis|rappel.{0,15}consigne",action_txt(r)))),
 ("ACTION","diffusion d'une note de service", lambda r:bool(re.search(r"diffusion.{0,15}note|note de service|note d.information",action_txt(r)))),
 ("ACTION","ramassage ou enlèvement du débris", lambda r:bool(re.search(r"ramass|enlevement|enlev\w+ .{0,10}(debris|fod|objet)|collecte.{0,15}(debris|fod)",action_txt(r)))),
]

def top_fiches(cl,coll,vec,k=25,fetch=200):
    res=cl.query_points(collection_name=coll,query=vec,limit=fetch,with_payload=True,
        query_filter=Filter(must_not=[FieldCondition(key="is_test_data",match=MatchValue(value=True))])).points
    vus,out=set(),[]
    for p in res:
        fe=(p.payload or {}).get("numero_fe")
        if fe and fe not in vus: vus.add(fe); out.append(fe)
        if len(out)>=k: break
    return out

def main():
    ol=OllamaClient(url="http://ollama:11434"); cl=QdrantClient(url="http://qdrant:6333")
    P={OLD:[],NEW:[]}; RR={OLD:[],NEW:[]}; rows=[]
    for cls,q,pred in QUERIES:
        rel=set(fe for fe,r in FICHE.items() if pred(r))
        vec=ol.embed(q); row={"cls":cls,"q":q,"rel":len(rel)}
        for coll in (OLD,NEW):
            top=top_fiches(cl,coll,vec)
            hit=[i for i,fe in enumerate(top) if fe in rel]
            row[f"p_{coll}"]=len(hit)/25
            P[coll].append(len(hit)/25); RR[coll].append(1/(hit[0]+1) if hit else 0.0)
        rows.append(row)
    n=len(rows); m=statistics.mean
    print("="*80); print(f"A/B ZONE DE RÉGRESSION ATTENDUE — {n} requêtes cause/action (champ ciblé)")
    print("hypothèse : ANCIEN (vecteur par champ) > NOUVEAU (fusionné dilué)"); print("="*80)
    print(f"\n  précision@25 : ANCIEN {m(P[OLD]):.0%}   NOUVEAU {m(P[NEW]):.0%}   Δ {m(P[NEW])-m(P[OLD]):+.0%}")
    print(f"  MRR          : ANCIEN {m(RR[OLD]):.2f}   NOUVEAU {m(RR[NEW]):.2f}   Δ {m(RR[NEW])-m(RR[OLD]):+.2f}")
    deltas=[a-b for a,b in zip(P[NEW],P[OLD])]; B=3000; mm=[]
    for _ in range(B): mm.append(sum(random.choice(deltas) for _ in range(n))/n)
    mm.sort(); lo,hi=mm[int(0.025*B)],mm[int(0.975*B)]
    verdict="RÉGRESSION significative" if hi<0 else ("gain significatif" if lo>0 else "neutre (IC contient 0)")
    print(f"  Δ = {m(deltas):+.1%}   IC95 [{lo:+.1%} ; {hi:+.1%}]  -> {verdict}")
    print("\n  détail (précision@25) :")
    for r in sorted(rows,key=lambda x:x['p_'+NEW]-x['p_'+OLD]):
        print(f"    [{r['cls']}] {r['q'][:44]:44} rel={r['rel']:4} old={r['p_'+OLD]:.0%} new={r['p_'+NEW]:.0%} Δ={r['p_'+NEW]-r['p_'+OLD]:+.0%}")

if __name__=="__main__":
    main()
