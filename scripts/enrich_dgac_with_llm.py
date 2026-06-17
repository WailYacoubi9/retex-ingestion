"""
Batch : enrichit les 53 IS DGAC avec un resume LLM (point de vue operateur).

Lit chaque JSON dans data/samples/dgac_canonique/, applique
enrich_with_resume_operateur via Ollama, et ecrit le JSON enrichi
(ecrase l'original car le champ llm est ajoute en place).

Idempotent : si le JSON contient deja un llm non-null, on skip
(sauf si --force).

Usage :
    python scripts/enrich_dgac_with_llm.py
    python scripts/enrich_dgac_with_llm.py --force   # re-enrichit meme si llm deja present
    python scripts/enrich_dgac_with_llm.py --limit 5 # ne traite que les 5 premiers (debug)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from clients import OllamaClient
from llm_enricher_info_securite import enrich_with_resume_operateur
from models_info_securite import (
    InfoSecuriteCanonique,
    LLMResumeOperateur,
)


JSON_DIR = PROJECT_ROOT / "data" / "samples" / "dgac_canonique"
OLLAMA_URL = "http://localhost:11434"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("enrich_dgac")


def _load_canonique_from_json(json_path: Path) -> InfoSecuriteCanonique:
    """Reconstitue un InfoSecuriteCanonique depuis le JSON serialise.

    Utilisation : meme logique que scripts/test_enricher_dgac.py.
    Reparse la date_version (str ISO -> date) et le sous-objet llm si present.
    """
    data: dict[str, Any] = json.loads(json_path.read_text(encoding="utf-8"))
    date_str = data.get("date_version")
    if date_str:
        data["date_version"] = date.fromisoformat(date_str)
    if data.get("llm"):
        data["llm"] = LLMResumeOperateur(**data["llm"])
    return InfoSecuriteCanonique(**data)


def _json_default(obj: Any) -> Any:
    """Serializer JSON pour les types non natifs."""
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, set):
        return sorted(obj)
    raise TypeError(f"Type non serialisable : {type(obj)}")


def _save_canonique_to_json(canonique: InfoSecuriteCanonique, json_path: Path) -> None:
    """Reserialise le dataclass enrichi dans son JSON."""
    payload = asdict(canonique)
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )


def run_batch(force: bool, limit: int | None) -> int:
    """Orchestre l'enrichissement LLM de toutes les IS.

    Utilisation : point d'entree principal. Itere sur les JSON, appelle
    enrich_with_resume_operateur pour chacun, sauve le JSON enrichi.
    """
    if not JSON_DIR.exists():
        logger.error("Repertoire absent : %s", JSON_DIR)
        return 1

    json_files = sorted(JSON_DIR.glob("is_*.json"))
    if not json_files:
        logger.error("Aucun JSON trouve dans %s", JSON_DIR)
        return 1

    if limit:
        json_files = json_files[:limit]
        logger.info("Mode limite : traitement des %d premiers seulement", limit)

    logger.info("IS a traiter : %d", len(json_files))

    n_skipped = 0
    n_enriched = 0
    n_failed = 0
    durations: list[float] = []
    t_start = time.time()

    with OllamaClient(url=OLLAMA_URL) as ollama:
        for i, json_path in enumerate(json_files, start=1):
            canonique = _load_canonique_from_json(json_path)

            # Skip si deja enrichi
            if canonique.llm is not None and not force:
                logger.info(
                    "[%d/%d] %s : deja enrichi, skip",
                    i, len(json_files), canonique.is_number,
                )
                n_skipped += 1
                continue

            t0 = time.time()
            canonique = enrich_with_resume_operateur(canonique, ollama)
            duration = time.time() - t0
            durations.append(duration)

            if canonique.llm is None:
                logger.warning(
                    "[%d/%d] %s : echec enrichissement",
                    i, len(json_files), canonique.is_number,
                )
                n_failed += 1
                continue

            _save_canonique_to_json(canonique, json_path)
            n_enriched += 1
            logger.info(
                "[%d/%d] %s : OK en %.1fs (resume %d chars)",
                i, len(json_files), canonique.is_number,
                duration, len(canonique.llm.resume),
            )

    t_total = time.time() - t_start
    logger.info("")
    logger.info("===== Recapitulatif =====")
    logger.info("IS traitees       : %d", len(json_files))
    logger.info("Enrichies (nouv.) : %d", n_enriched)
    logger.info("Deja enrichies    : %d", n_skipped)
    logger.info("Echecs            : %d", n_failed)
    logger.info("Temps total       : %.1fs (%.1f min)", t_total, t_total / 60)
    if durations:
        moyenne = sum(durations) / len(durations)
        logger.info("Duree moyenne     : %.1fs / IS", moyenne)
    logger.info("Sortie            : %s", JSON_DIR)
    return 0 if n_failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enrichit les JSON DGAC avec un resume LLM."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reecrase les resumes existants",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limite le nombre d'IS traitees (debug)",
    )
    args = parser.parse_args()
    return run_batch(force=args.force, limit=args.limit)


if __name__ == "__main__":
    sys.exit(main())