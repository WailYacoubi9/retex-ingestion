"""
Enrichissement des tickets via l'export CSV intra'know.

Le JSON intra'know ne contient pas le NOM du projet (seulement
projet_ticket._id, un identifiant opaque), ni structure / urgence /
individu. Ces informations ne vivent que dans l'export CSV. Ce module
fait la jointure sur numero_fe == colonne "N°" et injecte les valeurs
dans les dicts bruts AVANT le parsing, de sorte que parser_tickets les
recupere naturellement.

Cles injectees dans chaque ticket brut :
    projet_nom <- CSV "Projet"     (complete projet_ticket._id)
    structure  <- CSV "structure"
    urgence    <- CSV "urgent"     (Oui / Non)
    individu   <- CSV "individu"   (souvent vide)

Specificites de l'export : encode latin-1 (pas UTF-8), separateur ';'.
"""
from __future__ import annotations

import csv
import logging
import unicodedata
from pathlib import Path

logger = logging.getLogger(__name__)

# Cle injectee dans le dict brut -> en-tete de colonne CSV (sous forme "foldee" :
# sans accents, minuscule, espaces compresses ; voir _fold). Le matching folde
# evite les soucis d'encodage sur les en-tetes accentues ("etat", "etape").
CSV_FIELD_MAP = {
    "projet_nom": "projet",
    "structure": "structure",
    "urgence": "urgent",
    "individu": "individu",
    "importance": "importance",
    "etat": "etat",          # colonne "etat" (Actif/Clos) -- pas "etat encours"
    "etape_label": "etape",  # colonne "etape" (libelle, ex "Traitement (termine)")
}


def _fold(s: str) -> str:
    """Normalise un en-tete : sans accents, minuscule, espaces compresses."""
    norm = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return " ".join(norm.split()).strip().lower()


def build_csv_index(csv_path: Path) -> dict[str, dict[str, str | None]]:
    """Indexe l'export CSV par N° -> {projet_nom, structure, urgence, individu}.

    Args:
        csv_path: Chemin vers l'export CSV (latin-1, separateur ';').

    Returns:
        Un dict numero_fe -> dict des champs enrichis (valeurs None si vides).

    Raises:
        SystemExit: Si la colonne N° ou une colonne attendue est absente.
    """
    with csv_path.open(encoding="latin-1", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        # en-tete folde -> en-tete reel
        folded = {_fold(h): h for h in reader.fieldnames or []}

        id_col = next((folded[h] for h in folded if h.startswith("n")), None)
        if id_col is None:
            raise SystemExit(f"Colonne N° introuvable dans {csv_path}")

        resolved: dict[str, str] = {}
        for out_key, header_folded in CSV_FIELD_MAP.items():
            real = folded.get(header_folded)
            if real is None:
                raise SystemExit(f"Colonne CSV '{header_folded}' introuvable dans {csv_path}")
            resolved[out_key] = real

        index: dict[str, dict[str, str | None]] = {}
        for row in reader:
            numero = (row.get(id_col) or "").strip()
            if not numero:
                continue
            index[numero] = {
                out_key: (row.get(real) or "").strip() or None
                for out_key, real in resolved.items()
            }

    logger.info("Index CSV charge : %d tickets depuis %s", len(index), csv_path.name)
    return index


def enrich_raw_tickets(
    raw_list: list[dict],
    csv_index: dict[str, dict[str, str | None]],
) -> int:
    """Injecte les champs CSV dans les dicts bruts (mutation en place).

    Args:
        raw_list: Liste des tickets bruts issus du JSON intra'know.
        csv_index: Index retourne par build_csv_index.

    Returns:
        Le nombre de tickets effectivement enrichis (match trouve dans le CSV).
    """
    matched = 0
    for raw in raw_list:
        numero = str(raw.get("numero_fe") or raw.get("_id") or "").strip()
        enrich = csv_index.get(numero)
        if not enrich:
            continue
        matched += 1
        for key, val in enrich.items():
            raw[key] = val

    missing = len(raw_list) - matched
    logger.info("Enrichissement CSV : %d enrichis, %d sans correspondance", matched, missing)
    return matched
