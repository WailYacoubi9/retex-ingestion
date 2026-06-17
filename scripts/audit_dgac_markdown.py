"""
Audit du corpus de Markdown DGAC parses par OpenDataLoader.

Objectif : avant d'ecrire le parser final, comprendre la structure reelle
des 53 fichiers .md. Produit un rapport synthetique qui repond a :

1. Combien de fichiers ont au moins 1 tableau Markdown ?
2. Quels labels apparaissent dans la 1re colonne des tableaux ?
   (avec frequence et liste des fichiers ou ils apparaissent)
3. Combien de fichiers ont du contenu hors tableau (apres le dernier tableau) ?
4. Quels formats de pied de page (Version) sont detectables ?
5. Combien de fichiers mentionnent "annule et remplace" ?
6. Distribution des tailles de Markdown

Pas de Neo4j, pas de Qdrant. Juste de l'analyse statistique.

Usage :
    python scripts/audit_dgac_markdown.py
"""
from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MD_DIR = PROJECT_ROOT / "data" / "samples" / "dgac_parsed"
REPORT_PATH = PROJECT_ROOT / "data" / "samples" / "dgac_audit_report.md"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("audit_dgac")


# =====================================================================
# DETECTION DES TABLEAUX MARKDOWN
# =====================================================================

# Un tableau Markdown commence par une ligne avec | et a une ligne de
# separateur |---|---|. On utilise une regex permissive sur la ligne
# de separation.
SEPARATOR_PATTERN = re.compile(r"^\s*\|[\s\-:|]+\|\s*$")


def extract_table_rows(markdown: str) -> list[list[str]]:
    """Extrait toutes les lignes de tous les tableaux du Markdown.

    Utilisation : retourne une liste plate de lignes, ou chaque ligne
    est une liste de cellules (str). Les separateurs |---|---| et les
    lignes d'en-tete vides sont exclus.
    """
    rows: list[list[str]] = []
    lines = markdown.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        # Une ligne de tableau commence et finit par |
        if line.startswith("|") and line.endswith("|"):
            # On verifie si c'est une ligne de separateur (a ignorer)
            if SEPARATOR_PATTERN.match(line):
                i += 1
                continue
            # Extraction des cellules
            cells = [c.strip() for c in line.strip("|").split("|")]
            rows.append(cells)
        i += 1
    return rows


def has_table(markdown: str) -> bool:
    """Indique si le Markdown contient au moins une vraie ligne de tableau.

    Utilisation : test rapide pour le rapport.
    """
    return len(extract_table_rows(markdown)) > 0


# =====================================================================
# NORMALISATION DES LABELS (cellule gauche)
# =====================================================================

# On retire les accents et on lowercase pour fusionner les variantes
# orthographiques. Les ':' eventuels en fin de label sont aussi enleves.
ACCENT_MAP = str.maketrans({
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
    "’": "'", "'": "'",
})


def normalize_label(label: str) -> str:
    """Normalise un label de cellule gauche pour le regroupement.

    Utilisation : 'Operateurs concernes :' / 'Opérateur concernés' / 'OPERATEURS CONCERNES'
    deviennent tous 'operateurs concernes'.
    """
    cleaned = label.translate(ACCENT_MAP).lower().strip()
    cleaned = cleaned.rstrip(":").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def is_plausible_label(label: str) -> bool:
    """Filtre les cellules qui ressemblent a des noms de champs.

    Utilisation : evite que des cellules de contenu (longues phrases)
    ou des cellules vides soient comptees comme labels.
    """
    if not label:
        return False
    # Trop long pour etre un nom de champ
    if len(label) > 80:
        return False
    # Mots-cles a exclure (texte d'avertissement standard, URLs, etc.)
    excluded_keywords = [
        "une info securite est un document",
        "cette info securite est disponible",
        "http://",
        "https://",
        "<br>",
        "![",
    ]
    label_lower = label.lower()
    for kw in excluded_keywords:
        if kw in label_lower:
            return False
    return True


def looks_like_field_label(label: str) -> bool:
    """Decide si une cellule gauche est probablement un label de champ.

    Utilisation : appliquee apres is_plausible_label. Un label de champ
    a typiquement 1 a 5 mots, commence par une majuscule, ne contient
    pas de ponctuation forte (point final, etc.).
    """
    if not is_plausible_label(label):
        return False
    words = label.split()
    if len(words) > 6:
        return False
    if not words:
        return False
    # Le 1er caractere doit etre une lettre (pas un chiffre ni symbole)
    if not words[0][0].isalpha():
        return False
    return True


# =====================================================================
# DETECTION DU PIED DE PAGE (Version + date)
# =====================================================================

# On capture differents formats observes :
#   "Version n°1 du 10 mars 2026"
#   "Version n°2 du 26/01/2011"
#   "Version n° 2 du 27 / 02 / 2026"
VERSION_PATTERN = re.compile(
    r"Version\s+n\s*[°ºo]?\s*(\d+)\s+du\s+([\d/\s\w]+?\d{4})",
    re.IGNORECASE,
)


def find_version_footers(markdown: str) -> list[tuple[str, str]]:
    """Cherche toutes les occurrences de pieds de page Version.

    Utilisation : retourne liste de (numero_version, date_brute) pour
    inspection. Le parsing fin de la date sera fait dans le parser
    principal, pas ici.
    """
    results = []
    for match in VERSION_PATTERN.finditer(markdown):
        numero, date_brute = match.group(1), match.group(2).strip()
        results.append((numero, date_brute))
    return results


# =====================================================================
# DETECTION DE "annule et remplace"
# =====================================================================

REMPLACE_PATTERN = re.compile(
    r"(?:annule\s+et\s+)?remplace\s+(?:l['\u2019]?)?(?:IS|info\s+s[ée]curit[ée]\s+n[°º]?)\s*(\d{4})[\s/-]+(\d{1,2})",
    re.IGNORECASE,
)


def find_replaced_is(markdown: str) -> list[str]:
    """Cherche les references a des IS remplacees par celle-ci.

    Utilisation : detecte les patterns "annule et remplace l'IS 2012/04"
    ou "remplace l'Info Securite n°2013/05".
    """
    results = []
    for match in REMPLACE_PATTERN.finditer(markdown):
        annee, num = match.group(1), match.group(2)
        results.append(f"{annee}/{int(num):02d}")
    return results


# =====================================================================
# CONTENU HORS TABLEAU
# =====================================================================

def estimate_content_after_last_table(markdown: str) -> int:
    """Estime la taille (en caracteres) du contenu apres le dernier tableau.

    Utilisation : reperer les IS qui ont des annexes ou des references
    en flux libre apres le tableau principal (cas 2022/03, 2024/03, 2022/02).
    """
    lines = markdown.split("\n")
    # Cherche le dernier index ou il y a une ligne commencant par |
    last_table_line = -1
    for i, line in enumerate(lines):
        if line.startswith("|") and line.endswith("|"):
            last_table_line = i

    if last_table_line == -1:
        return 0

    after = "\n".join(lines[last_table_line + 1:])
    # On retire les lignes vides et le pied de page pour estimer le contenu utile
    after_cleaned = re.sub(r"Toute remarque quant.*?rex@aviation-civile\.gouv\.fr", "", after, flags=re.DOTALL)
    after_cleaned = re.sub(r"Version n[°ºo]?\s*\d+\s+du\s+[\d/\s\w]+\d{4}", "", after_cleaned)
    return len(after_cleaned.strip())


# =====================================================================
# AUDIT D'UN FICHIER
# =====================================================================

def audit_one_file(md_path: Path) -> dict:
    """Audite un fichier Markdown et retourne un dictionnaire de stats.

    Utilisation : appelee pour chaque .md du dossier. Le dict retourne
    est consolide dans le rapport global.
    """
    content = md_path.read_text(encoding="utf-8")
    rows = extract_table_rows(content)

    # Extraction des labels de la 1re colonne
    labels_normalized: list[str] = []
    labels_raw: list[str] = []
    empty_left_count = 0
    for row in rows:
        if not row:
            continue
        first_cell = row[0].strip()
        if not first_cell:
            empty_left_count += 1
            continue
        if looks_like_field_label(first_cell):
            labels_raw.append(first_cell)
            labels_normalized.append(normalize_label(first_cell))

    return {
        "file": md_path.name,
        "size_bytes": md_path.stat().st_size,
        "has_table": len(rows) > 0,
        "n_table_rows": len(rows),
        "n_empty_left_cells": empty_left_count,
        "labels_raw": labels_raw,
        "labels_normalized": labels_normalized,
        "version_footers": find_version_footers(content),
        "replaced_is": find_replaced_is(content),
        "content_after_last_table_chars": estimate_content_after_last_table(content),
    }


# =====================================================================
# RAPPORT GLOBAL
# =====================================================================

def build_report(audits: list[dict]) -> str:
    """Construit le rapport Markdown a partir des audits individuels.

    Utilisation : agrege toutes les stats par fichier en sections
    thematiques lisibles.
    """
    n_files = len(audits)
    lines: list[str] = []
    lines.append("# Audit du corpus DGAC Markdown\n")
    lines.append(f"Fichiers analyses : **{n_files}**\n\n")

    # 1. Presence de tableaux
    n_with_table = sum(1 for a in audits if a["has_table"])
    lines.append("## 1. Presence de tableaux Markdown\n\n")
    lines.append(f"- Avec au moins un tableau : **{n_with_table} / {n_files}**\n")
    lines.append(f"- Sans aucun tableau : **{n_files - n_with_table}**\n")
    if n_files - n_with_table > 0:
        lines.append("\nFichiers sans tableau :\n")
        for a in audits:
            if not a["has_table"]:
                lines.append(f"- {a['file']} ({a['size_bytes']} octets)\n")
    lines.append("\n")

    # 2. Inventaire des labels detectes
    label_counter: Counter[str] = Counter()
    label_files: dict[str, list[str]] = defaultdict(list)
    label_raw_examples: dict[str, set[str]] = defaultdict(set)
    for a in audits:
        seen_in_file = set()
        for raw, normalized in zip(a["labels_raw"], a["labels_normalized"]):
            if normalized in seen_in_file:
                continue
            seen_in_file.add(normalized)
            label_counter[normalized] += 1
            label_files[normalized].append(a["file"])
            label_raw_examples[normalized].add(raw)

    lines.append("## 2. Inventaire des labels (cellule gauche du tableau)\n\n")
    lines.append("Tri par frequence decroissante. La colonne 'variantes' montre les graphies effectivement vues.\n\n")
    lines.append("| Label normalise | Occurrences | Couverture | Variantes orthographiques |\n")
    lines.append("|---|---|---|---|\n")
    for label, count in label_counter.most_common():
        coverage = round(100 * count / n_files, 1)
        variants = " / ".join(sorted(label_raw_examples[label]))
        # Tronquer la liste de variantes si trop longue
        if len(variants) > 120:
            variants = variants[:117] + "..."
        lines.append(f"| {label} | {count} | {coverage}% | {variants} |\n")
    lines.append("\n")

    # 2b. Detail par label : fichiers ou il apparait
    lines.append("### Detail par label (fichiers d'apparition)\n\n")
    for label, count in label_counter.most_common():
        lines.append(f"**{label}** ({count} IS)\n")
        files_for_label = sorted(set(label_files[label]))
        # Si plus de 15 fichiers, on tronque
        if len(files_for_label) > 15:
            shown = ", ".join(files_for_label[:15])
            lines.append(f"  - {shown}, ... ({len(files_for_label) - 15} de plus)\n\n")
        else:
            lines.append(f"  - {', '.join(files_for_label)}\n\n")

    # 3. Cellules gauches vides (continuation de champ)
    n_with_empty = sum(1 for a in audits if a["n_empty_left_cells"] > 0)
    lines.append("## 3. Cellules gauches vides (continuation de champ probable)\n\n")
    lines.append(f"Fichiers avec au moins 1 cellule gauche vide : **{n_with_empty} / {n_files}**\n\n")
    for a in audits:
        if a["n_empty_left_cells"] > 0:
            lines.append(f"- {a['file']} : {a['n_empty_left_cells']} cellules vides\n")
    lines.append("\n")

    # 4. Pieds de page (version + date)
    n_with_version = sum(1 for a in audits if a["version_footers"])
    lines.append("## 4. Pieds de page detectes (Version + date)\n\n")
    lines.append(f"Fichiers avec au moins un pied de page Version : **{n_with_version} / {n_files}**\n\n")
    lines.append("Echantillon de formats vus (premiere occurrence par fichier) :\n\n")
    seen_formats = set()
    for a in audits:
        if a["version_footers"]:
            numero, date_brute = a["version_footers"][0]
            example = f"Version n°{numero} du {date_brute}"
            seen_formats.add(example)
            lines.append(f"- {a['file']} : `{example}`\n")
    lines.append("\n")

    # 5. "annule et remplace"
    n_with_replace = sum(1 for a in audits if a["replaced_is"])
    lines.append("## 5. Detection de 'annule et remplace'\n\n")
    lines.append(f"Fichiers contenant cette mention : **{n_with_replace} / {n_files}**\n\n")
    for a in audits:
        if a["replaced_is"]:
            lines.append(f"- **{a['file']}** remplace : {', '.join(a['replaced_is'])}\n")
    lines.append("\n")

    # 6. Contenu hors tableau
    n_with_after = sum(1 for a in audits if a["content_after_last_table_chars"] > 100)
    lines.append("## 6. Contenu apres le dernier tableau (annexes, references en flux libre)\n\n")
    lines.append(f"Fichiers avec >100 caracteres apres le dernier tableau : **{n_with_after} / {n_files}**\n\n")
    sorted_audits = sorted(audits, key=lambda a: a["content_after_last_table_chars"], reverse=True)
    lines.append("Top 15 (taille decroissante) :\n\n")
    lines.append("| Fichier | Caracteres hors tableau |\n")
    lines.append("|---|---|\n")
    for a in sorted_audits[:15]:
        chars = a["content_after_last_table_chars"]
        if chars > 0:
            lines.append(f"| {a['file']} | {chars} |\n")
    lines.append("\n")

    # 7. Distribution des tailles
    lines.append("## 7. Distribution des tailles de Markdown\n\n")
    sizes = [a["size_bytes"] for a in audits]
    sizes_sorted = sorted(sizes)
    lines.append(f"- Minimum : {min(sizes)} octets\n")
    lines.append(f"- Maximum : {max(sizes)} octets\n")
    lines.append(f"- Moyenne : {sum(sizes) // n_files} octets\n")
    lines.append(f"- Median : {sizes_sorted[n_files // 2]} octets\n\n")

    return "".join(lines)


# =====================================================================
# ORCHESTRATION
# =====================================================================

def run_audit() -> int:
    """Lance l'audit complet sur tous les .md de MD_DIR.

    Utilisation : point d'entree principal. Lit chaque fichier, calcule
    les stats, ecrit le rapport global dans REPORT_PATH.
    """
    if not MD_DIR.exists():
        logger.error("Repertoire absent : %s", MD_DIR)
        return 1

    md_files = sorted(MD_DIR.glob("*.md"))
    if not md_files:
        logger.error("Aucun .md trouve dans %s", MD_DIR)
        return 1

    logger.info("Fichiers a analyser : %d", len(md_files))

    audits = [audit_one_file(p) for p in md_files]

    report = build_report(audits)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")

    logger.info("Rapport ecrit dans : %s", REPORT_PATH)

    # Apercu console : top 20 labels
    label_counter: Counter[str] = Counter()
    for a in audits:
        seen = set()
        for normalized in a["labels_normalized"]:
            if normalized not in seen:
                seen.add(normalized)
                label_counter[normalized] += 1

    logger.info("\n===== Top 20 labels detectes =====")
    for i, (label, count) in enumerate(label_counter.most_common(20), start=1):
        coverage = round(100 * count / len(md_files), 1)
        logger.info("%2d. [%3d / %5.1f%%] %s", i, count, coverage, label)

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(run_audit())