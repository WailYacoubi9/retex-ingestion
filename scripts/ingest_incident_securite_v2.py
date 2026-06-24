"""
Ingestion — Incident Sécurité v2 (export plateforme à plat).

Pipeline PARALLÈLE à ingest_incidents.py (HAL). Lit l'export "présentation"
(liste JSON, libellés FR), extrait via le mapping YAML, écrit Neo4j + Qdrant.

Usage :
    python scripts/ingest_incident_securite_v2.py --input data/samples/incidents_securites.json
    python scripts/ingest_incident_securite_v2.py --input <fichier> --limit 50
    python scripts/ingest_incident_securite_v2.py --input <fichier> --dry-run
    python scripts/ingest_incident_securite_v2.py --input <fichier> --no-embedding
    python scripts/ingest_incident_securite_v2.py --input <fichier> --with-llm
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, QDRANT_URL, OLLAMA_URL
from clients import Neo4jClient, OllamaClient, QdrantWrapper
from extractor_incident_securite_v2 import charger_schema, extraire, verifier_coherence
from loader_incident_securite_v2 import (
    bootstrap_neo4j,
    write_incident_to_neo4j,
    write_incident_to_qdrant,
)
from llm_enricher_incident_securite_v2 import enrich_incident

DEFAULT_INPUT = Path("data/samples/incidents_securites.json")
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "schemas" / "incident_securite_v2.schema.yaml"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ingest_incident_secu_v2")


def _charger_payloads(path: Path) -> list[dict]:
    """Charge l'export : liste plate, ou enveloppe _embedded en secours."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    module = data.get("_embedded", {}).get("module", [])
    return [d for d in module if isinstance(d, dict)]


def run(input_path: Path, config_path: Path, limit: int, offset: int,
        dry_run: bool, embedding: bool, llm: bool = False) -> int:
    if not input_path.exists():
        logger.error("Fichier introuvable : %s", input_path)
        return 1

    schema = charger_schema(config_path)
    verifier_coherence(schema)            # stoppe net si modèle pas régénéré
    payloads = _charger_payloads(input_path)
    if offset:
        payloads = payloads[offset:]
    if limit:
        payloads = payloads[:limit]

    logger.info("Fiches à traiter : %d", len(payloads))
    logger.info("Neo4j=%s  Qdrant=%s  embedding=%s  llm=%s  dry_run=%s",
                NEO4J_URI, QDRANT_URL, embedding, llm, dry_run)

    n_ok = n_skip = n_fail = n_chunks = 0
    t0 = time.time()

    if dry_run:
        for p in payloads:
            inc = extraire(p, schema)
            if inc is None:
                n_skip += 1
            else:
                n_ok += 1
        logger.info("DRY RUN — extractibles: %d, ignorées: %d", n_ok, n_skip)
        return 0

    with Neo4jClient(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD) as neo4j, \
         OllamaClient(url=OLLAMA_URL) as ollama:

        qdrant = QdrantWrapper(url=QDRANT_URL)
        bootstrap_neo4j(neo4j)
        if embedding:
            qdrant.ensure_collection()

        for i, p in enumerate(payloads, 1):
            inc = extraire(p, schema)
            if inc is None:
                n_skip += 1
                continue
            try:
                if llm:
                    enrich_incident(ollama, inc)
                write_incident_to_neo4j(neo4j, inc)
                if embedding:
                    n_chunks += write_incident_to_qdrant(inc, qdrant, ollama)
                n_ok += 1
                if i % 200 == 0:
                    logger.info("  ... %d/%d", i, len(payloads))
            except Exception as e:
                logger.error("Échec %s : %s", inc.numero_fe, e)
                n_fail += 1

    dt = time.time() - t0
    logger.info("===== Récapitulatif =====")
    logger.info("OK: %d | ignorées: %d | échecs: %d", n_ok, n_skip, n_fail)
    logger.info("Chunks Qdrant: %d | Durée: %.1fs", n_chunks, dt)
    return 0 if n_fail == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingestion Incident Sécurité v2 (export plateforme)")
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--limit", type=int, default=0, help="0 = tous")
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true", help="extrait sans écrire")
    ap.add_argument("--no-embedding", action="store_true",
                    help="n'écrit pas dans Qdrant (test rapide sans GPU)")
    ap.add_argument("--with-llm", action="store_true",
                    help="enrichit chaque incident avec un résumé LLM (llama3.1:8b)")
    args = ap.parse_args()
    return run(args.input, args.config, args.limit, args.offset,
               args.dry_run, embedding=not args.no_embedding, llm=args.with_llm)


if __name__ == "__main__":
    sys.exit(main())
