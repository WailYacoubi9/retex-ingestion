"""
Script de test rapide du parser DGAC sur une IS donnee.

Lance le parser sur un fichier .md, affiche le contenu structure du
dataclass produit pour validation visuelle. Utile pour iterer sur la
logique de parsing sans lancer l'orchestrateur complet.

Usage :
    python scripts/test_parser_dgac.py is_2024_01.md
    python scripts/test_parser_dgac.py is_2023_02.md
    python scripts/test_parser_dgac.py is_2022_02.md
"""
from __future__ import annotations

import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from parser_dgac import parse_markdown_to_canonique


logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")


def main() -> int:
    """Parse un .md et affiche son contenu structure pour validation.

    Utilisation : recoit le nom du fichier en argument (ex is_2024_01.md),
    cherche dans data/samples/dgac_parsed/, parse, affiche le resultat.
    """
    if len(sys.argv) < 2:
        print("Usage : python scripts/test_parser_dgac.py <nom_fichier.md>")
        return 1

    fichier_nom = sys.argv[1]
    md_path = PROJECT_ROOT / "data" / "samples" / "dgac_parsed" / fichier_nom

    if not md_path.exists():
        print(f"Fichier introuvable : {md_path}")
        return 1

    print(f"Parsing : {md_path.name}\n")
    canonique = parse_markdown_to_canonique(md_path)

    # Affichage structure
    print("===== Identification =====")
    print(f"is_number          : {canonique.is_number}")
    print(f"annee              : {canonique.annee}")
    print(f"info_securite_id   : {canonique.info_securite_id}")
    print(f"source_module      : {canonique.source_module}")
    print(f"titre              : {canonique.titre}")

    print("\n===== Metadonnees =====")
    print(f"operateurs_concernes ({len(canonique.operateurs_concernes)}) :")
    for op in canonique.operateurs_concernes:
        print(f"  - {op}")
    print(f"sujet              : {canonique.sujet}")
    print(f"objectif           : {canonique.objectif}")

    print("\n===== Contenu principal =====")
    print(f"contexte ({len(canonique.contexte or '')} chars) :")
    print(_preview(canonique.contexte, 500))
    print(f"\nactions_recommandees ({len(canonique.actions_recommandees or '')} chars) :")
    print(_preview(canonique.actions_recommandees, 500))

    print("\n===== Champs optionnels du tableau =====")
    print(f"annexe ({len(canonique.annexe or '')} chars) :")
    print(_preview(canonique.annexe, 300))
    print(f"\nreferences ({len(canonique.references or '')} chars) :")
    print(_preview(canonique.references, 300))

    print("\n===== Contenu hors tableau =====")
    if canonique.contenu_hors_tableau:
        print(f"contenu_hors_tableau ({len(canonique.contenu_hors_tableau)} chars) :")
        print(_preview(canonique.contenu_hors_tableau, 500))
    else:
        print("(rien)")

    print("\n===== Versionnement =====")
    print(f"version_numero     : {canonique.version_numero}")
    print(f"date_version       : {canonique.date_version}")

    print("\n===== Relations =====")
    print(f"remplace           : {canonique.remplace}")

    print("\n===== Extra fields =====")
    if canonique.extra_fields:
        for key, value in canonique.extra_fields.items():
            print(f"  {key} ({len(value)} chars) :")
            print(_preview(value, 300))
            print()
    else:
        print("(aucun)")

    return 0


def _preview(text: str | None, max_chars: int) -> str:
    """Tronque un texte pour affichage console avec ellipsis.

    Utilisation : evite que l'affichage soit pollue par un Contexte
    de 5000 caracteres.
    """
    if not text:
        return "(vide)"
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "...\n[tronque]"


if __name__ == "__main__":
    sys.exit(main())