"""
Orchestrateur d'ingestion DGAC : JSON canonique -> Neo4j + Qdrant.

Lit les 53 JSON dans data/samples/dgac_canonique/, ecrit chaque IS
dans Neo4j (noeud :InfoSecurite + relations :REMPLACE) et Qdrant
(chunks vectorises par champ).

Idempotent grace au MERGE Neo4j et a l'upsert Qdrant.

Usage :
    python scripts/ingest_dgac.py
    python scripts/ingest_dgac.py --limit 5
    python scripts/ingest_dgac.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from clients import Neo4jClient, OllamaClient, QdrantWrapper
from loader_info_securite import (
    bootstrap_neo4j_schema,
    load_one,
)
from models_info_securite import (
    InfoSecuriteCanonique,
    LLMResumeOperateur,
)


JSON_DIR = PROJECT_ROOT / "data" / "samples" / "dgac_canonique"

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "retex_dev_pwd")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ingest_dgac")


def _load_canonique_from_json(json_path: Path) -> InfoSecuriteCanonique:
    """Reconstitue un InfoSecuriteCanonique depuis le JSON serialise."""
    data: dict[str, Any] = json.loads(json_path.read_text(encoding="utf-8"))
    date_str = data.get("date_version")
    if date_str:
        data["date_version"] = date.fromisoformat(date_str)
    if data.get("llm"):
        data["llm"] = LLMResumeOperateur(**data["llm"])
    return InfoSecuriteCanonique(**data)


def run_ingest(limit: int | None, dry_run: bool) -> int:
    """Charge les JSON DGAC dans Neo4j et Qdrant."""
    if not JSON_DIR.exists():
        logger.error("Repertoire absent : %s", JSON_DIR)
        return 1

    json_files = sorted(JSON_DIR.glob("is_*.json"))
    if not json_files:
        logger.error("Aucun JSON dans %s", JSON_DIR)
        return 1

    if limit:
        json_files = json_files[:limit]
        logger.info("Mode limite : %d premieres IS seulement", limit)

    logger.info("IS a ingerer : %d", len(json_files))
    logger.info("Neo4j  : %s", NEO4J_URI)
    logger.info("Qdrant : %s", QDRANT_URL)
    logger.info("Ollama : %s", OLLAMA_URL)
    if dry_run:
        logger.info("DRY RUN : aucune ecriture effectuee")

    n_ok = 0
    n_failed = 0
    n_total_chunks = 0
    t_start = time.time()

    with Neo4jClient(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD) as neo4j, \
         OllamaClient(url=OLLAMA_URL) as ollama:

        qdrant = QdrantWrapper(url=QDRANT_URL)

        if not dry_run:
            bootstrap_neo4j_schema(neo4j)
            qdrant.ensure_collection()

        for i, json_path in enumerate(json_files, start=1):
            try:
                canonique = _load_canonique_from_json(json_path)
            except Exception as e:
                logger.error("[%d/%d] %s : erreur chargement JSON : %s",
                             i, len(json_files), json_path.name, e)
                n_failed += 1
                continue

            if dry_run:
                logger.info("[%d/%d] %s : DRY RUN, pas d'ecriture",
                            i, len(json_files), canonique.is_number)
                n_ok += 1
                continue

            t0 = time.time()
            try:
                n_chunks = load_one(canonique, neo4j, qdrant, ollama)
            except Exception as e:
                logger.error("[%d/%d] %s : erreur ingestion : %s",
                             i, len(json_files), canonique.is_number, e)
                n_failed += 1
                continue

            duration = time.time() - t0
            n_total_chunks += n_chunks
            n_ok += 1
            logger.info("[%d/%d] %s : OK (%d chunks Qdrant, %.1fs)",
                        i, len(json_files), canonique.is_number, n_chunks, duration)

    t_total = time.time() - t_start
    logger.info("")
    logger.info("===== Recapitulatif =====")
    logger.info("IS traitees       : %d", len(json_files))
    logger.info("Succes            : %d", n_ok)
    logger.info("Echecs            : %d", n_failed)
    logger.info("Chunks Qdrant     : %d", n_total_chunks)
    logger.info("Temps total       : %.1fs (%.1f min)", t_total, t_total / 60)
    return 0 if n_failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingestion DGAC dans Neo4j + Qdrant")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limite le nombre d'IS traitees")
    parser.add_argument("--dry-run", action="store_true",
                        help="N'ecrit rien, valide juste le chargement des JSON")
    args = parser.parse_args()
    return run_ingest(limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())