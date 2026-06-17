"""
Orchestrateur principal du pipeline d'ingestion v2.

Lit les URLs des services depuis les variables d'environnement
(NEO4J_URI, QDRANT_URL, OLLAMA_URL) avec des valeurs par defaut
adaptees au lancement local.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from clients import Neo4jClient, OllamaClient, QdrantWrapper
from extractor_v2 import extract_incident
from llm_enricher import enrich_incident
from loader_v2 import (
    bootstrap_neo4j,
    write_incident_to_neo4j,
    write_incident_to_qdrant,
)
from yaml_loader import load_mapping


DEFAULT_INPUT = Path("data/samples/incidents_securite.json")
DEFAULT_MAPPING = Path("config/extractors/q_incident_securite.yaml")

# URLs lues depuis les variables d'environnement avec fallback local
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "retex_dev_pwd")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("ingest_v2")


class IngestStats:
    """Compteurs et chronometre pour le rapport final."""

    def __init__(self) -> None:
        self.total_payloads = 0
        self.extraction_ok = 0
        self.extraction_failed = 0
        self.llm_called = 0
        self.llm_skipped = 0
        self.llm_failed = 0
        self.neo4j_written = 0
        self.qdrant_chunks = 0
        self.start_time = time.time()

    def report(self) -> str:
        duration = time.time() - self.start_time
        return "\n".join([
            "",
            "=" * 60,
            "RAPPORT D'INGESTION (v2)",
            "=" * 60,
            f"Duree totale          : {duration:.1f} s",
            f"Payloads en entree    : {self.total_payloads}",
            f"Extraction reussie    : {self.extraction_ok}",
            f"Extraction echouee    : {self.extraction_failed}",
            f"LLM appele            : {self.llm_called}",
            f"LLM ignore            : {self.llm_skipped}",
            f"LLM echoue            : {self.llm_failed}",
            f"Incidents Neo4j       : {self.neo4j_written}",
            f"Chunks Qdrant         : {self.qdrant_chunks}",
            "=" * 60,
        ])


def load_payloads(input_path: Path, embedded_key: str) -> list[dict]:
    """Charge les payloads depuis un fichier JSON HAL ou liste."""
    with input_path.open(encoding="utf-8") as f:
        raw = json.load(f)

    if isinstance(raw, dict) and "_embedded" in raw:
        embedded = raw["_embedded"]
        if isinstance(embedded, dict) and embedded_key in embedded:
            payloads = embedded[embedded_key]
            if isinstance(payloads, list):
                return [p for p in payloads if isinstance(p, dict)]

    if isinstance(raw, list):
        return [p for p in raw if isinstance(p, dict)]

    logger.error("Format de fichier non reconnu : %s", input_path)
    return []


def run_ingestion(input_path: Path, mapping_path: Path, skip_llm: bool = False) -> IngestStats:
    """Execute le pipeline complet d'ingestion."""
    stats = IngestStats()

    if not mapping_path.exists():
        logger.error("Mapping YAML introuvable : %s", mapping_path)
        sys.exit(1)

    logger.info("Chargement du mapping : %s", mapping_path)
    mapping = load_mapping(mapping_path)
    logger.info("Mapping charge pour module : %s", mapping.module_name)

    if not input_path.exists():
        logger.error("Fichier d'entree introuvable : %s", input_path)
        sys.exit(1)

    logger.info("Chargement des payloads : %s", input_path)
    payloads = load_payloads(input_path, mapping.embedded_key or "module")
    stats.total_payloads = len(payloads)
    logger.info("Payloads detectes : %d", stats.total_payloads)

    if not payloads:
        logger.error("Aucun payload a traiter, arret")
        return stats

    logger.info("Connexion services - Neo4j: %s, Qdrant: %s, Ollama: %s",
                NEO4J_URI, QDRANT_URL, OLLAMA_URL)

    with Neo4jClient(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD) as neo4j, \
         OllamaClient(url=OLLAMA_URL) as ollama:

        qdrant = QdrantWrapper(url=QDRANT_URL)

        logger.info("Bootstrap Neo4j et Qdrant")
        bootstrap_neo4j(neo4j)
        qdrant.ensure_collection()

        for i, payload in enumerate(payloads):
            _process_one_payload(
                payload, mapping, neo4j, qdrant, ollama, skip_llm,
                stats, i + 1, len(payloads),
            )

    return stats


def _process_one_payload(payload, mapping, neo4j, qdrant, ollama, skip_llm,
                          stats, index, total) -> None:
    """Traite un payload de A a Z."""
    source_id = payload.get("_id", "?")
    logger.info("[%d/%d] Traitement de l'incident %s", index, total, source_id)

    try:
        incident = extract_incident(payload, mapping)
    except Exception as e:
        logger.error("[%d/%d] Erreur extraction : %s", index, total, e)
        stats.extraction_failed += 1
        return

    if incident is None:
        stats.extraction_failed += 1
        return
    stats.extraction_ok += 1

    if not skip_llm and incident.has_narrative_content():
        try:
            enrichment = enrich_incident(ollama, incident)
            if enrichment is not None:
                incident.llm = enrichment
                stats.llm_called += 1
            else:
                stats.llm_skipped += 1
        except Exception as e:
            logger.warning("[%d/%d] LLM echoue : %s", index, total, e)
            stats.llm_failed += 1
    else:
        stats.llm_skipped += 1

    try:
        write_incident_to_neo4j(neo4j, incident)
        stats.neo4j_written += 1
    except Exception as e:
        logger.error("[%d/%d] Neo4j echoue : %s", index, total, e)
        return

    try:
        n = write_incident_to_qdrant(qdrant, ollama, incident, mapping)
        stats.qdrant_chunks += n
    except Exception as e:
        logger.error("[%d/%d] Qdrant echoue : %s", index, total, e)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline d'ingestion RETEX v2")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--skip-llm", action="store_true")
    args = parser.parse_args()

    logger.info("Demarrage du pipeline v2")
    if args.skip_llm:
        logger.info("LLM desactive (--skip-llm)")

    stats = run_ingestion(args.input, args.mapping, skip_llm=args.skip_llm)
    print(stats.report())


if __name__ == "__main__":
    main()
