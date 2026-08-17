#!/usr/bin/env python3
"""Évalue la voie RECOMMANDATION dans son sens réel : événement -> actions recommandées.

POURQUOI CE HARNAIS — mon golden précédent testait la voie à contresens. Ses questions
« action » décrivaient une ACTION (« cas où une procédure a été modifiée ») et cherchaient
les fiches correspondantes. Or la voie recommandation prend un ÉVÉNEMENT en entrée et rend
les actions prises dans les cas comparables — et elle EXCLUT volontairement les champs
d'action du matching (EXCLUDED_MATCH_FIELDS), pour apparier problème↔problème. Je lui
demandais donc de retrouver des fiches par le texte qu'elle est conçue à ignorer, d'où des
scores de 33 % qui ne mesuraient rien.

PROTOCOLE — leave-one-out, non circulaire :
  1. on prend une fiche F qui porte une action documentée ;
  2. on interroge avec la DESCRIPTION DE L'ÉVÉNEMENT de F (titre + détail), jamais son action ;
  3. on EXCLUT F des actions renvoyées (sinon la réponse contient la vérité attendue) ;
  4. on compare par THÈME, pas au mot près : 1 298 actions pour 916 titres distincts
     (défaut D6), donc l'égalité stricte de libellé ne mesurerait que la répétition littérale.

LA RÉFÉRENCE QUI REND LE SCORE LISIBLE — « rappel / sensibilisation » représente 28 % des
actions du corpus. Un système qui répondrait TOUJOURS « rappel » obtiendrait donc 28 % sans
rien comprendre. On calcule cette référence, et le score n'a de sens qu'au-dessus d'elle.
"""
import json
import re
import sys
import time
import unicodedata
import urllib.request
from collections import Counter

API = "http://172.16.6.10:8000"
POOL = ("/tmp/claude-1000/-home-yie0070-retex-split/"
        "5bf5faa3-f01f-46d3-96f0-99399c451a7a/scratchpad/reco_pool.txt")
OUT = "/home/yie0070/retex-split/retex-ingestion/resultats_recommandation.md"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 40

THEMES = [
    ("rappel / sensibilisation", r"rappel|sensibilis|repreciser|recadr"),
    ("formation / recyclage",    r"formation|recycl|habilit|e-learning"),
    ("procédure / consigne",     r"procedure|consigne|mode operatoire|instruction|protocole"),
    ("débriefing / entretien",   r"debrief|entretien|convocation"),
    ("réunion / groupe travail", r"reunion|groupe de travail|comite|commission"),
    ("courrier / diffusion",     r"courrier|\bnote\b|diffusion|mail|communication"),
    ("matériel / équipement",    r"materiel|equipement|remplacement|reparation|mise hors service"),
    ("balisage / marquage",      r"balisage|marquage|signalisation|peinture|panneau|cone"),
    ("contrôle / audit",         r"controle|audit|inspection|verification|surveillance"),
    ("sanction / RH",            r"sanction|avertissement|mise a pied|retrait de badge"),
    ("étude / analyse",          r"etude|analyse|expertise|diagnostic"),
    ("travaux / infrastructure", r"travaux|refection|amenagement|chantier"),
]


def nz(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def themes_de(texte):
    n = nz(texte)
    return {t for t, rx in THEMES if re.search(rx, n)}


def recommande(description, timeout=300):
    b = json.dumps({"question": description, "top_k": 10}).encode()
    r = urllib.request.Request(f"{API}/ask/incident-v2/recommande", data=b,
                               headers={"Content-Type": "application/json"}, method="POST")
    t = time.time()
    return json.load(urllib.request.urlopen(r, timeout=timeout)), time.time() - t


def charger_pool():
    """[(fe, titre, detail, action)] — une fiche n'apparaît qu'une fois."""
    vus, out = set(), []
    for l in open(POOL, encoding="utf-8"):
        l = l.strip().strip('"')
        if "|||" not in l:
            continue
        p = l.split("|||")
        if len(p) != 4:
            continue
        fe = p[0].strip()
        if fe in vus or not themes_de(p[3]):
            continue          # sans thème identifiable, la fiche ne peut pas servir de vérité
        vus.add(fe)
        out.append((fe, p[1].strip(), p[2].strip(), p[3].strip()))
    return out


def main():
    pool = charger_pool()[:N]
    print(f"{len(pool)} fiches testées (leave-one-out)\n", flush=True)

    freq = Counter()
    for _, _, _, act in charger_pool():
        freq.update(themes_de(act))
    theme_majoritaire = freq.most_common(1)[0][0]

    lignes, reussites, sans_reco = [], 0, 0
    reussites_struct = 0
    ref_maj = 0
    for i, (fe, titre, detail, action) in enumerate(pool, 1):
        attendus = themes_de(action)
        ref_maj += 1 if theme_majoritaire in attendus else 0
        try:
            d, dt = recommande(f"{titre}. {detail}")
        except Exception as e:
            print(f"  [{i}/{len(pool)}] {fe} ERREUR {type(e).__name__}", flush=True)
            continue
        # on retire les actions issues de la fiche elle-même : sans cela on lirait la réponse
        # dans l'énoncé.
        proposees = [a for a in (d.get("actions") or [])
                     if fe not in (a.get("fe_sources") or [])]
        obtenus, obtenus_struct = set(), set()
        for a in proposees:
            th = themes_de(a.get("titre"))
            obtenus |= th
            # « à chaud » = le récit de ce qui a été fait sur le moment (« Bag ramassé »).
            # Ce n'est pas une recommandation applicable : on mesure aussi SANS, pour savoir
            # si le score repose sur les actions structurées ou sur ce bruit.
            if a.get("type_action") != "à chaud":
                obtenus_struct |= th
        if not proposees:
            sans_reco += 1
        ok = bool(attendus & obtenus)
        ok_struct = bool(attendus & obtenus_struct)
        reussites += 1 if ok else 0
        reussites_struct += 1 if ok_struct else 0
        lignes.append({"fe": fe, "titre": titre[:70], "action": action[:70],
                       "attendus": sorted(attendus), "obtenus": sorted(obtenus),
                       "n_actions": len(proposees), "ok": ok,
                       "ok_struct": ok_struct, "s": round(dt, 1)})
        print(f"  [{i}/{len(pool)}] {fe:16} {'OK ' if ok else '.  '} "
              f"{len(proposees)} actions · attendu {sorted(attendus)}", flush=True)

    n = len(lignes)
    L = ["# Voie Recommandation — l'action proposée correspond-elle à celle qui a été prise ?\n",
         f"*Protocole leave-one-out sur {n} fiches : on interroge avec la description de "
         "l'événement, jamais avec son action, et on retire la fiche elle-même des résultats. "
         "Comparaison par THÈME (916 titres distincts pour 1 298 actions — l'égalité littérale "
         "ne mesurerait que la répétition).*\n",
         "\n| | valeur |", "|---|---:|",
         f"| fiches testées | {n} |",
         f"| **thème de l'action réelle retrouvé** | **{reussites}/{n} = {reussites/n:.0%}** |",
         f"| référence « toujours {theme_majoritaire} » | {ref_maj}/{n} = {ref_maj/n:.0%} |",
         f"| **gain sur la référence** | **{(reussites-ref_maj)/n:+.0%} points** |",
         f"| **thème retrouvé SANS les actions à chaud** | **{reussites_struct}/{n} = "
         f"{reussites_struct/n:.0%}** |",
         f"| aucune action recommandée | {sans_reco}/{n} |",
         "\n*La référence est indispensable : « rappel / sensibilisation » pèse 28 % du corpus, "
         "donc un système qui répondrait toujours cela obtiendrait ce score sans rien comprendre. "
         "Seul l'écart au-dessus de la référence mesure une capacité réelle.*\n",
         "\n## Détail\n",
         "| fiche | événement | action réelle | thème attendu | thèmes proposés | |",
         "|---|---|---|---|---|:-:|"]
    for r in lignes:
        L.append(f"| {r['fe']} | {r['titre']} | {r['action']} | {', '.join(r['attendus'])} "
                 f"| {', '.join(r['obtenus']) or '—'} | {'✅' if r['ok'] else '❌'} |")
    open(OUT, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"\nsans les à chaud : {reussites_struct}/{n} = {reussites_struct/n:.0%}")
    print(f"thème retrouvé : {reussites}/{n} = {reussites/n:.0%}"
          f"   ·   référence « toujours {theme_majoritaire} » : {ref_maj/n:.0%}")
    print(f"écrit : {OUT}")


if __name__ == "__main__":
    main()
