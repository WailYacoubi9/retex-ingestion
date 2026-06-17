"""
Parser Markdown -> InfoSecuriteCanonique pour le module DGAC.

Lit un fichier .md produit par OpenDataLoader (cf scripts/parse_dgac_pdfs.py)
et en extrait une structure pivot InfoSecuriteCanonique exploitable
par le loader Neo4j/Qdrant.

Strategie de parsing :
  1. Le nom de fichier "is_YYYY_NN.md" donne is_number et annee.
  2. Le pied de page (regex "Version n°X du DD/MM/YYYY") donne version_numero
     et date_version (Optional, non present sur toutes les IS).
  3. Tous les tableaux Markdown sont extraits et leurs lignes parcourues :
     - Si la cellule gauche est un label connu (LABELS_ALIASES) :
       mapper vers le champ canonique, concatener si deja rempli, ajouter
       un marqueur "## <label>" si le label est dans LABELS_TO_PRESERVE_AS_MARKER.
     - Si la cellule gauche est vide ET on a un champ courant : continuation
       (concatener au dernier champ identifie).
     - Si la cellule gauche est du bruit standard (en-tete repete, texte
       d'avertissement) : ignorer.
     - Sinon : extra_fields.
  4. Le contenu apres le dernier tableau est stocke dans contenu_hors_tableau.
  5. La phrase "annule et remplace l'IS XXXX/YY" est detectee dans contexte
     pour remplir remplace.

Cf scripts/audit_dgac_markdown.py pour la justification des regles.
"""
from __future__ import annotations

import logging
import re
from dataclasses import fields
from datetime import date
from pathlib import Path
from typing import Optional

from dgac_constants import (
    CHAMPS_TEXTUELS_CANONIQUES,
    LABELS_ALIASES,
    LABELS_TO_IGNORE_PREFIXES,
    LABELS_TO_PRESERVE_AS_MARKER,
)
from models_info_securite import (
    InfoSecuriteCanonique,
    make_info_securite_uuid,
)


logger = logging.getLogger(__name__)


# =====================================================================
# REGEX DE PARSING
# =====================================================================

# Nom de fichier attendu : is_2024_01.md -> is_number="2024/01", annee=2024
FILENAME_PATTERN = re.compile(r"^is_(\d{4})_(\d{2})\.md$")

# Ligne de separateur de tableau Markdown : |---|---| ou |:--|:--:|
SEPARATOR_PATTERN = re.compile(r"^\s*\|[\s\-:|]+\|\s*$")

# Pied de page Version : capture le numero et la date brute (variantes
# de format gerees : "10/03/2026", "10 mars 2026", "10 / 03 / 2026")
VERSION_FOOTER_PATTERN = re.compile(
    r"Version\s+n\s*[°ºo]?\s*(\d+)\s+du\s+([\d/\s\w]+?\d{4})",
    re.IGNORECASE,
)

# Detection de "annule et remplace l'IS XXXX/YY" dans le contexte.
# Capture le numero de l'IS remplacee.
REMPLACE_PATTERN = re.compile(
    r"(?:annule\s+et\s+)?remplace\s+(?:l['\u2019]?)?(?:IS|info\s+s[ée]curit[ée]\s+n[°º]?)\s*(\d{4})[\s/-]+(\d{1,2})",
    re.IGNORECASE,
)

# Mois francais -> numero pour parser les dates en lettres
MOIS_FR_TO_NUM = {
    "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "aout": 8, "août": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
    "décembre": 12,
}


# =====================================================================
# NORMALISATION DES LABELS
# =====================================================================

# Map de remplacement pour normaliser les caracteres accentues, fonction
# de normalize_label() ci-dessous.
_ACCENT_MAP = str.maketrans({
    "à": "a", "â": "a", "ä": "a",
    "é": "e", "è": "e", "ê": "e", "ë": "e",
    "î": "i", "ï": "i",
    "ô": "o", "ö": "o",
    "ù": "u", "û": "u", "ü": "u",
    "ç": "c",
    "À": "a", "Â": "a",
    "É": "e", "È": "e", "Ê": "e",
    "Î": "i", "Ï": "i",
    "Ô": "o",
    "Ç": "c",
    "’": "'",
})


def normalize_label(label: str) -> str:
    """Normalise un label pour le matcher avec LABELS_ALIASES.

    Utilisation : retire les balises HTML (notamment <br>), les accents,
    lowercase, retire les ':' finaux, collapse les espaces multiples.
    Ex : "Operateurs concernes :" -> "operateurs concernes".
    Ex : "Actions recommandees<br><br>" -> "actions recommandees".

    Args:
        label: Le label brut tel que vu dans le Markdown.

    Returns:
        Le label normalise, pret a etre matche dans LABELS_ALIASES.
    """
    if not label:
        return ""
    # Retirer d'abord les balises <br> qui peuvent etre collees au label
    cleaned = re.sub(r"<br\s*/?>", " ", label)
    cleaned = cleaned.translate(_ACCENT_MAP).lower().strip()
    cleaned = cleaned.rstrip(":").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def is_noise_label(label_normalized: str) -> bool:
    """Indique si un label correspond au bruit standard a ignorer.

    Utilisation : evite que le texte d'avertissement DGAC ou les en-tetes
    de page repetes soient interpretes comme des labels de champ.

    Args:
        label_normalized: Label deja normalise via normalize_label().

    Returns:
        True si le label correspond a un prefixe de bruit, False sinon.
    """
    for prefix in LABELS_TO_IGNORE_PREFIXES:
        if label_normalized.startswith(prefix):
            return True
    return False


def is_plausible_label(label: str) -> bool:
    """Filtre les cellules qui ressemblent a des labels de champ.

    Utilisation : avant de tenter normalize_label + lookup, on filtre les
    cellules manifestement trop longues, contenant des URLs, ou des
    balises HTML qui sont en realite du contenu mal aligne.

    Cas particulier : un label peut avoir des "<br><br>" colles a la fin
    (artefact OpenDataLoader, vu sur 2020/01 et 2023/02). On nettoie ces
    balises avant le test de longueur et d'URL.

    Args:
        label: Le label brut tel que vu dans le Markdown.

    Returns:
        True si la cellule peut etre un label de champ, False sinon.
    """
    if not label or not label.strip():
        return False

    # Nettoyer les <br> qui peuvent etre colles en fin de label
    # (artefact OpenDataLoader sur certaines IS).
    cleaned = re.sub(r"<br\s*/?>", " ", label).strip()
    if not cleaned:
        return False

    # Test de longueur sur le label nettoye, pas le brut
    if len(cleaned) > 100:
        return False

    cleaned_lower = cleaned.lower()
    if "http://" in cleaned_lower or "https://" in cleaned_lower:
        return False
    if "![" in cleaned_lower:
        return False
    return True


# =====================================================================
# EXTRACTION DES METADONNEES DU NOM DE FICHIER
# =====================================================================

def parse_filename(md_path: Path) -> tuple[str, int]:
    """Extrait is_number et annee depuis le nom du fichier .md.

    Utilisation : "is_2024_01.md" -> ("2024/01", 2024).

    Args:
        md_path: Chemin vers le fichier .md.

    Returns:
        Tuple (is_number, annee).

    Raises:
        ValueError: Si le nom de fichier ne respecte pas le format attendu.
    """
    match = FILENAME_PATTERN.match(md_path.name)
    if not match:
        raise ValueError(
            f"Nom de fichier inattendu : {md_path.name} (attendu : is_YYYY_NN.md)"
        )
    annee_str, num_str = match.group(1), match.group(2)
    is_number = f"{annee_str}/{num_str}"
    annee = int(annee_str)
    return is_number, annee


# =====================================================================
# EXTRACTION DU PIED DE PAGE (Version + date)
# =====================================================================

def parse_french_date(date_brute: str) -> Optional[date]:
    """Parse une date au format francais variable.

    Utilisation : gere les formats observes dans le corpus :
      - "10/03/2026"      -> date(2026, 3, 10)
      - "10 mars 2026"    -> date(2026, 3, 10)
      - "10 / 03 / 2026"  -> date(2026, 3, 10)

    Args:
        date_brute: La string de date telle que capturee par la regex.

    Returns:
        Un objet date, ou None si le parsing echoue.
    """
    if not date_brute:
        return None
    cleaned = re.sub(r"\s+", " ", date_brute).strip()

    # Format DD/MM/YYYY ou DD / MM / YYYY
    match_num = re.match(r"^(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})$", cleaned)
    if match_num:
        try:
            return date(int(match_num.group(3)), int(match_num.group(2)),
                        int(match_num.group(1)))
        except ValueError:
            return None

    # Format DD <mois> YYYY
    match_text = re.match(r"^(\d{1,2})\s+(\w+)\s+(\d{4})$", cleaned)
    if match_text:
        jour = int(match_text.group(1))
        mois_str = match_text.group(2).lower()
        annee = int(match_text.group(3))
        mois_num = MOIS_FR_TO_NUM.get(mois_str)
        if mois_num:
            try:
                return date(annee, mois_num, jour)
            except ValueError:
                return None

    return None


def extract_version_and_date(markdown: str) -> tuple[Optional[int], Optional[date]]:
    """Extrait version_numero et date_version du pied de page Markdown.

    Utilisation : retourne (None, None) si aucun pied de page detecte
    (cas de ~43 des 53 IS du corpus, OpenDataLoader filtre inegalement
    les footers).

    Args:
        markdown: Le contenu Markdown complet du fichier.

    Returns:
        Tuple (version_numero, date_version), chacun Optional.
    """
    match = VERSION_FOOTER_PATTERN.search(markdown)
    if not match:
        return None, None
    try:
        version_numero = int(match.group(1))
    except ValueError:
        version_numero = None
    date_version = parse_french_date(match.group(2))
    return version_numero, date_version


# =====================================================================
# EXTRACTION DES TABLEAUX MARKDOWN
# =====================================================================

def extract_table_rows(markdown: str) -> list[list[str]]:
    """Extrait toutes les lignes de tous les tableaux du Markdown.

    Utilisation : retourne une liste plate de lignes, ou chaque ligne
    est une liste de cellules. Les lignes de separateur |---|---| sont
    ignorees. Les tableaux multiples (cas frequent dans le corpus) sont
    concatenes dans une seule liste plate.

    Args:
        markdown: Le contenu Markdown complet du fichier.

    Returns:
        Liste de lignes, chaque ligne etant une liste de cellules (str).
    """
    rows: list[list[str]] = []
    for raw_line in markdown.split("\n"):
        line = raw_line.rstrip()
        if not line.startswith("|") or not line.endswith("|"):
            continue
        if SEPARATOR_PATTERN.match(line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append(cells)
    return rows


def extract_content_after_last_table(markdown: str) -> Optional[str]:
    """Extrait le contenu textuel apres le dernier tableau Markdown.

    Utilisation : capture les annexes/references qui apparaissent en
    flux libre apres les tableaux (cas 2022/02, 2022/03, 2024/03, 2018/01).

    Args:
        markdown: Le contenu Markdown complet du fichier.

    Returns:
        Le contenu hors tableau nettoye, ou None si vide/insignifiant.
    """
    lines = markdown.split("\n")
    last_table_idx = -1
    for i, line in enumerate(lines):
        if line.startswith("|") and line.endswith("|"):
            last_table_idx = i

    if last_table_idx == -1:
        return None

    after_lines = lines[last_table_idx + 1:]
    after_text = "\n".join(after_lines).strip()

    # Nettoyage : pied de page DGAC standard + URL d'avertissement
    after_text = re.sub(
        r"Toute remarque quant.*?rex@aviation-civile\.gouv\.fr",
        "",
        after_text,
        flags=re.DOTALL,
    )
    after_text = VERSION_FOOTER_PATTERN.sub("", after_text)
    after_text = after_text.strip()

    # Seuil arbitraire : moins de 100 chars c'est probablement du residuel
    if len(after_text) < 100:
        return None
    return after_text


# =====================================================================
# LOGIQUE PRINCIPALE : PARCOURS DES LIGNES DE TABLEAU
# =====================================================================

def get_cell_content_from_row(row: list[str]) -> str:
    """Concatene les cellules de droite (apres la cellule label) en une
    seule string.

    Utilisation : certains tableaux OpenDataLoader ont une colonne
    intermediaire vide (cf cas 2023/02 a 3 colonnes : label, vide, contenu).
    On joint tout ce qui n'est pas la cellule de gauche.

    Args:
        row: Une ligne de tableau Markdown (liste de cellules).

    Returns:
        Le contenu textuel concatene des cellules de droite.
    """
    if len(row) <= 1:
        return ""
    right_cells = [c for c in row[1:] if c]
    return " ".join(right_cells).strip()


def append_to_field(
    canonique: InfoSecuriteCanonique,
    champ_canonique: str,
    contenu: str,
    marker: Optional[str] = None,
) -> None:
    """Ajoute du contenu a un champ du dataclass, avec concatenation propre.

    Utilisation : si le champ contient deja du contenu, on ajoute "\n\n"
    avant le nouveau. Si un marker est fourni, on ajoute "## <marker>\n\n"
    avant le contenu (preservation de la sous-section).

    Args:
        canonique: L'instance a modifier en place.
        champ_canonique: Nom du champ (doit etre un attribut du dataclass).
        contenu: Le contenu textuel a ajouter.
        marker: Le label d'origine a preserver comme titre Markdown, optionnel.
    """
    if not contenu:
        return

    bloc = contenu
    if marker:
        bloc = f"## {marker}\n\n{contenu}"

    valeur_actuelle = getattr(canonique, champ_canonique, None)
    if valeur_actuelle:
        nouvelle_valeur = f"{valeur_actuelle}\n\n{bloc}"
    else:
        nouvelle_valeur = bloc
    setattr(canonique, champ_canonique, nouvelle_valeur)


def process_table_rows(
    rows: list[list[str]],
    canonique: InfoSecuriteCanonique,
) -> None:
    """Parcourt les lignes de tableau et remplit le dataclass.

    Utilisation : applique les regles de parsing decrites en tete de
    module (bruit / label connu / continuation / ad hoc).

    Args:
        rows: Liste de lignes (chaque ligne est une liste de cellules).
        canonique: Le dataclass a remplir en place.
    """
    dernier_champ_courant: Optional[str] = None

    for row in rows:
        if not row:
            continue

        gauche_brute = row[0].strip() if row else ""
        contenu_droite = get_cell_content_from_row(row)

        # Cas A : cellule gauche vide
        if not gauche_brute:
            # A.1 : si la droite est manifestement un bruit d'en-tete
            #       (titre repete "INFO SECURITE DGAC N° YYYY/NN"), ignorer
            if _is_noise_right_cell(contenu_droite):
                continue
            # A.2 : sinon, continuation du dernier champ courant
            if dernier_champ_courant and contenu_droite:
                append_to_field(canonique, dernier_champ_courant, contenu_droite)
            continue

        # Cas B : cellule gauche manifestement pas un label (trop longue,
        # contient une URL, contient du HTML)
        if not is_plausible_label(gauche_brute):
            continue

        gauche_normalisee = normalize_label(gauche_brute)

        # Cas C : cellule gauche = bruit standard (avertissement DGAC,
        # en-tete de page)
        if is_noise_label(gauche_normalisee):
            continue

        # Cas D : cellule gauche = label canonique connu
        if gauche_normalisee in LABELS_ALIASES:
            champ_canonique = LABELS_ALIASES[gauche_normalisee]
            marker = (
                gauche_brute.rstrip(":").strip()
                if gauche_normalisee in LABELS_TO_PRESERVE_AS_MARKER
                else None
            )

            # Cas particulier : operateurs_concernes est une list[str],
            # pas un str. On le traite a part.
            if champ_canonique == "operateurs_concernes":
                canonique.operateurs_concernes.extend(
                    _split_operateurs(contenu_droite)
                )
            else:
                append_to_field(canonique, champ_canonique, contenu_droite, marker)
            dernier_champ_courant = champ_canonique
            continue

        # Cas E : label inconnu = ad hoc, stockage dans extra_fields
        if contenu_droite:
            canonique.extra_fields[gauche_normalisee] = contenu_droite
            dernier_champ_courant = None  # ad hoc n'autorise pas la continuation


def _is_noise_right_cell(content: str) -> bool:
    """Detecte si une cellule de droite est un en-tete de page repete.

    Utilisation : "INFO SECURITE DGAC N° 2024/01" ou des balises image.

    Args:
        content: Le contenu de la cellule de droite.

    Returns:
        True si c'est du bruit, False sinon.
    """
    if not content:
        return True
    content_lower = content.lower()
    noise_markers = (
        "info securite dgac",
        "info sécurité dgac",
        "n° 20",
        "no 20",
    )
    for marker in noise_markers:
        if marker in content_lower and len(content) < 150:
            return True
    # Cellule constituee uniquement de balises image
    if content.startswith("![") and content.endswith(")"):
        return True
    return False


def _split_operateurs(contenu: str) -> list[str]:
    """Decoupe le contenu du champ Operateurs concernes en liste.

    Utilisation : le contenu peut etre formate de plusieurs facons :
      "• NCO<br>• Ballons<br>• SPO/TA91" -> ["NCO", "Ballons", "SPO/TA91"]
      "Exploitants d'aeronefs Pilotes qualifies IFR" -> liste a 1 ou 2 elements
      "NCO\nBallons\nSPO" -> ["NCO", "Ballons", "SPO"]

    Args:
        contenu: Le contenu brut du champ Operateurs concernes.

    Returns:
        Liste de strings, une entree par operateur identifie.
    """
    if not contenu:
        return []
    # Remplacer les <br> et balises de liste par des newlines
    texte = re.sub(r"<br\s*/?>", "\n", contenu, flags=re.IGNORECASE)
    # Decouper sur newlines, puces, tirets en debut de ligne
    parts = re.split(r"\n|•|\u25CF|\u2022", texte)
    cleaned = [p.strip(" -\t") for p in parts]
    return [p for p in cleaned if p and len(p) > 1]


# =====================================================================
# DETECTION DE "annule et remplace"
# =====================================================================

def extract_remplace(contexte: Optional[str]) -> list[str]:
    """Extrait les references aux IS remplacees par celle-ci.

    Utilisation : cherche le pattern "annule et remplace l'IS YYYY/NN"
    dans le contexte du PDF. En V1 seulement 1 cas sur 53 detecte ;
    les autres chaines historiques restent inconnues.

    Args:
        contexte: Le champ contexte deja rempli du dataclass.

    Returns:
        Liste de is_number remplaces, ou liste vide.
    """
    if not contexte:
        return []
    results: list[str] = []
    for match in REMPLACE_PATTERN.finditer(contexte):
        annee, num = match.group(1), match.group(2)
        results.append(f"{annee}/{int(num):02d}")
    return results


# =====================================================================
# POINT D'ENTREE PUBLIC
# =====================================================================

def parse_markdown_to_canonique(md_path: Path) -> InfoSecuriteCanonique:
    """Parse un fichier Markdown DGAC en InfoSecuriteCanonique.

    Utilisation : fonction principale du module. Appellee par
    l'orchestrateur (scripts/ingest_dgac.py) pour chaque .md du corpus.

    Args:
        md_path: Chemin vers le fichier .md a parser. Le nom doit
            respecter le format is_YYYY_NN.md.

    Returns:
        Instance d'InfoSecuriteCanonique remplie. Les champs non
        detectes restent a leur valeur par defaut (None ou liste vide).

    Raises:
        FileNotFoundError: Si le fichier n'existe pas.
        ValueError: Si le nom de fichier ne respecte pas le format attendu.
    """
    if not md_path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {md_path}")

    # Etape 1 : identification depuis le nom de fichier
    is_number, annee = parse_filename(md_path)
    info_securite_id = make_info_securite_uuid(is_number)

    # Lecture du contenu
    markdown = md_path.read_text(encoding="utf-8")

    # Etape 2 : version et date depuis le pied de page (peuvent etre None)
    version_numero, date_version = extract_version_and_date(markdown)

    # Etape 3 : initialisation du dataclass avec titre temporaire
    # (sera enrichi a la fin si le sujet a ete extrait)
    canonique = InfoSecuriteCanonique(
        is_number=is_number,
        annee=annee,
        info_securite_id=info_securite_id,
        titre=f"IS DGAC {is_number}",  # placeholder, sera ecrase si possible
        version_numero=version_numero,
        date_version=date_version,
    )

    # Etape 4 : parcours des lignes de tous les tableaux
    rows = extract_table_rows(markdown)
    process_table_rows(rows, canonique)

    # Etape 5 : capture du contenu hors tableau
    canonique.contenu_hors_tableau = extract_content_after_last_table(markdown)

    # Etape 6 : detection de "annule et remplace" dans le contexte
    canonique.remplace = extract_remplace(canonique.contexte)

    # Etape 7 : enrichissement du titre depuis le sujet
    if canonique.sujet:
        canonique.titre = canonique.sujet

    logger.debug(
        "Parse %s : sujet=%s, operateurs=%d, contexte=%d chars, "
        "actions=%d chars, extra=%d",
        md_path.name,
        bool(canonique.sujet),
        len(canonique.operateurs_concernes),
        len(canonique.contexte or ""),
        len(canonique.actions_recommandees or ""),
        len(canonique.extra_fields),
    )

    return canonique