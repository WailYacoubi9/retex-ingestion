"""
Pipeline d'ingestion des projets client intra'know.

Lit le CSV des projets, cree/enrichit les noeuds Projet dans Neo4j,
puis relie les tickets aux projets PAR TITRE.

A lancer APRES l'ingestion des tickets (pour que le lien par titre trouve
les noeuds Ticket).

Usage :
    python scripts/ingest_projets.py --input "D:\\...\\yieloo_export_projet_client_*.csv"
    python scripts/ingest_projets.py --input <csv> --skip-link   # sans relier aux tickets
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from clients import Neo4jClient
from loader_projets import (
    bootstrap_neo4j_schema,
    get_referenced_titres,
    link_projet_hierarchie,
    link_tickets_to_projets,
    write_to_neo4j,
)
from parser_projets import parse_projets


NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "retex_dev_pwd")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("ingest_projets")


def run_ingestion(input_path: Path, skip_link: bool, only_referenced: bool) -> None:
    start = time.time()

    if not input_path.exists():
        logger.error("Fichier introuvable : %s", input_path)
        sys.exit(1)

    projets = parse_projets(input_path)
    logger.info("Projets parses : %d", len(projets))
    total_parsed = len(projets)

    with Neo4jClient(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD) as neo4j:
        bootstrap_neo4j_schema(neo4j)

        if only_referenced:
            titres = get_referenced_titres(neo4j)
            if not titres:
                logger.warning(
                    "Aucun projet reference (tickets ingeres ?). Rien a ecrire."
                )
            projets = [p for p in projets if p.titre in titres]
            logger.info("Filtre 'mentionnes dans tickets' : %d projets retenus", len(projets))

        written = 0
        for i, projet in enumerate(projets, 1):
            try:
                write_to_neo4j(projet, neo4j)
                written += 1
            except Exception as e:
                logger.error("Ecriture echouee pour projet %s : %s", projet.projet_id, e)
            if i % 50 == 0:
                logger.info("[%d/%d] projets ecrits", i, len(projets))

        hierarchie = link_projet_hierarchie(neo4j)
        links = 0 if skip_link else link_tickets_to_projets(neo4j)

    duration = time.time() - start
    print("\n" + "=" * 60)
    print("RAPPORT D'INGESTION PROJETS")
    print("=" * 60)
    print(f"Duree                  : {duration:.1f} s")
    print(f"Projets parses         : {total_parsed}")
    print(f"Projets retenus        : {len(projets)}{' (filtre tickets)' if only_referenced else ''}")
    print(f"Noeuds Projet ecrits   : {written}")
    print(f"Liens SOUS_PROJET_DE   : {hierarchie}")
    print(f"Liens Ticket->Projet   : {'(ignore)' if skip_link else links}")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline d'ingestion projets intra'know")
    parser.add_argument("--input", type=Path, required=True, help="CSV des projets (latin-1, ';')")
    parser.add_argument("--skip-link", action="store_true",
                        help="Ne pas relier les tickets aux projets (par titre)")
    parser.add_argument("--only-referenced", action="store_true",
                        help="N'ingerer que les projets mentionnes par un ticket (titre reference)")
    args = parser.parse_args()

    logger.info("Demarrage ingestion projets : %s", args.input)
    run_ingestion(args.input, args.skip_link, args.only_referenced)


if __name__ == "__main__":
    main()
