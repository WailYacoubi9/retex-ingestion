"""
Ré-enrichissement ciblé des résumés LLM pour les incidents mentionnant
les nouveaux sigles ajoutés au glossaire par Hugo (juillet 2026).

Incidents ciblés : ont déjà un resume_llm ET mentionnent au moins un des sigles
dont la définition vient d'être ajoutée au prompt (TWR, CSO, AVP, MGX, AIBT,
PCT, GPU, ZEC, GSF, QRP, SPPA).

Usage (depuis /app dans le container) :
    python3 scripts/reenrich_sigles_glossaire.py [--dry-run] [--limit N]
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from neo4j import GraphDatabase

from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, OLLAMA_URL
from clients import OllamaClient
from llm_enricher_incident_securite_v2 import enrich_incident, LLM_MODEL
from models_incident_securite_v2 import IncidentSecuriteV2Canonique

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

NEW_SIGLES = ["TWR", "CSO", "AVP", "MGX", "AIBT", "PCT", "GPU", "ZEC", "GSF", "QRP", "SPPA"]

TEXT_FIELDS = ["titre", "detail", "action_corrective", "analyse_chaud", "detail_verification"]

FIELDS_TO_FETCH = [
    "numero_fe", "titre", "detail", "action_corrective",
    "analyse_chaud", "desc_cause_1", "desc_cause_3", "desc_cause_5",
    "detail_verification",
]


def build_sigle_filter() -> str:
    conditions = []
    for sigle in NEW_SIGLES:
        field_conds = " OR ".join(
            f"(i.{f} IS NOT NULL AND i.{f} CONTAINS '{sigle}')"
            for f in TEXT_FIELDS
        )
        conditions.append(f"({field_conds})")
    return " OR ".join(conditions)


def fetch_incidents(driver, limit: int | None) -> list[dict]:
    sigle_filter = build_sigle_filter()
    cypher = f"""
    MATCH (i:IncidentSecu)
    WHERE coalesce(i.is_test_data, false) = false
      AND i.resume_llm IS NOT NULL
      AND ({sigle_filter})
    RETURN {", ".join(f"i.{f} AS {f}" for f in FIELDS_TO_FETCH)}
    ORDER BY i.numero_fe
    {"LIMIT " + str(limit) if limit else ""}
    """
    with driver.session() as sess:
        return [dict(r) for r in sess.run(cypher)]


def update_resume(driver, numero_fe: str, resume: str, model: str) -> None:
    with driver.session() as sess:
        sess.run(
            "MATCH (i:IncidentSecu {numero_fe: $fe}) SET i.resume_llm = $resume, i.llm_model = $model",
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
    ap.add_argument("--limit", type=int, default=None, help="Limite le nombre d'incidents traités")
    args = ap.parse_args()

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    logger.info("Chargement des incidents ciblés (sigles: %s)…", ", ".join(NEW_SIGLES))
    rows = fetch_incidents(driver, args.limit)
    logger.info("%d incidents à ré-enrichir", len(rows))

    if args.dry_run:
        logger.info("DRY RUN — aucune écriture Neo4j")

    n_ok = n_skip = n_fail = 0
    t0 = time.time()

    with OllamaClient(url=OLLAMA_URL) as ollama:
        for i, row in enumerate(rows, 1):
            fe = row.get("numero_fe", "?")
            inc = row_to_inc(row)
            resume = enrich_incident(ollama, inc, model=LLM_MODEL)
            if resume is None:
                n_skip += 1
                logger.debug("SKIP %s (contexte insuffisant ou rejet)", fe)
                continue

            if not args.dry_run:
                update_resume(driver, fe, resume, inc.llm_model or LLM_MODEL)
                n_ok += 1
            else:
                n_ok += 1
                logger.debug("DRY %s → %s…", fe, resume[:80])

            if i % 50 == 0:
                elapsed = time.time() - t0
                remaining = (elapsed / i) * (len(rows) - i)
                logger.info(
                    "[%d/%d] ok=%d skip=%d fail=%d — %.0fs écoulées, ~%.0fs restantes",
                    i, len(rows), n_ok, n_skip, n_fail, elapsed, remaining,
                )

    driver.close()
    elapsed = time.time() - t0
    logger.info(
        "Terminé en %.0fs — ok=%d | skip=%d | fail=%d",
        elapsed, n_ok, n_skip, n_fail,
    )


if __name__ == "__main__":
    main()
