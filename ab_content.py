"""
A/B CONTENU — casse la circularité : la pertinence est définie par le CONTENU du
texte libre (espèce, scénario), qui n'est PAS dans la ligne de métadonnées de
l'enrichi. Donc tout gain vient de la FUSION (narratif remonté), pas d'un champ injecté.
Ensemble pertinent EXHAUSTIF (scan des 9 191) -> vrai recall. + précision@k + MRR +
bootstrap CI apparié sur le delta de précision@25.
"""
from __future__ import annotations
import os, json, re, unicodedata, statistics, random
from clients import OllamaClient
from qdrant_client import QdrantClient
from qdrant_client.http.models import Filter, FieldCondition, MatchValue

OLD = "incident_chunks"
NEW = os.environ.get("NEW_COLL", "incident_chunks_v2b")
SRC = "data/samples/incidents_avec_actions.json"

def nz(s):
    s="".join(c for c in unicodedata.normalize("NFD",str(s or "").lower()) if unicodedata.category(c)!="Mn")
    return re.sub(r"\s+"," ",s).strip()
D=json.load(open(SRC)); FICHE={r.get("Num F.E."):r for r in D if r.get("Num F.E.")}
CH=["Description de l'événement et de son contexte","Analyse à chaud","Action corrective immédiate",
    "desc cause 1","desc cause 2","desc cause 3","desc cause 5","desc cause 6","détail de la vérification","titre"]
def txt(r): return nz(" ".join(str(r.get(k) or "") for k in CH))

# (question, motif de pertinence CONTENU — absent des métadonnées)
QUERIES = [
 ("collisions avec un faucon crécerelle", r"crecerelle"),
 ("oiseau retrouvé mort sur la piste", r"oiseau.{0,30}mort|mort.{0,15}oiseau|cadavre.{0,15}oiseau|collect\w* .{0,20}(oiseau|volatile)"),
 ("fuite de kérosène ou de carburant", r"kerosene|fuite.{0,15}carburant|epandage.{0,15}carburant"),
 ("escabeau ou échelle oublié sur le tarmac", r"escabeau|echelle"),
 ("intrusion par un grillage ou clôture coupée", r"grillage|cloture|intrusion"),
 ("baisse SSLIA au centre de rétention", r"centre de retention|retention administrative|\bcra\b"),
 ("passager agressif refusant les consignes", r"passager.{0,25}(agress|refus|indiscipl|perturbat)|paxi"),
 ("chariot ou GSE mal stationné gênant", r"chariot.{0,20}(genant|stationn)|gse.{0,15}(genant|mal)|materiel.{0,10}genant"),
 ("remise de gaz à l'approche", r"remise de gaz|go.?around|approche interrompue"),
 ("déversement d'huile ou de fluide hydraulique", r"huile|hydraulique|fluide"),
 ("chien ou animal errant sur l'aire", r"chien|lievre|renard|animal.{0,15}(errant|aire|piste)"),
]

def top_fiches(cl, coll, vec, k, fetch=250, field=None):
    must=[FieldCondition(key="field_canonical", match=MatchValue(value=field))] if field else []
    res=cl.query_points(collection_name=coll, query=vec, limit=fetch, with_payload=True,
        query_filter=Filter(must=must, must_not=[FieldCondition(key="is_test_data", match=MatchValue(value=True))])).points
    vus,out=set(),[]
    for p in res:
        fe=(p.payload or {}).get("numero_fe")
        if fe and fe not in vus: vus.add(fe); out.append(fe)
        if len(out)>=k: break
    return out

def main():
    ol=OllamaClient(url="http://ollama:11434"); cl=QdrantClient(url="http://qdrant:6333")
    p10={OLD:[],NEW:[]}; p25={OLD:[],NEW:[]}; rr={OLD:[],NEW:[]}; rec25={OLD:[],NEW:[]}
    rows=[]
    for q,pat in QUERIES:
        rx=re.compile(pat)
        rel=set(fe for fe,r in FICHE.items() if rx.search(txt(r)))
        if not rel: continue
        vec=ol.embed(q)
        row={"q":q,"rel":len(rel)}
        FF=os.environ.get("FIELD_FILTER")
        for coll in (OLD,NEW):
            top=top_fiches(cl,coll,vec,25, field=(FF if coll==NEW else None))
            hit=[i for i,fe in enumerate(top) if fe in rel]
            p10v=sum(1 for i in hit if i<10)/10
            p25v=len(hit)/25
            recv=len([fe for fe in top if fe in rel])/min(25,len(rel))
            rrv=1/(hit[0]+1) if hit else 0.0
            p10[coll].append(p10v); p25[coll].append(p25v); rr[coll].append(rrv); rec25[coll].append(recv)
            row[f"p25_{coll}"]=p25v; row[f"p10_{coll}"]=p10v
        rows.append(row)

    n=len(rows)
    def m(x): return statistics.mean(x)
    print("="*80)
    print(f"A/B CONTENU — {n} questions · pertinence = CONTENU texte (hors métadonnées)")
    print("test PROPRE de la fusion (pas de champ injecté) · ancien vs nouveau")
    print("="*80)
    print(f"\n  {'métrique':16} {'ANCIEN':>8} {'NOUVEAU':>9} {'Δ':>7}")
    print(f"  {'précision@10':16} {m(p10[OLD]):>7.0%} {m(p10[NEW]):>8.0%} {m(p10[NEW])-m(p10[OLD]):>+6.0%}")
    print(f"  {'précision@25':16} {m(p25[OLD]):>7.0%} {m(p25[NEW]):>8.0%} {m(p25[NEW])-m(p25[OLD]):>+6.0%}")
    print(f"  {'MRR':16} {m(rr[OLD]):>7.2f} {m(rr[NEW]):>8.2f} {m(rr[NEW])-m(rr[OLD]):>+6.2f}")
    print(f"  {'recall@25':16} {m(rec25[OLD]):>7.0%} {m(rec25[NEW]):>8.0%} {m(rec25[NEW])-m(rec25[OLD]):>+6.0%}")

    # bootstrap CI apparié sur le delta de précision@25
    deltas=[a-b for a,b in zip(p25[NEW],p25[OLD])]
    B=3000; means=[]
    for _ in range(B):
        s=[random.choice(deltas) for _ in range(n)]
        means.append(sum(s)/n)
    means.sort()
    lo,hi=means[int(0.025*B)],means[int(0.975*B)]
    print(f"\n  Δ précision@25 = {m(deltas):+.1%}   IC95 bootstrap [{lo:+.1%} ; {hi:+.1%}]"
          f"   -> {'SIGNIFICATIF (>0)' if lo>0 else ('SIGNIFICATIF (<0)' if hi<0 else 'NON significatif (IC contient 0)')}")

    print("\n  détail par question (précision@25) :")
    for r in sorted(rows,key=lambda x:-(x['p25_'+NEW]-x['p25_'+OLD])):
        print(f"    {r['q'][:44]:44} rel={r['rel']:4}  old={r['p25_'+OLD]:.0%}  new={r['p25_'+NEW]:.0%}  Δ={r['p25_'+NEW]-r['p25_'+OLD]:+.0%}")

if __name__=="__main__":
    main()
