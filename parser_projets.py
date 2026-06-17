"""
Parser des projets client intra'know : CSV -> ProjetCanonique.

Specificites de l'export :
  - Encode latin-1 (pas UTF-8), separateur ';'
  - DEUX lignes d'en-tete : la 1ere = codes techniques (en-tete CSV reel),
    la 2eme ligne = libelles FR ("Identifiant", "Titre", ...). On saute
    cette ligne de libelles (detectee car [identifiant] non numerique).
"""
from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Optional

from models_projets import ProjetCanonique

logger = logging.getLogger(__name__)

# Suffixes parasites en fin de nom client (icones/emoji mangees par l'export latin-1)
TRAILING_NOISE_RE = re.compile(r"[\s?]+$")

# Cle ProjetCanonique -> en-tete de colonne CSV
COLUMN_MAP = {
    "projet_id": "[identifiant]",
    "titre": "projet_client_titre",
    "nom": "projet_client_libelle",
    "processus": "projet_processus",
    "statut": "projet_statut",
    "actif": "[actif]",
    "resp": "projet_client_lien_resp",
    "equipe": "projet_client_equipe",
    "priorite": "projet_priorite_processus",
    "date_creation": "[date_creation]",
    "date_debut": "projet_date_debut",
    "date_fin_prevue": "projet_date_fin_prevue",
    "client": "projet_client_lien_client",
    "plateforme": "projet_client_lien_plateforme",
    "projet_parent": "projet_parent",
    "temps_prevu": "projet_temps_prevu_global",
    "temps_consomme": "projet_temps_consomme",
    "lien_drive": "projet_lien_drive",
}


def _s(row: dict, col: str) -> Optional[str]:
    val = (row.get(col) or "").strip()
    return val or None


def parse_projets(csv_path: Path) -> list[ProjetCanonique]:
    """Parse le CSV des projets en liste de ProjetCanonique.

    Args:
        csv_path: Chemin vers l'export CSV (latin-1, separateur ';').

    Returns:
        Liste de ProjetCanonique. Lignes sans identifiant numerique ou
        sans titre ignorees (dont la ligne de libelles).
    """
    result: list[ProjetCanonique] = []
    skipped = 0

    with csv_path.open(encoding="latin-1", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            ident = (row.get("[identifiant]") or "").strip()
            # Saute la ligne de libelles ("Identifiant") et les lignes vides
            if not ident or not ident.isdigit():
                skipped += 1
                continue
            titre = (row.get("projet_client_titre") or "").strip()
            if not titre:
                skipped += 1
                continue

            fields = {
                key: _s(row, col)
                for key, col in COLUMN_MAP.items()
                if key not in ("projet_id", "titre")
            }
            if fields.get("client"):
                fields["client"] = TRAILING_NOISE_RE.sub("", fields["client"]).strip() or None

            result.append(ProjetCanonique(projet_id=ident, titre=titre, **fields))

    logger.info("Parse projets : %d OK, %d ignores", len(result), skipped)
    return result
