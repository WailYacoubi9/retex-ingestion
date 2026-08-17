#!/usr/bin/env python3
"""Golden CLIENT posé sur l'ASSISTANT seul — ce que vit vraiment un utilisateur.

POURQUOI CE HARNAIS — `test_golden_client.py` envoie chaque question à l'onglet qui la
traiterait le mieux. C'est la bonne mesure du MOTEUR, mais personne ne travaille comme ça :
un utilisateur tape sa question dans l'assistant et laisse le routeur choisir. L'écart entre
les deux mesures EST la performance du routeur, et elle n'avait jamais été évaluée.

On applique exactement le même barème que le harnais par voie (statuts EXACTE / PLAFOND /
ABSTENTION, mêmes fonctions de contrôle importées) : sans cela la comparaison ne voudrait
rien dire. La seule différence est l'endpoint.

Trois chiffres en sortie :
  - conformes via l'assistant, à comparer au harnais par voie ;
  - questions ROUTÉES AILLEURS que la voie attendue ;
  - parmi elles, celles où le mauvais aiguillage COÛTE la réponse (le seul défaut qui compte).
"""
import json
import time

from test_golden_client import GOLD, controler, post, texte_reponse

OUT = "/home/yie0070/retex-split/retex-ingestion/resultats_assistant_routeur.md"
PAR_VOIE = "/home/yie0070/retex-split/retex-ingestion/resultats_golden_client.json"

# Le routeur nomme ses voies autrement que le golden : on aligne le vocabulaire une fois.
EQUIV = {"analyse": "analyse", "agregation": "liste", "statistiques": "liste",
         "liste": "liste", "requete": "liste", "recherche": "recherche",
         "semantique": "recherche", "recommandation": "recommandation",
         "reco": "recommandation", "abstention": "abstention",
         "hors_domaine": "abstention", "synthese": "recherche"}


def main():
    G = [json.loads(l) for l in open(GOLD, encoding="utf-8") if l.strip()]
    try:
        par_voie = {x["id"]: x for x in json.load(open(PAR_VOIE))}
    except Exception:
        par_voie = {}
    print(f"{len(G)} questions client, toutes envoyées à l'ASSISTANT\n", flush=True)

    lignes = []
    for i, g in enumerate(G, 1):
        try:
            d, dt = post("/ask/incident-v2/auto", {"question": g["question"], "top_k": 10})
            rep = texte_reponse(d)
        except Exception as e:
            print(f"  [{i}/{len(G)}] {g['id']:8} ERREUR {type(e).__name__}", flush=True)
            lignes.append({"id": g["id"], "statut": g.get("statut"), "ok": False, "s": 0,
                           "erreur": type(e).__name__})
            continue
        c = controler(g, rep)
        choisie = d.get("voie_choisie") or "?"
        attendue = g.get("voie_attendue")
        bonne = EQUIV.get(str(choisie).lower(), str(choisie).lower()) == attendue
        ref = par_voie.get(g["id"], {})
        lignes.append({"id": g["id"], "question": g["question"], "voie_choisie": choisie,
                       "voie_attendue": attendue, "bon_aiguillage": bonne,
                       "ok_par_voie": ref.get("ok"), "trouves_par_voie": ref.get("trouves"),
                       "rep": rep[:400], "s": round(dt, 1), **c})
        print(f"  [{i}/{len(G)}] {g['id']:8} {str(choisie):16}"
              f"{'' if bonne else ' (attendu ' + str(attendue) + ')':22}"
              f" {'✅' if c.get('ok') else '❌'} {c.get('detail', '')} · {dt:.0f}s", flush=True)

    n = len(lignes) or 1
    ok = sum(1 for x in lignes if x.get("ok"))
    ok_ref = sum(1 for x in lignes if x.get("ok_par_voie"))
    mal = [x for x in lignes if x.get("bon_aiguillage") is False]
    couteux = [x for x in mal if x.get("ok_par_voie") and not x.get("ok")]

    L = ["# Golden client posé sur l'ASSISTANT — la performance du ROUTEUR\n",
         f"*{time.strftime('%Y-%m-%d')} · {n} questions · `/ask/incident-v2/auto` · barème "
         "identique au harnais par voie (seul l'endpoint change).*\n",
         f"\n**{ok}/{n} conformes via l'assistant**, contre **{ok_ref}/{n} quand chaque "
         "question est posée à la bonne voie.**\n",
         f"\n**{len(mal)} questions routées ailleurs que la voie attendue**, dont "
         f"**{len(couteux)} où l'aiguillage COÛTE la réponse** (la bonne voie répondait).\n"]
    if couteux:
        L += ["\n## Les aiguillages qui coûtent une réponse\n",
              "| id | attendu | choisi | question |", "|---|---|---|---|"]
        for x in couteux:
            L.append(f"| {x['id']} | {x['voie_attendue']} | {x['voie_choisie']} | "
                     f"{x['question'][:64]} |")
    L += ["\n## Détail\n", "| id | voie choisie | attendue | aiguillage | assistant | par voie |",
          "|---|---|---|---|---|---|"]
    for x in lignes:
        L.append(f"| {x['id']} | {x.get('voie_choisie','')} | {x.get('voie_attendue','')} | "
                 f"{'✔' if x.get('bon_aiguillage') else '✘'} | "
                 f"{'✅' if x.get('ok') else '❌'} {x.get('detail', x.get('erreur',''))} | "
                 f"{'✅' if x.get('ok_par_voie') else '❌'} |")
    open(OUT, "w", encoding="utf-8").write("\n".join(L) + "\n")
    json.dump(lignes, open(OUT.replace(".md", ".json"), "w"), ensure_ascii=False, indent=1)
    print(f"\n  assistant {ok}/{n}   ·   par voie {ok_ref}/{n}")
    print(f"  {len(mal)} mal aiguillées, dont {len(couteux)} qui perdent la réponse")
    print(f"écrit : {OUT}")


if __name__ == "__main__":
    main()
