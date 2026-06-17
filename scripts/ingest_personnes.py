"""
Pipeline d'ingestion des collaborateurs intra'know.

Lit data/personnes_mapping.csv (login;nom) et cree/enrichit les noeuds
Personne:Collaborateur dans Neo4j. Idempotent : relancer apres avoir
complete le mapping ne cree pas de doublon.

A lancer apres l'ingestion des tickets (pour enrichir les Personne deja
creees par EMIS_PAR / TRAITE_PAR), mais marche aussi seul.

Usage :
    python scripts/ingest_personnes.py
    python scripts/ingest_personnes.py --input data/personnes_mapping.csv
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
from loader_personnes import bootstrap_neo4j_schema, load_collaborateurs, load_mapping


DEFAULT_INPUT = PROJECT_ROOT / "data" / "personnes_mapping.csv"

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "retex_dev_pwd")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("ingest_personnes")


def run_ingestion(input_path: Path) -> None:
    start = time.time()

    if not input_path.exists():
        logger.error("Fichier introuvable : %s", input_path)
        sys.exit(1)

    mapping = load_mapping(input_path)

    with Neo4jClient(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD) as neo4j:
        bootstrap_neo4j_schema(neo4j)
        written = load_collaborateurs(neo4j, mapping)

    duration = time.time() - start
    print("\n" + "=" * 60)
    print("RAPPORT D'INGESTION COLLABORATEURS")
    print("=" * 60)
    print(f"Duree                    : {duration:.1f} s")
    print(f"Entrees mapping          : {len(mapping)}")
    print(f"Noeuds Collaborateur     : {written}")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline d'ingestion collaborateurs")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT,
                        help="CSV login;nom (defaut: data/personnes_mapping.csv)")
    args = parser.parse_args()

    logger.info("Demarrage ingestion collaborateurs : %s", args.input)
    run_ingestion(args.input)


if __name__ == "__main__":
    main()
