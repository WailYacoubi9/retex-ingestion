#!/usr/bin/env python3
"""Extraction des sigles du corpus FNE et comptage de leurs fréquences.

Sortie JSON destinée à la validation métier (Hugo) et à l'alimentation du
glossaire du prompt de résumé (config/prompts/resume_incident.txt).

Principe : on n'analyse que le texte libre réellement vu par le LLM de résumé,
et on n'efface rien — un token écarté part dans `exclus` avec son motif, jamais
à la poubelle silencieusement.
"""

import argparse
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime

# Champs de texte libre, alignés sur ceux que consomme resume_incident.txt.
CHAMPS_TEXTE = [
    "titre",
    "Description de l'événement et de son contexte",
    "Analyse à chaud",
    "Analyse détaillée (ev. significatif)",
    "Action corrective immédiate",
    "détail de la vérification",
    "REX",
    "REX similaires",
] + [f"desc cause {i}" for i in range(1, 8)]

# Actions imbriquées : seules les clés porteuses de texte rédigé.
CHAMPS_ACTIONS = ["titre de l'action", "détail", "Comment sera vérifiée l'efficacité ?"]

LISTES_ACTIONS = ["actions_correctives", "actions_preventives"]

CHAMP_ID = "Num F.E."

# Sigles de 2 à 8 caractères : SSLIA tient en 5, ASMGCS en 6, ECCAIRS en 7.
RE_SIGLE = re.compile(r"\b[A-Z][A-Z0-9]{1,7}\b")

# Formes ponctuées (F.O.D, Q.R.P) normalisées vers la forme compacte.
RE_POINTEE = re.compile(r"\b(?:[A-Z]\.){2,}[A-Z]?\b")

# Termes du jargon écrits en minuscules : invisibles pour RE_SIGLE, mais bien
# présents au glossaire. Liste explicite — pas de détection automatique, qui
# confondrait « est » (verbe) et « EST » (point cardinal).
TERMES_MINUSCULES = {
    "iso": "s'écrit en minuscules dans les fiches (« NP7 iso NP9 »)",
    "pax": "variante minuscule de PAX",
}

# Vrais sigles homographes d'un mot français : ils priment sur MOTS_FRANCAIS.
# Écarter ILS ferait perdre l'ILS (203 occurrences) au motif du pronom.
SIGLES_PROTEGES = {
    "ILS": "Instrument Landing System — homographe du pronom « ils », "
    "le comptage mélange les deux : à trancher sur les extraits",
}

# Mots français courants qui deviennent des faux sigles dans les fiches
# rédigées en CapsLock. Écartés par défaut, mais tracés dans `exclus` avec
# leur fréquence : c'est une proposition, pas une suppression.
MOTS_FRANCAIS = {
    "LE", "LA", "LES", "DE", "DES", "DU", "UN", "UNE", "ET", "OU", "AU", "AUX",
    "SUR", "POUR", "DANS", "AVEC", "SANS", "SOUS", "IL", "ELLE", "ILS", "ONT",
    "EST", "SONT", "PAS", "QUE", "QUI", "CE", "CET", "CETTE", "CES", "SE", "NE",
    "SON", "SA", "SES", "LEUR", "PAR", "MAIS", "DONC", "OR", "NI", "CAR", "PUIS",
    "TOUT", "TOUS", "TOUTE", "PLUS", "MOINS", "TRES", "APRES", "AVANT", "ETE",
    "ETAIT", "AVAIT", "FAIT", "SUITE", "LORS", "NON", "OUI", "ETC", "AFIN",
    "DEUX", "TROIS", "BIEN", "ALORS", "SOIT", "DONT", "NOUS", "VOUS", "JE",
    "VOIR", "ENFIN", "AINSI", "AUSSI", "ENTRE", "VERS", "CHEZ", "DEPUIS",
    "PENDANT", "SELON", "MEME", "AUCUN", "LUI", "SUR", "ETAT", "ZONE", "VOL",
    "AIRE", "PORTE", "RIEN", "TYPE", "AVION", "PISTE", "AGENT", "POSTE",
    "HEURE", "JOUR", "NUIT", "BORD", "SOL", "EN", "A", "Y",
}


def _sans_accents(txt: str) -> str:
    """ÉTAT -> ETAT, pour comparer aux mots de MOTS_FRANCAIS."""
    return "".join(
        c for c in unicodedata.normalize("NFD", txt) if unicodedata.category(c) != "Mn"
    )


def _extrait(texte: str, terme: str, marge: int = 70) -> str | None:
    """Petite fenêtre de contexte autour de la première occurrence."""
    pos = texte.find(terme)
    if pos < 0:
        return None
    debut = max(0, pos - marge)
    fin = min(len(texte), pos + len(terme) + marge)
    bout = " ".join(texte[debut:fin].split())
    return ("…" if debut else "") + bout + ("…" if fin < len(texte) else "")


def _champs_texte(fiche: dict):
    """Rend les couples (nom_du_champ, texte) à analyser pour une fiche."""
    for champ in CHAMPS_TEXTE:
        valeur = fiche.get(champ)
        if isinstance(valeur, str) and valeur.strip():
            yield champ, valeur
    for liste in LISTES_ACTIONS:
        for action in fiche.get(liste) or []:
            for champ in CHAMPS_ACTIONS:
                valeur = action.get(champ)
                if isinstance(valeur, str) and valeur.strip():
                    yield f"{liste}.{champ}", valeur


def _candidats(texte: str):
    """Rend les couples (forme_normalisee, forme_observee) d'un texte."""
    for brut in RE_POINTEE.findall(texte):
        yield brut.replace(".", ""), brut
    # Les formes ponctuées ne gênent pas RE_SIGLE : « F.O.D » n'y produit
    # aucun mot de 2+ caractères, les lettres étant isolées par les points.
    for brut in RE_SIGLE.findall(texte):
        yield brut, brut
    for terme in TERMES_MINUSCULES:
        for brut in re.findall(rf"\b{terme}\b", texte, flags=re.IGNORECASE):
            yield terme.upper(), brut


def _motif_exclusion(sigle: str) -> str | None:
    if sigle in SIGLES_PROTEGES:
        return None
    if _sans_accents(sigle) in MOTS_FRANCAIS:
        return (
            "homographe d'un mot français courant (fiches en majuscules) — "
            "écarté par défaut, à rouvrir si le métier lui connaît un sens"
        )
    if len(sigle) < 2:
        return "trop court"
    return None


def extraire(chemin_source: str, chemin_sortie: str, nb_extraits: int = 3) -> dict:
    print(f"Lecture de {chemin_source}…")
    with open(chemin_source, encoding="utf-8") as f:
        fiches = json.load(f)

    frequences = Counter()
    variantes = defaultdict(Counter)
    par_champ = defaultdict(Counter)
    fiches_vues = defaultdict(set)
    extraits = defaultdict(list)

    for fiche in fiches:
        ref = fiche.get(CHAMP_ID) or "?"
        for champ, texte in _champs_texte(fiche):
            for sigle, observee in _candidats(texte):
                frequences[sigle] += 1
                variantes[sigle][observee] += 1
                par_champ[sigle][champ] += 1
                fiches_vues[sigle].add(ref)
                if len(extraits[sigle]) < nb_extraits and ref not in {
                    e["fiche"] for e in extraits[sigle]
                }:
                    bout = _extrait(texte, observee)
                    if bout:
                        extraits[sigle].append({"fiche": ref, "texte": bout})

    retenus, exclus = [], []
    for sigle, freq in frequences.most_common():
        motif = _motif_exclusion(sigle)
        if motif:
            exclus.append({"sigle": sigle, "frequence": freq, "motif": motif})
            continue
        if sigle in {t.upper() for t in TERMES_MINUSCULES}:
            categorie = "minuscule"
        elif any(c.isdigit() for c in sigle):
            categorie = "alphanumerique"
        else:
            categorie = "alpha"
        entree = {
            "sigle": sigle,
            "frequence": freq,
            "nb_fiches": len(fiches_vues[sigle]),
            "categorie": categorie,
            "variantes": dict(variantes[sigle].most_common()),
            "champs": dict(par_champ[sigle].most_common(5)),
            "extraits": extraits[sigle],
        }
        note = TERMES_MINUSCULES.get(sigle.lower()) or SIGLES_PROTEGES.get(sigle)
        if note:
            entree["remarque"] = note
        retenus.append(entree)

    resultat = {
        "meta": {
            "genere_le": datetime.now().isoformat(timespec="seconds"),
            "source": chemin_source,
            "nb_fiches": len(fiches),
            "champs_analyses": CHAMPS_TEXTE
            + [f"{liste}.{c}" for liste in LISTES_ACTIONS for c in CHAMPS_ACTIONS],
            "regles": {
                "motif_sigle": RE_SIGLE.pattern,
                "longueur": "2 à 8 caractères",
                "formes_pointees": "F.O.D normalisé en FOD",
                "termes_minuscules": sorted(TERMES_MINUSCULES),
                "categories": {
                    "alpha": "sigle purement alphabétique",
                    "alphanumerique": "contient un chiffre : NP7 (niveau de "
                    "protection) mais aussi numéros de vol et postes — à trier "
                    "par le métier",
                    "minuscule": "terme du jargon écrit en minuscules",
                },
            },
            "totaux": {
                "sigles_retenus": len(retenus),
                "occurrences_retenues": sum(e["frequence"] for e in retenus),
                "tokens_exclus": len(exclus),
            },
        },
        "sigles": retenus,
        "exclus": exclus,
    }

    with open(chemin_sortie, "w", encoding="utf-8") as f:
        json.dump(resultat, f, ensure_ascii=False, indent=2)

    m = resultat["meta"]["totaux"]
    print(
        f"Terminé : {m['sigles_retenus']} sigles ({m['occurrences_retenues']} "
        f"occurrences), {m['tokens_exclus']} tokens écartés (tracés dans "
        f"« exclus »).\nÉcrit dans {chemin_sortie}"
    )
    return resultat


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--source",
        default="/home/yie0070/retex-split/retex-ingestion/data/samples/incidents_avec_actions.json",
    )
    p.add_argument("--sortie", default="/home/yie0070/retex-split/sigles_frequences.json")
    p.add_argument("--extraits", type=int, default=3)
    args = p.parse_args()
    extraire(args.source, args.sortie, args.extraits)
