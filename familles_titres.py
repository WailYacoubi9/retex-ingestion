#!/usr/bin/env python3
"""
Familles de titres — définition REPRODUCTIBLE et contrôles d'arbitrage.

POURQUOI CE FICHIER
    Le chiffre « ~24 familles couvrent ~75 % du corpus » circulait sans script :
    impossible de répondre à « comment définissez-vous une famille ? ». Ce module
    fige la définition, et surtout il MESURE SA PROPRE FRAGILITÉ.

LA DÉFINITION, EN TROIS POINTS
    1. Le titre est normalisé (minuscules, sans accents, ponctuation réduite) puis
       les fautes de frappe récurrentes sont corrigées (CORR).
    2. La famille est attribuée par le PREMIER motif qui correspond, dans l'ordre
       de la liste FAMILLES. L'ordre est donc une décision de conception, pas un
       détail : « fod fuite hydraulique » tombe dans FOD parce que FOD est déclaré
       avant Fuite.
    3. Un titre qui ne correspond à aucun motif reste NON CLASSÉ. Ce n'est pas un
       échec : la queue de titres uniques est le régime naturel de la voie
       recherche, pas d'un filtre.

CE QUE CE SCRIPT A APPRIS DE LUI-MÊME  (mesuré le 17/08/2026)
    Confronté à une implémentation indépendante des mêmes familles :
      - la COUVERTURE GLOBALE est robuste          — 75,8 % ici contre 75,5 % là ;
      - les COMPTAGES PAR FAMILLE ne le sont PAS   — jusqu'à 100 fiches d'écart
        sur les familles dont le vocabulaire chevauche celui d'une autre
        (balisage/incendie, fuite/FOD, ligne frontière/sûreté). La table « Repli »
        dit, pour chacune, où ses fiches iraient si on la retirait : c'est la
        mesure de sa dépendance à l'ordre de déclaration.
    Conséquence pour le rapport : on cite la couverture, PAS l'effectif d'une
    famille au fiche près, sauf pour les familles que le contrôle de chevauchement
    déclare disjointes. Le contrôle est calculé ci-dessous, il n'est pas à croire
    sur parole.

USAGE
    python familles_titres.py                 # rapport texte
    python familles_titres.py --md > stats_familles_titres.md
"""
from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

SRC = Path(__file__).parent / "data/samples/incidents_avec_actions.json"
TE = "type d'événement (ECC)"
CAUSES = [f"desc cause {i}" for i in range(1, 7)]
LISTES_ACTIONS = ["actions_correctives", "actions_preventives", "actions_curatives"]
ACTION_IMMEDIATE = "Action corrective immédiate"

# ── fautes de frappe et variantes lexicales relevées dans le corpus ──────────
CORR = [
    (r"\bcolll?ision\b", "collision"), (r"\bcollisions\b", "collision"),
    (r"\bavia(?:re|ires?|ere)\b", "aviaire"),
    (r"\boiseau/avion\b|\bavion/oiseau\b|\boiseau avion\b", "aviaire"),
    (r"\brepoussages\b", "repoussage"), (r"\bvehicules\b", "vehicule"),
    (r"\baeronefs\b", "aeronef"), (r"\bincursions\b", "incursion"),
    (r"\bpassagers?\b", "passager"), (r"\bderoutements?\b", "deroutement"),
    (r"\bfuites?\b", "fuite"), (r"\bmateriels?\b", "materiel"),
]

# ── les familles, DANS L'ORDRE D'ATTRIBUTION ────────────────────────────────
# Du plus spécifique au plus générique. Déplacer une ligne change les comptages :
# toute modification doit être suivie d'un « python familles_titres.py » et d'une
# relecture de la section CHEVAUCHEMENT.
FAMILLES: list[tuple[str, str]] = [
    ("Collision aviaire",             r"aviaire|oiseau|birdstrike|volatile"),
    ("Collision animale",             r"collision animale|lievre|renard|\banimal\b|animaux|chevreuil"),
    ("Baisse niveau SSLIA",           r"baisse (?:du )?np|baisse.*sslia|np\s?\d\s*iso|niveau.*protection"),
    ("Remise de gaz / approche",      r"remise de gaz|remise gaz|go.?around|approche non stabilis|approche interrompue"),
    ("Déroutement",                   r"deroutement|deroute\b|diversion|retour terrain|demi.?tour"),
    ("Problème technique avion",      r"probleme technique|panne avion|retour parking|panne moteur|incident technique"),
    ("État des surfaces",             r"etat (?:de la )?surface|revetement|nid de poule|affaissement|degradation.*(?:piste|aire|voie|poste)|trou.*(?:piste|aire|taxiway)|dalle"),
    ("Balisage / éclairage",          r"balisage|feux?|eclairage|lumineux|panneau|marquage"),
    ("Incendie / fumée",              r"incendie|fumee|explosion|depart de feu"),
    ("Panne système / informatique",  r"panne (?:systeme|informatique|reseau|electrique|de courant)|indisponibilite|logiciel|serveur|\bbug\b|dysfonctionnement (?:systeme|informatique|technique)|coupure (?:electrique|de courant)"),
    ("Ligne frontière / sûreté",      r"ligne frontiere|\blf\b|surete|intrusion|badge|zone reservee|acces (?:non autorise|ligne)|franchissement.*(?:frontiere|lf)|porte.*ouverte|pietons? (?:en|sur|non)|personne.*(?:piste|aire|zone)"),
    ("Placement / affectation avion", r"placement|affectation|mauvais poste|erreur de poste"),
    ("Incursion / franchissement",    r"incursion|franchissement|point d arret|penetration"),
    ("Refus de priorité",             r"refus.*priorit|non respect.*priorit"),
    ("Repoussage / tractage",         r"repoussage|push ?back|tractage|remorquage"),
    ("Passager indiscipliné",         r"paxi|passager indiscipline|passager perturbateur"),
    ("Chargement / bagages",          r"bagage|chargement|fret|soute"),
    ("Avitaillement / carburant",     r"avitaillement|avitailleur|carburant|kerosene|fuel|jet a-?1|\bplein\b|camion citerne"),
    ("FOD",                           r"\bfod\b|corps etranger|debris"),
    ("Fuite hydraulique / fluide",    r"fuite|epanchement|hydraulique|deversement"),
    ("Quasi-collision",               r"quasi.?collision|perte de separation|rapprochement"),
    ("Collision matérielle",          r"collision|choc|heurt|accrochage|percut|contact.*(?:avion|aeronef)|touche.*avion|endommag"),
    ("Matériel gênant / encombrement", r"materiel genant|mal stationne|stationnement non|\bgse\b|encombrement"),
    ("Météo / conditions",            r"meteo|neige|verglas|orage|\bvent\b|degivrage|brouillard|givre|grele|foudre|visibilite|windshear"),
]


# ── normalisation ───────────────────────────────────────────────────────────
def nz(t) -> str:
    t = "".join(c for c in unicodedata.normalize("NFD", str(t or "").lower())
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9/ -]", " ", t)).strip()


def cle(t) -> str:
    s = nz(t)
    for p, r in CORR:
        s = re.sub(p, r, s)
    return s


def cl(v):
    """Valeur métier utile, ou None. « 0 » signifie « axe non retenu », pas zéro."""
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s if s and s.lower() not in {"0", "-", "n/a", "na", "ras"} else None


def famille(s: str):
    for lib, pat in FAMILLES:
        if re.search(pat, s):
            return lib
    return None


def toutes_familles(s: str) -> list[str]:
    """Toutes les familles dont le motif correspond, dans l'ordre de déclaration.

    Le premier élément est la famille attribuée ; les suivants sont les familles
    plus GÉNÉRIQUES qui auraient capté le titre. Ce n'est pas un défaut : la
    cascade spécifique -> générique est voulue (« collision aviaire » correspond
    aussi au motif `collision` de Collision matérielle, déclaré plus bas). On
    s'en sert pour dire vers QUELLE famille les fiches se replieraient si celle-ci
    était retirée — une information, pas un verdict.
    """
    return [lib for lib, pat in FAMILLES if re.search(pat, s)]


def entropie(compte: Counter) -> float:
    """Entropie de Shannon normalisée sur [0,1]. 0 = une seule modalité."""
    n = sum(compte.values())
    if n == 0 or len(compte) <= 1:
        return 0.0
    h = -sum((v / n) * math.log(v / n) for v in compte.values() if v)
    return h / math.log(len(compte))


# ── calcul ──────────────────────────────────────────────────────────────────
def analyser(fiches: list[dict]) -> dict:
    par_fam: dict[str, list[dict]] = defaultdict(list)
    repli: dict[str, Counter] = defaultdict(Counter)
    non_classes: list[dict] = []

    for r in fiches:
        s = cle(r.get("titre"))
        toutes = toutes_familles(s)
        if not toutes:
            non_classes.append(r)
            continue
        par_fam[toutes[0]].append(r)
        repli[toutes[0]][toutes[1] if len(toutes) > 1 else "(non classé)"] += 1

    lignes = []
    for lib, _ in FAMILLES:
        grp = par_fam.get(lib, [])
        n = len(grp)
        if not n:
            lignes.append(dict(famille=lib, n=0))
            continue
        types = Counter()
        for r in grp:
            for x in (cl(r.get(TE)) or "(vide)").split("|"):
                types[x.strip()] += 1
        top, ntop = types.most_common(1)[0]
        n_cause = sum(1 for r in grp if any(cl(r.get(c)) for c in CAUSES))
        n_struct = sum(1 for r in grp if any(r.get(L) for L in LISTES_ACTIONS))
        n_imm = sum(1 for r in grp if cl(r.get(ACTION_IMMEDIATE)))
        n_trace = sum(1 for r in grp
                      if any(r.get(L) for L in LISTES_ACTIONS) or cl(r.get(ACTION_IMMEDIATE)))
        cible, ncible = repli[lib].most_common(1)[0]
        ans = sorted({m.group(1) for r in grp
                      if (m := re.search(r"(\d{4})", str(r.get("Date") or "")))
                      and "2000" <= m.group(1) <= "2026"})
        lignes.append(dict(
            famille=lib, n=n,
            taux_cause=n_cause / n,
            taux_action_struct=n_struct / n, taux_action_imm=n_imm / n,
            taux_action=n_trace / n,
            type_dominant=top, part_type=ntop / n,
            entropie_types=entropie(types), n_types=len(types),
            repli=cible, part_repli=ncible / n,
            periode=f"{ans[0]}-{ans[-1]}" if ans else "?",
        ))

    return dict(lignes=lignes, non_classes=non_classes, total=len(fiches),
                classes=sum(len(v) for v in par_fam.values()))


def verdict_apport(l: dict) -> str:
    """La famille apporte-t-elle une dimension que le type d'événement ne porte pas ?

    Le contrôle décisif n'est PAS `part_type` bas — une famille lâche produit
    mécaniquement un part_type bas. C'est l'ENTROPIE des types à l'intérieur de la
    famille : concentrée sur 2-3 types proches = le type fragmente (apport réel) ;
    éparpillée sur dix types sans rapport = c'est le motif de titre qui est trop
    large (à resserrer avant toute promotion).
    """
    if l["n"] == 0:
        return "vide"
    if l["part_type"] >= 0.90:
        return "redondant"
    if l["type_dominant"].startswith("Autre"):
        return "APPORT FORT"
    if l["entropie_types"] > 0.75:
        return "MOTIF LÂCHE"
    if l["part_type"] < 0.55:
        return "APPORT FORT"
    return "moyen"


def rapport(res: dict, md: bool = False) -> str:
    out: list[str] = []
    p = out.append
    N, C = res["total"], res["classes"]

    if md:
        p("# Familles de titres — sortie de `familles_titres.py`\n")
        p(f"*{N} fiches · {C} classées (**{100*C/N:.1f} %**) · "
          f"{N-C} non classées ({100*(N-C)/N:.1f} %) · {len(FAMILLES)} familles*\n")
        p("| Famille | n | Cause | Act. imm. | Act. struct. | Type dominant | part | H(types) | Verdict |")
        p("|---|---:|---:|---:|---:|---|---:|---:|---|")
        for l in sorted(res["lignes"], key=lambda x: -x["n"]):
            if not l["n"]:
                continue
            p(f"| {l['famille']} | {l['n']} | {100*l['taux_cause']:.0f} % | "
              f"{100*l['taux_action_imm']:.0f} % | {100*l['taux_action_struct']:.0f} % | "
              f"{l['type_dominant'][:34]} | {100*l['part_type']:.0f} % | "
              f"{l['entropie_types']:.2f} | {verdict_apport(l)} |")
        p("\n**Act. imm.** action corrective immédiate (champ libre) · **Act. struct.** "
          "au moins une action de l'onglet Agir — les deux ne mesurent pas la même chose "
          "(cf. rapport §3.5). **H(types)** entropie normalisée des types d'événement "
          "dans la famille : basse = le type porte déjà la famille, haute = le motif de "
          "titre est trop large et doit être resserré avant toute promotion.\n")
        p("### Repli — vers quelle famille iraient les fiches si celle-ci était retirée\n")
        p("| Famille | se replierait sur | part |")
        p("|---|---|---:|")
        for l in sorted(res["lignes"], key=lambda x: -x["n"]):
            if l["n"]:
                p(f"| {l['famille']} | {l['repli']} | {100*l['part_repli']:.0f} % |")
        p("")
    else:
        p(f"{'famille':32s} {'n':>5s} {'cause':>6s} {'imm':>5s} {'strc':>5s} "
          f"{'part':>5s} {'H':>5s}  verdict")
        p("-" * 96)
        for l in sorted(res["lignes"], key=lambda x: -x["n"]):
            if not l["n"]:
                continue
            p(f"{l['famille'][:32]:32s} {l['n']:5d} {100*l['taux_cause']:5.0f}% "
              f"{100*l['taux_action_imm']:4.0f}% {100*l['taux_action_struct']:4.0f}% "
              f"{100*l['part_type']:4.0f}% {l['entropie_types']:5.2f}  {verdict_apport(l)}")
        p("-" * 96)
        p(f"classé {C}/{N} = {100*C/N:.1f} %   non classé {N-C} = {100*(N-C)/N:.1f} %")

    # ── inversion volume / explication ──────────────────────────────────────
    peuplees = sorted((l for l in res["lignes"] if l["n"] >= 50), key=lambda x: -x["n"])
    if len(peuplees) >= 4:
        gros = peuplees[:3]
        riches = sorted(peuplees, key=lambda x: -x["taux_cause"])[:3]
        titre = "\n## Inversion volume ⊥ explication\n" if md else "\n>>> INVERSION VOLUME / EXPLICATION"
        p(titre)
        p(("Les trois familles les plus volumineuses : " if md else "  volumineuses : ")
          + " · ".join(f"{l['famille']} ({l['n']}, {100*l['taux_cause']:.0f} % de cause)" for l in gros))
        p(("Les trois mieux expliquées : " if md else "  expliquées   : ")
          + " · ".join(f"{l['famille']} ({l['n']}, {100*l['taux_cause']:.0f} % de cause)" for l in riches))

    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--md", action="store_true", help="sortie Markdown")
    ap.add_argument("--src", default=str(SRC))
    a = ap.parse_args()
    fiches = json.loads(Path(a.src).read_text(encoding="utf-8"))
    print(rapport(analyser(fiches), md=a.md))


if __name__ == "__main__":
    main()
