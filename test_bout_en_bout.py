#!/usr/bin/env python3
"""A/B BOUT EN BOUT du correctif reranker — réponses de l'assistant, pas récupération.

A = API de production (ancien code)   B = API locale (code corrigé)
Même collection Qdrant, même Ollama, même reranker : le correctif est la seule variable.

Mesure, pour chaque question :
  - abstention (l'assistant refuse-t-il de répondre ?)
  - nombre de sources citées
  - sources pertinentes selon la vérité terrain du golden
  - la réponse rédigée (pour lecture humaine)
"""
import json, urllib.request, time, datetime

PROD = "http://172.16.6.10:8000"
LOCAL = "http://localhost:6001"
GOLD = "/home/yie0070/retex-split/retex-ingestion/golden_voies.jsonl"
OUT = "/home/yie0070/retex-split/retex-ingestion/resultats_bout_en_bout.md"

# questions du golden : celles où la réponse vit dans la cause ou l'action (le correctif y agit),
# plus des questions de recherche normale (témoins : rien ne doit se dégrader).
CIBLES = [
    "cause : agent nouvellement arrivé ou intérimaire",
    "cause : défaut de vigilance lors d'une manœuvre au poste",
    "cause : éblouissement ou visibilité réduite",
    "rappel des consignes après un incident de refus de priorité",
    "débriefing de l'agent après un incident impliquant un GSE",
    "modification d'une procédure ou d'un mode opératoire",
    "un oiseau a été ingéré par un moteur",           # témoin recherche
    "porte de soute restée ouverte",                   # témoin recherche
    "fuite d'huile constatée sous un aéronef au poste", # témoin recherche
]

ABSTENTION = ("aucune source", "je n'ai pas trouvé", "aucun incident", "hors du périmètre",
              "pas de fiche", "aucune fiche")


def ask(base, question, timeout=180):
    body = json.dumps({"question": question, "top_k": 8}).encode()
    r = urllib.request.Request(f"{base}/ask/incident-v2", data=body,
                               headers={"Content-Type": "application/json"}, method="POST")
    t = time.time()
    d = json.load(urllib.request.urlopen(r, timeout=timeout))
    return d, time.time() - t


def sources_de(d):
    for cle in ("sources", "incidents"):
        v = d.get(cle)
        if isinstance(v, list):
            return [x.get("numero_fe") for x in v if isinstance(x, dict) and x.get("numero_fe")]
    diag = d.get("diagnostic") or {}
    v = diag.get("sources")
    if isinstance(v, list):
        return [x.get("numero_fe") for x in v if isinstance(x, dict) and x.get("numero_fe")]
    return []


def main():
    G = {g["question"]: set(g["fne_attendus"]) for g in
         (json.loads(l) for l in open(GOLD, encoding="utf-8"))}
    L = ["# A/B bout en bout — correctif du reranker\n",
         f"*{datetime.date.today().isoformat()} · **A** = API de production (ancien code) · "
         "**B** = API locale (code corrigé). Même collection `incident_chunks`, même Ollama, "
         "même reranker : le correctif est la seule variable.*\n",
         "\n| Question | A : sources (bonnes) | B : sources (bonnes) | A abstient | B abstient |",
         "|---|---:|---:|:-:|:-:|"]
    detail = []
    for q in CIBLES:
        rel = G.get(q, set())
        ligne = {"q": q, "rel": len(rel)}
        for nom, base in (("A", PROD), ("B", LOCAL)):
            try:
                d, dt = ask(base, q)
                rep = (d.get("answer") or d.get("reponse") or "")
                src = sources_de(d)
                ligne[nom] = {"n": len(src), "bons": sum(1 for s in src if s in rel),
                              "abst": any(m in rep.lower() for m in ABSTENTION),
                              "rep": " ".join(rep.split())[:400], "s": dt}
            except Exception as e:
                ligne[nom] = {"n": 0, "bons": 0, "abst": None, "rep": f"ERREUR {e}", "s": 0}
            print(f"  [{nom}] {q[:46]:46} {ligne[nom]['n']:2} sources, "
                  f"{ligne[nom]['bons']:2} bonnes, {ligne[nom]['s']:.0f}s", flush=True)
        a, b = ligne["A"], ligne["B"]
        L.append(f"| {q[:44]} | {a['n']} ({a['bons']}) | **{b['n']} ({b['bons']})** | "
                 f"{'oui' if a['abst'] else 'non'} | {'oui' if b['abst'] else 'non'} |")
        detail.append(ligne)

    ta = sum(x["A"]["bons"] for x in detail); tb = sum(x["B"]["bons"] for x in detail)
    aa = sum(1 for x in detail if x["A"]["abst"]); ab = sum(1 for x in detail if x["B"]["abst"])
    L.append(f"| **TOTAL** | **{sum(x['A']['n'] for x in detail)} ({ta})** | "
             f"**{sum(x['B']['n'] for x in detail)} ({tb})** | **{aa}** | **{ab}** |")
    L.append("\n## Réponses rédigées — comparaison\n")
    for x in detail:
        L.append(f"\n### « {x['q']} »  *({x['rel']} fiches pertinentes)*\n")
        L.append(f"**A — production** ({x['A']['n']} sources, {x['A']['bons']} bonnes) :\n")
        L.append(f"> {x['A']['rep']}\n")
        L.append(f"**B — corrigé** ({x['B']['n']} sources, {x['B']['bons']} bonnes) :\n")
        L.append(f"> {x['B']['rep']}\n")
    open(OUT, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"\nTOTAL sources bonnes : A={ta}  B={tb}   ·   abstentions : A={aa}  B={ab}")
    print(f"écrit : {OUT}")


if __name__ == "__main__":
    main()
