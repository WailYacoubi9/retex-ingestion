#!/usr/bin/env python3
"""
Enrichit le golden pour l'évaluation DE BOUT EN BOUT.

Le golden actuel ne juge que la récupération (quelles fiches remontent).
Il ne dit rien de la réponse rédigée. On ajoute donc, pour chaque question,
ce qu'une bonne réponse doit contenir — et ce qu'elle ne doit surtout pas.

Trois blocs ajoutés par question :

  attendu_generation
      faits_obligatoires   éléments que la réponse DOIT contenir (∈ sources)
      faits_interdits      erreurs typiques (chiffres faux, entités absentes)
      plafond_a_annoncer   limite de couverture que la réponse doit signaler
      type_reponse         narratif | liste | comptage | abstention

  ancrage
      fne_citables         fiches dont la réponse peut se réclamer
      champs_source        où vit l'information (contrôle de la citation)

  criteres_juge
      grille binaire pour le juge LLM, une ligne = une vérification

    python enrichir_golden_e2e.py --in golden_recherche_cause_action.jsonl \
                                  --out golden_e2e.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

SRC = "/mnt/user-data/uploads/incidents_avec_actions.json"
D = json.load(open(SRC, encoding="utf-8"))


def cl(v):
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s if s and s.lower() not in {"0", "-", "n/a", "na", "ras", "nil"} else None


def nz(t):
    t = "".join(c for c in unicodedata.normalize("NFD", str(t or "").lower())
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t).strip()


PAR_FE = {cl(r.get("Num F.E.")): r for r in D if cl(r.get("Num F.E."))}


def annee(r):
    m = re.search(r"(\d{4})", cl(r.get("date de l'évènement (ECC)")) or "")
    return m.group(1) if m and m.group(1) != "0000" else None


def cause_txt(r):
    return " ".join(filter(None, [cl(r.get(f"desc cause {i}")) for i in range(1, 7)]))


def action_txt(r):
    a = [cl(r.get("Action corrective immédiate"))]
    a += [cl(x.get("titre de l'action")) for k in
          ("actions_correctives", "actions_preventives", "actions_curatives")
          for x in (r.get(k) or [])]
    return " ".join(filter(None, a))


# --------------------------------------------------------------- faits attendus

def faits_obligatoires(fnes, voie):
    """Éléments vérifiables qu'une bonne réponse doit mentionner.

    On ne demande pas des mots exacts mais des FAITS : un lieu, une année,
    un type, une cause. Le juge vérifie la présence du fait, pas de la formule.
    """
    fiches = [PAR_FE[f] for f in fnes if f in PAR_FE]
    if not fiches:
        return []
    faits = []

    # le type dominant, s'il l'est vraiment
    ty = Counter()
    for r in fiches:
        for x in (cl(r.get("type d'événement (ECC)")) or "").split("|"):
            if x.strip():
                ty[x.strip()] += 1
    if ty:
        top, n = ty.most_common(1)[0]
        if n / len(fiches) >= 0.6:
            faits.append({"type": "type_evenement", "valeur": top,
                          "couverture": round(n / len(fiches), 2)})

    # les lieux récurrents
    lieux = Counter(cl(r.get("précisions sur le lieu (ECC)")) for r in fiches
                    if cl(r.get("précisions sur le lieu (ECC)")))
    for v, n in lieux.most_common(2):
        if n >= 3 and n / len(fiches) >= 0.25:
            faits.append({"type": "lieu", "valeur": v, "couverture": round(n / len(fiches), 2)})

    # la période couverte
    ans = sorted(a for r in fiches if (a := annee(r)))
    if ans:
        faits.append({"type": "periode", "valeur": f"{ans[0]}-{ans[-1]}",
                      "couverture": round(len(ans) / len(fiches), 2)})

    # pour les questions cause/action : au moins une formulation réelle
    if voie in ("cause", "action"):
        extract = cause_txt if voie == "cause" else action_txt
        exemples = [t[:120] for r in fiches if (t := extract(r)) and len(t) > 25][:3]
        if exemples:
            faits.append({"type": f"exemple_{voie}", "valeur": exemples,
                          "couverture": None,
                          "note": "au moins UN de ces contenus doit se retrouver "
                                  "dans la réponse, reformulé ou cité"})
    return faits


def faits_interdits(fnes, voie, question):
    """Erreurs typiques à détecter. Chacune est une régression connue."""
    fiches = [PAR_FE[f] for f in fnes if f in PAR_FE]
    inter = [
        {"type": "chiffre_invente",
         "regle": f"ne pas annoncer un total de fiches ; la recherche remonte un "
                  f"échantillon, pas la population complète ({len(fnes)} fiches "
                  f"pertinentes existent, mais le système n'en voit que k)"},
        {"type": "fne_hors_contexte",
         "regle": "ne citer aucun numéro de fiche absent du contexte fourni"},
    ]
    # années hors périmètre
    ans = {a for r in fiches if (a := annee(r))}
    m = re.search(r"\b(20\d{2})\b", question)
    if m and m.group(1) in ans:
        inter.append({"type": "annee_hors_contrainte",
                      "regle": f"toutes les fiches citées doivent être de {m.group(1)}"})
    if voie == "cause":
        inter.append({"type": "cause_inventee",
                      "regle": "ne pas attribuer de cause à une fiche dont "
                               "desc_cause est vide — dire que l'analyse est absente"})
    if voie == "action":
        inter.append({"type": "action_inventee",
                      "regle": "ne pas recommander d'action non tracée dans les "
                               "fiches ; distinguer ce qui a été fait de ce qui "
                               "pourrait l'être"})
    return inter


def plafond(fnes, voie):
    """Limite de couverture que la réponse doit annoncer honnêtement."""
    fiches = [PAR_FE[f] for f in fnes if f in PAR_FE]
    if not fiches:
        return None
    n = len(fiches)
    if voie == "cause":
        avec = sum(1 for r in fiches if cause_txt(r))
        return {"mesure": "fiches avec cause rédigée", "n": avec, "sur": n,
                "annonce_attendue": avec < n}
    if voie == "action":
        struct = sum(1 for r in fiches if any(
            r.get(k) for k in ("actions_correctives", "actions_preventives",
                               "actions_curatives")))
        return {"mesure": "fiches avec action structurée", "n": struct, "sur": n,
                "annonce_attendue": struct < n * 0.5}
    desc = sum(1 for r in fiches
               if len(cl(r.get("Description de l'événement et de son contexte")) or "") >= 100)
    return {"mesure": "fiches avec description exploitable", "n": desc, "sur": n,
            "annonce_attendue": desc < n * 0.7}


GRILLE = {
    "recherche": [
        ("ancrage", "chaque affirmation factuelle est soutenue par une fiche du contexte"),
        ("pertinence", "la réponse porte bien sur le sujet demandé, pas sur un sujet voisin"),
        ("citation", "les fiches citées existent dans le contexte fourni"),
        ("faits", "au moins un fait obligatoire est présent"),
        ("pas_invention", "aucun chiffre global ni entité absente du contexte"),
        ("honnetete", "le plafond de couverture est annoncé s'il le faut"),
    ],
    "cause": [
        ("ancrage", "les causes énoncées proviennent des champs desc_cause du contexte"),
        ("pas_confusion", "la cause n'est pas confondue avec l'action ni avec la description"),
        ("citation", "les fiches citées existent dans le contexte"),
        ("faits", "au moins une cause réelle du corpus est reprise ou reformulée"),
        ("pas_invention", "aucune cause attribuée à une fiche qui n'en porte pas"),
        ("honnetete", "la part de fiches sans analyse causale est signalée"),
    ],
    "action": [
        ("ancrage", "les actions énoncées proviennent du contexte"),
        ("distinction", "ce qui a été FAIT est distingué de ce qui POURRAIT être fait"),
        ("citation", "les fiches citées existent dans le contexte"),
        ("faits", "au moins une action réelle du corpus est reprise"),
        ("pas_invention", "aucune action recommandée présentée comme déjà réalisée"),
        ("honnetete", "le faible taux d'actions structurées est signalé si pertinent"),
    ],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("golden_e2e.jsonl"))
    a = ap.parse_args()

    lignes = [json.loads(l) for l in a.src.read_text(encoding="utf-8").splitlines() if l.strip()]
    out = []
    for o in lignes:
        voie = o.get("voie", "recherche")
        fnes = o.get("fne_attendus", [])
        champ = {"recherche": ["titre", "detail", "analyse_chaud"],
                 "cause": ["desc_cause_1..6"],
                 "action": ["action_corrective", "actions structurées"]}[voie]
        o["attendu_generation"] = {
            "type_reponse": "narratif_avec_exemples",
            "faits_obligatoires": faits_obligatoires(fnes, voie),
            "faits_interdits": faits_interdits(fnes, voie, o["question"]),
            "plafond_a_annoncer": plafond(fnes, voie),
        }
        o["ancrage"] = {"fne_citables": fnes, "champs_source": champ}
        o["criteres_juge"] = [{"critere": c, "verification": v} for c, v in GRILLE[voie]]
        out.append(o)

    # questions d'abstention : la bonne réponse est un refus motivé
    ABST = [
        ("Quelles actions ont été jugées inefficaces ?", "action",
         "le champ ne contient que « oui » sur 709 fiches ; aucune inefficacité n'est tracée"),
        ("Quelles ont été les causes des incidents de 2010 ?", "cause",
         "aucune cause n'est rédigée avant 2013"),
        ("Combien d'incidents n'ont fait aucun blessé ?", "recherche",
         "le champ blessés n'a aucune modalité « non » ; l'absence n'est pas une négation"),
        ("Quel est le coût des incidents de FOD ?", "recherche",
         "le champ coût est renseigné sur 12 actions"),
    ]
    for i, (q, voie, motif) in enumerate(ABST):
        out.append({
            "id": f"ABST_{i:02d}", "question": q, "voie": voie,
            "n_pertinents": 0, "fne_attendus": [],
            "attendu_generation": {
                "type_reponse": "abstention",
                "faits_obligatoires": [{"type": "motif", "valeur": motif}],
                "faits_interdits": [
                    {"type": "chiffre", "regle": "la réponse ne doit contenir AUCUN nombre "
                                                 "présenté comme un décompte"},
                    {"type": "reponse_fabriquee", "regle": "ne pas répondre à la place de la donnée"},
                ],
                "plafond_a_annoncer": None,
            },
            "ancrage": {"fne_citables": [], "champs_source": []},
            "criteres_juge": [
                {"critere": "abstention", "verification": "la réponse refuse explicitement"},
                {"critere": "motif", "verification": "le motif du refus est exact et expliqué"},
                {"critere": "pas_de_chiffre", "verification": "aucun décompte n'est avancé"},
                {"critere": "alternative", "verification": "une reformulation utile est proposée"},
            ],
        })

    with a.out.open("w", encoding="utf-8") as f:
        for o in out:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")

    nf = sum(len(o["attendu_generation"]["faits_obligatoires"]) for o in out)
    print(f"{len(out)} questions -> {a.out}")
    print(f"  dont abstentions attendues : {sum(1 for o in out if o['attendu_generation']['type_reponse']=='abstention')}")
    print(f"  faits obligatoires générés : {nf} ({nf/len(out):.1f} par question)")
    print(f"  critères de jugement       : {sum(len(o['criteres_juge']) for o in out)}")
    ex = out[0]
    print("\n--- exemple ---")
    print(json.dumps({k: ex[k] for k in ("id", "question", "attendu_generation")},
                     ensure_ascii=False, indent=1)[:900])


if __name__ == "__main__":
    main()
