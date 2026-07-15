"""
Enrichissement LLM des incidents qui étaient skippés (MIN_CONTEXT trop élevé).

Cible les incidents avec resume_skip dont le contexte brut est entre 100 et 149
caractères — seuil abaissé à 100 le 13/07/2026 (fiches courtes mais avec titre
+ detail suffisants pour une phrase fidèle).

Usage (depuis /app dans le container) :
    python3 scripts/enrich_resumes_skip.py [--dry-run] [--limit N] [--min 100] [--max 149]
"""
from __future__ import annotations

import argparse
import logging
import time

from neo4j import GraphDatabase

from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, OLLAMA_URL
from clients import OllamaClient
from llm_enricher_incident_securite_v2 import enrich_incident, LLM_MODEL, MIN_CONTEXT
from models_incident_securite_v2 import IncidentSecuriteV2Canonique

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

FIELDS_TO_FETCH = [
    "numero_fe", "titre", "detail", "action_corrective",
    "analyse_chaud", "desc_cause_1", "desc_cause_3", "desc_cause_5",
    "detail_verification",
]

CTX_EXPR = (
    "coalesce(i.detail, '') + coalesce(i.analyse_chaud, '') + "
    "coalesce(i.action_corrective, '') + coalesce(i.detail_verification, '') + "
    "coalesce(i.desc_cause_1, '') + coalesce(i.desc_cause_3, '') + coalesce(i.desc_cause_5, '')"
)


def fetch_incidents(driver, min_len: int, max_len: int, limit: int | None) -> list[dict]:
    cypher = f"""
    MATCH (i:IncidentSecu)
    WHERE coalesce(i.is_test_data, false) = false AND i.resume_skip IS NOT NULL
    WITH i, size({CTX_EXPR}) AS ctx_len
    WHERE ctx_len >= {min_len} AND ctx_len <= {max_len}
    RETURN {", ".join(f"i.{f} AS {f}" for f in FIELDS_TO_FETCH)}, ctx_len
    ORDER BY i.numero_fe
    {"LIMIT " + str(limit) if limit else ""}
    """
    with driver.session() as sess:
        return [dict(r) for r in sess.run(cypher)]


def update_neo4j(driver, numero_fe: str, resume: str, model: str) -> None:
    with driver.session() as sess:
        sess.run(
            """
            MATCH (i:IncidentSecu {numero_fe: $fe})
            SET i.resume_llm = $resume, i.llm_model = $model
            REMOVE i.resume_skip
            """,
            fe=numero_fe, resume=resume, model=model,
        )


def row_to_inc(row: dict) -> IncidentSecuriteV2Canonique:
    return IncidentSecuriteV2Canonique(
        numero_fe=row.get("numero_fe"),
        titre=row.get("titre"),
        detail=row.get("detail"),
        action_corrective=row.get("action_corrective"),
        analyse_chaud=row.get("analyse_chaud"),
        desc_cause_1=row.get("desc_cause_1"),
        desc_cause_3=row.get("desc_cause_3"),
        desc_cause_5=row.get("desc_cause_5"),
        detail_verification=row.get("detail_verification"),
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="N'écrit rien dans Neo4j")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--min", type=int, default=MIN_CONTEXT, dest="min_len",
                    help=f"Longueur minimale du contexte (défaut: {MIN_CONTEXT})")
    ap.add_argument("--max", type=int, default=149, dest="max_len",
                    help="Longueur maximale du contexte (défaut: 149)")
    args = ap.parse_args()

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    logger.info("Chargement des incidents skippés avec contexte %d-%d chars…",
                args.min_len, args.max_len)
    rows = fetch_incidents(driver, args.min_len, args.max_len, args.limit)
    logger.info("%d incidents à traiter", len(rows))

    if args.dry_run:
        logger.info("DRY RUN — aucune écriture Neo4j")

    n_ok = n_skip = n_fail = 0
    t0 = time.time()

    with OllamaClient(url=OLLAMA_URL) as ollama:
        for idx, row in enumerate(rows, 1):
            fe = row.get("numero_fe", "?")
            inc = row_to_inc(row)
            resume = enrich_incident(ollama, inc, model=LLM_MODEL)

            if resume is None:
                n_skip += 1
                logger.debug("SKIP %s (contexte insuffisant ou rejet LLM)", fe)
                continue

            if not args.dry_run:
                update_neo4j(driver, fe, resume, inc.llm_model or LLM_MODEL)

            n_ok += 1
            if args.dry_run:
                logger.debug("DRY %s [%d chars] → %s…", fe, row.get("ctx_len", 0), resume[:80])

            if idx % 50 == 0:
                elapsed = time.time() - t0
                remaining = (elapsed / idx) * (len(rows) - idx)
                logger.info(
                    "[%d/%d] ok=%d skip=%d — %.0fs écoulées, ~%.0fs restantes",
                    idx, len(rows), n_ok, n_skip, elapsed, remaining,
                )

    driver.close()
    elapsed = time.time() - t0
    logger.info("Terminé en %.0fs — ok=%d | skip=%d | fail=%d", elapsed, n_ok, n_skip, n_fail)


if __name__ == "__main__":
    main()
