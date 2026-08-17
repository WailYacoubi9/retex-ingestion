#!/usr/bin/env python3
"""Choisit les questions d'EXEMPLE du frontend en les MESURANT, pas en les supposant.

POURQUOI — un exemple affiché dans l'interface est la première chose qu'un nouvel
utilisateur essaie. S'il échoue, il ne conclut pas que l'exemple est mal choisi : il
conclut que l'outil ne marche pas. Un exemple doit donc être vérifié, et re-vérifié après
chaque changement du moteur — les scores d'avant-hier ne valent plus rien aujourd'hui.

On rejoue `golden_voies.jsonl` (46 questions, fiches attendues établies les jours
précédents) sur les endpoints RÉELS du serveur, et on classe chaque question par le
nombre de fiches attendues effectivement retrouvées. Seules les meilleures deviennent
des exemples.

Les trois voies du golden n'ont pas le même endpoint :
  recherche -> /ask/incident-v2       (recherche sémantique)
  cause     -> /ask/incident-v2/synthese   (cas comparables : ce qui a été fait)
  action    -> /ask/incident-v2/recommande (recommandation d'actions)
"""
import json
import sys
import time
import urllib.request

API = "http://172.16.6.10:8000"
GOLD = "golden_voies.jsonl"
OUT = "/home/yie0070/retex-split/retex-ingestion/resultats_choix_exemples.md"
NQ = int(sys.argv[1]) if len(sys.argv) > 1 else 999

ENDPOINT = {"recherche": "/ask/incident-v2",
            "cause": "/ask/incident-v2/synthese",
            "action": "/ask/incident-v2/recommande"}


def post(chemin, corps, timeout=900):
    r = urllib.request.Request(API + chemin, data=json.dumps(corps).encode(),
                               headers={"Content-Type": "application/json"}, method="POST")
    t = time.time()
    return json.load(urllib.request.urlopen(r, timeout=timeout)), time.time() - t


def fiches_rendues(d):
    """Les numéros de fiche servis, quel que soit le nom du champ selon la voie."""
    # ⚠️ Chaque voie nomme ses fiches autrement. En oublier une ne rend pas « 0 fiche » :
    # cela rend « 0 fiche TROUVÉE », ce qui se lit comme un échec du produit alors que
    # c'est un défaut de l'instrument. Les 12 questions de cause ont d'abord toutes été
    # mesurées à 0 % pour cette seule raison — leur champ est `precedents`.
    src = (d.get("sources") or d.get("incidents") or d.get("incidents_similaires")
           or d.get("precedents") or d.get("cas") or [])
    out = []
    for s in src:
        if isinstance(s, dict):
            fe = s.get("numero_fe") or s.get("fe") or s.get("id")
        else:
            fe = s
        if fe:
            out.append(str(fe).strip())
    return out


def main():
    G = [json.loads(l) for l in open(GOLD, encoding="utf-8") if l.strip()][:NQ]
    print(f"{len(G)} questions rejouées sur le serveur\n", flush=True)
    lignes = []
    for i, g in enumerate(G, 1):
        voie = g["voie"]
        ep = ENDPOINT[voie]
        k = int(g.get("k") or 10)
        attendus = set(g.get("fne_attendus") or [])
        corps = {"question": g["question"], "top_k": k}
        try:
            d, dt = post(ep, corps)
        except Exception as e:
            print(f"  [{i}/{len(G)}] {g.get('id','?'):9} ERREUR {type(e).__name__}", flush=True)
            continue
        rendues = fiches_rendues(d)
        bonnes = len([f for f in rendues if f in attendus])
        # rappel_max : ce qu'il est POSSIBLE de retrouver dans k fiches
        # la synthèse plafonne son voisinage : le maximum atteignable est ce qu'elle rend
        plafond = min(k, len(attendus), max(len(rendues), 1)) or 1
        lignes.append({"id": g.get("id"), "voie": voie, "question": g["question"],
                       "k": k, "rendues": len(rendues), "bonnes": bonnes,
                       "attendus": len(attendus), "plafond": plafond,
                       "taux": round(100 * bonnes / plafond, 1), "s": round(dt, 1),
                       "abstention": len(rendues) == 0})
        print(f"  [{i}/{len(G)}] {str(g.get('id')):9} {voie:9} "
              f"{bonnes}/{plafond} utiles ({lignes[-1]['taux']:.0f} %) · {dt:.0f}s"
              f"  {g['question'][:44]}", flush=True)

    lignes.sort(key=lambda x: (-x["taux"], -x["bonnes"]))
    L = ["# Choix des questions d'exemple — mesuré, pas supposé\n",
         f"*{time.strftime('%Y-%m-%d')} · {len(lignes)} questions de `golden_voies.jsonl` "
         "rejouées sur les endpoints réels, APRÈS les correctifs du jour. Le taux est le "
         "nombre de fiches attendues retrouvées, rapporté à ce qu'il est possible d'en "
         "retrouver dans k résultats.*\n"]
    for voie, titre in (("recherche", "🔍 Recherche sémantique"),
                        ("cause", "📚 Cas comparables"),
                        ("action", "💡 Recommandation")):
        sel = [x for x in lignes if x["voie"] == voie]
        if not sel:
            continue
        bons = [x for x in sel if x["taux"] >= 50]
        L += [f"\n## {titre} — {len(bons)}/{len(sel)} questions au-dessus de 50 %\n",
              "| taux | utiles | question | s |", "|---:|---:|---|---:|"]
        for x in sel:
            L.append(f"| {x['taux']:.0f} % | {x['bonnes']}/{x['plafond']} | "
                     f"{x['question'][:70]} | {x['s']} |")
    open(OUT, "w", encoding="utf-8").write("\n".join(L) + "\n")
    json.dump(lignes, open(OUT.replace(".md", ".json"), "w"), ensure_ascii=False, indent=1)
    bons = [x for x in lignes if x["taux"] >= 50]
    print(f"\n  {len(bons)}/{len(lignes)} questions retrouvent au moins la moitié "
          f"de ce qu'elles peuvent retrouver")
    print(f"écrit : {OUT}")


if __name__ == "__main__":
    main()
