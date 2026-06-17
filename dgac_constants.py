"""
Constantes de parsing pour le module d'ingestion DGAC Info Securite.

Centralise les dictionnaires de mapping label Markdown -> champ canonique.
Issu de l'audit des 53 IS du corpus (scripts/audit_dgac_markdown.py).
Toute variante de label observee dans le corpus est listee ici.

Mise a jour : si l'audit revele une nouvelle variante non couverte,
l'ajouter dans LABELS_ALIASES (et eventuellement dans LABELS_TO_PRESERVE_AS_MARKER
si on veut garder le label d'origine comme marqueur dans le contenu concatene).
"""
from __future__ import annotations


# Mapping label normalise (lowercase, sans accents, sans ":") -> champ canonique.
# Le parser applique normalize_label() avant de chercher dans ce dict.
LABELS_ALIASES: dict[str, str] = {
    # Operateurs concernes
    "operateurs concernes": "operateurs_concernes",

    # Sujet
    "sujet": "sujet",

    # Objectif
    "objectif": "objectif",

    # Contexte et toutes ses variantes (concatenees avec marqueur ## si specifique)
    "contexte": "contexte",
    "contexte aeronautique": "contexte",                # 2017/03
    "contexte technique": "contexte",                   # 2017/03
    "contexte reglementaire": "contexte",               # 2018/03
    "exigences reglementaires": "contexte",             # 2019/02
    "breve description de l'evenement": "contexte",     # 2012/03
    "enseignements de securite": "contexte",            # 2012/03

    # Actions recommandees et ses variantes
    "actions recommandees": "actions_recommandees",
    "actions recommandee s": "actions_recommandees",                          # 2023/02 (espace inserre par OpenDataLoader)
    "actions de reduction de risque": "actions_recommandees",       # 2011/02
    "bonnes pratiques identifiees": "actions_recommandees",         # 2010/01
    "bonne pratique": "actions_recommandees",                       # 2025/01
    "suites donnees": "actions_recommandees",                       # 2012/03
    "prevention des evenements fumees et odeurs": "actions_recommandees",  # 2020/05
    "evolution des mesures de reduction des risques": "actions_recommandees",   # 2019/02
    "menaces et mesures de reduction des risques": "actions_recommandees",       # 2020/02, 2020/03

    # Annexe (singulier ou pluriel)
    "annexe": "annexe",
    "annexes": "annexe",

    # References (singulier ou pluriel)
    "references": "references",
    "reference": "references",
    "autres documents d'information": "references",     # 2012/03
}


# Sous-ensemble de LABELS_ALIASES : labels pour lesquels on veut conserver
# le nom d'origine comme marqueur "## <label original>" dans le contenu
# concatene. Permet de preserver l'info que c'etait une sous-section nommee.
#
# Exemple : 2017/03 a "Contexte aeronautique" et "Contexte technique".
# Apres parsing, son champ `contexte` contiendra :
#
#   ## Contexte aeronautique
#   [contenu...]
#
#   ## Contexte technique
#   [contenu...]
LABELS_TO_PRESERVE_AS_MARKER: set[str] = {
    "contexte aeronautique",
    "contexte technique",
    "contexte reglementaire",
    "exigences reglementaires",
    "breve description de l'evenement",
    "enseignements de securite",
    "suites donnees",
    "prevention des evenements fumees et odeurs",
    "bonnes pratiques identifiees",
    "bonne pratique",
    "actions de reduction de risque",
    "autres documents d'information",
    "evolution des mesures de reduction des risques",
    "menaces et mesures de reduction des risques",
}


# Labels normalises a IGNORER explicitement quand rencontres dans le parser.
# Correspondent au bruit standard observe dans le corpus (en-tete de page
# repete, avertissement DGAC standard, etc.). Si une cellule gauche
# correspond a un de ces patterns, on saute la ligne entiere.
LABELS_TO_IGNORE_PREFIXES: tuple[str, ...] = (
    "une info securite est un document",
    "info securite dgac",
    "info securite",
)


# Champs du dataclass InfoSecuriteCanonique qui sont des chaines vides
# de defaut (servent au parser pour distinguer "non rempli" de "vide explicite").
# Permet au parser de savoir s'il doit concatener (champ deja rempli) ou
# initialiser (champ vide).
CHAMPS_TEXTUELS_CANONIQUES: tuple[str, ...] = (
    "sujet",
    "objectif",
    "contexte",
    "actions_recommandees",
    "annexe",
    "references",
)