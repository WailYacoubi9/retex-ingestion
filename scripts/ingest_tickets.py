"""
Pipeline d'ingestion des tickets intra'know.

Lit tickets.json, parse chaque ticket, enrichit via LLM,
ecrit dans Neo4j + Qdrant.

Usage :
    python scripts/ingest_tickets.py
    python scripts/ingest_tickets.py --input data/samples/tickets.json
    python scripts/ingest_tickets.py --skip-llm
    python scripts/ingest_tickets.py --limit 100
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from clients import Neo4jClient, OllamaClient, QdrantWrapper
from enrich_tickets_csv import build_csv_index, enrich_raw_tickets
from llm_enricher_tickets import enrich_ticket
from loader_tickets import (
    bootstrap_neo4j_schema,
    get_enriched_ticket_ids,
    link_tickets_hierarchie,
    load_one,
)
from parser_tickets import parse_tickets


DEFAULT_INPUT = Path("data/samples/tickets.json")

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "retex_dev_pwd")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
# Timeout HTTP Ollama (s). qwen2.5:14b partiellement sur CPU peut depasser
# largement 120 s par ticket -> on monte a 600 s par defaut.
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "600"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("ingest_tickets")


class IngestStats:
    def __init__(self) -> None:
        self.total = 0
        self.parsed_ok = 0
        self.parsed_failed = 0
        self.llm_ok = 0
        self.llm_skipped = 0
        self.llm_failed = 0
        self.neo4j_ok = 0
        self.qdrant_chunks = 0
        self.start_time = time.time()

    def report(self) -> str:
        duration = time.time() - self.start_time
        return "\n".join([
            "",
            "=" * 60,
            "RAPPORT D'INGESTION TICKETS",
            "=" * 60,
            f"Duree totale          : {duration:.1f} s",
            f"Payloads en entree    : {self.total}",
            f"Parsing reussi        : {self.parsed_ok}",
            f"Parsing echoue        : {self.parsed_failed}",
            f"LLM appele            : {self.llm_ok}",
            f"LLM ignore (contenu)  : {self.llm_skipped}",
            f"LLM echoue            : {self.llm_failed}",
            f"Tickets Neo4j ecrits  : {self.neo4j_ok}",
            f"Chunks Qdrant         : {self.qdrant_chunks}",
            "=" * 60,
        ])


def _fix_invalid_escapes(text: str) -> str:
    """Repare les sequences d'echappement invalides dans le JSON source."""
    out: list[str] = []
    i = 0
    in_string = False
    valid_simple = set('"\\/bfnrtu')
    hex_chars = set("0123456789abcdefABCDEF")
    n = len(text)
    while i < n:
        c = text[i]
        if not in_string:
            out.append(c)
            if c == '"':
                in_string = True
            i += 1
            continue
        if c == '"':
            in_string = False
            out.append(c)
            i += 1
            continue
        if c != "\\":
            out.append(c)
            i += 1
            continue
        if i + 1 >= n:
            out.append("\\\\")
            i += 1
            continue
        nxt = text[i + 1]
        if nxt == "u":
            if i + 5 < n and all(text[i + 2 + k] in hex_chars for k in range(4)):
                out.append(c)
                out.append(nxt)
                i += 2
            else:
                out.append("\\\\")
                out.append(nxt)
                i += 2
            continue
        if nxt in valid_simple:
            out.append(c)
            out.append(nxt)
            i += 2
        else:
            out.append("\\\\")
            out.append(nxt)
            i += 2
    return "".join(out)


def load_raw_tickets(input_path: Path) -> list[dict]:
    """Charge les payloads bruts depuis tickets.json."""
    raw = input_path.read_text(encoding="utf-8", errors="replace")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.info("JSON invalide, tentative de reparation des escapes...")
        data = json.loads(_fix_invalid_escapes(raw))

    if isinstance(data, list):
        return [p for p in data if isinstance(p, dict)]

    embedded = data.get("_embedded", {})
    module = embedded.get("module", [])
    if isinstance(module, list):
        return [p for p in module if isinstance(p, dict)]

    logger.error("Format de fichier non reconnu : %s", input_path)
    return []


def run_ingestion(input_path: Path, skip_llm: bool, limit: int, csv_path: Path | None,
                  skip_existing: bool, offset: int = 0) -> IngestStats:
    stats = IngestStats()

    if not input_path.exists():
        logger.error("Fichier introuvable : %s", input_path)
        sys.exit(1)

    raw_list = load_raw_tickets(input_path)
    if offset > 0:
        raw_list = raw_list[offset:]
    if limit > 0:
        raw_list = raw_list[:limit]
    stats.total = len(raw_list)
    logger.info("Payloads charges : %d", stats.total)

    if csv_path is not None:
        if not csv_path.exists():
            logger.error("CSV introuvable : %s", csv_path)
            sys.exit(1)
        csv_index = build_csv_index(csv_path)
        enrich_raw_tickets(raw_list, csv_index)

    tickets = parse_tickets(raw_list)
    stats.parsed_ok = len(tickets)
    stats.parsed_failed = stats.total - stats.parsed_ok
    logger.info("Parsing : %d OK, %d echecs", stats.parsed_ok, stats.parsed_failed)

    with Neo4jClient(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD) as neo4j, \
         OllamaClient(url=OLLAMA_URL, timeout=OLLAMA_TIMEOUT) as ollama:

        qdrant = QdrantWrapper(url=QDRANT_URL)
        qdrant.ensure_collection()
        bootstrap_neo4j_schema(neo4j)

        if skip_existing:
            done = get_enriched_ticket_ids(neo4j)
            avant = len(tickets)
            tickets = [t for t in tickets if t.ticket_id not in done]
            stats.llm_skipped += avant - len(tickets)
            logger.info(
                "Reprise : %d deja enrichis ignores, %d a traiter",
                avant - len(tickets), len(tickets),
            )

        a_traiter = len(tickets)
        for i, ticket in enumerate(tickets, 1):
            logger.info("[%d/%d] Ticket %s", i, a_traiter, ticket.numero_fe)

            if not skip_llm and ticket.has_narrative_content():
                try:
                    before = ticket.llm
                    enrich_ticket(ticket, ollama)
                    if ticket.llm is not None:
                        stats.llm_ok += 1
                    else:
                        stats.llm_failed += 1
                except Exception as e:
                    logger.warning("LLM echoue pour %s : %s", ticket.numero_fe, e)
                    stats.llm_failed += 1
            else:
                stats.llm_skipped += 1

            try:
                n = load_one(ticket, neo4j, qdrant, ollama)
                stats.neo4j_ok += 1
                stats.qdrant_chunks += n
            except Exception as e:
                logger.error("Ecriture echouee pour %s : %s", ticket.numero_fe, e)

        # 2e passe : relie chaque ticket a son parent (corrige les liens manques
        # quand l'enfant est ingere avant son parent)
        link_tickets_hierarchie(neo4j)

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline d'ingestion tickets intra'know")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--csv", type=Path, default=None,
                        help="Export CSV pour enrichir projet_nom/structure/urgence/individu (jointure sur numero_fe)")
    parser.add_argument("--skip-llm", action="store_true", help="Desactive l'enrichissement LLM")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Reprise : ignore les tickets deja enrichis (llm_resume present)")
    parser.add_argument("--limit", type=int, default=0, help="Limite le nombre de tickets (0 = tous)")
    parser.add_argument("--offset", type=int, default=0, help="Ignore les N premiers tickets (pour traiter un autre lot)")
    args = parser.parse_args()

    logger.info("Demarrage ingestion tickets : %s", args.input)
    stats = run_ingestion(args.input, args.skip_llm, args.limit, args.csv, args.skip_existing, args.offset)
    print(stats.report())


if __name__ == "__main__":
    main()
