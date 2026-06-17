"""
2e passe : cree les liens (Ticket)-[:ENFANT_DE]->(Ticket).

Pourquoi : le loader tickets ne cree ENFANT_DE que si le parent existe DEJA
au moment du chargement (il fait un MATCH sur le parent). Quand un ticket
enfant est ingere AVANT son parent (l'ordre du JSON est arbitraire), le lien
est manque. Ce script, lance APRES l'ingestion complete, relie tous les
couples enfant/parent presents en base.

Independant du run d'ingestion : il relit le JSON source pour connaitre les
couples (numero_fe -> parent.numero_fe), puis fait un MERGE idempotent en base.

Usage :
    python scripts/link_tickets_hierarchie.py --input "C:\\...\\tickets.json"
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from clients import Neo4jClient

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "retex_dev_pwd")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("link_tickets_hierarchie")


def _fix_invalid_escapes(text: str) -> str:
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
            out.append(c); i += 1; continue
        if c != "\\":
            out.append(c); i += 1; continue
        if i + 1 >= n:
            out.append("\\\\"); i += 1; continue
        nxt = text[i + 1]
        if nxt == "u":
            if i + 5 < n and all(text[i + 2 + k] in hex_chars for k in range(4)):
                out.append(c); out.append(nxt); i += 2
            else:
                out.append("\\\\"); out.append(nxt); i += 2
            continue
        if nxt in valid_simple:
            out.append(c); out.append(nxt); i += 2
        else:
            out.append("\\\\"); out.append(nxt); i += 2
    return "".join(out)


def load_pairs(input_path: Path) -> list[dict]:
    """Extrait les couples {child, parent} (numeros_fe) depuis le JSON source."""
    raw = input_path.read_text(encoding="utf-8", errors="replace")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = json.loads(_fix_invalid_escapes(raw))

    if isinstance(data, list):
        modules = [m for m in data if isinstance(m, dict)]
    else:
        modules = data.get("_embedded", {}).get("module", [])

    pairs: list[dict] = []
    for m in modules:
        child = str(m.get("numero_fe") or "").strip()
        parent = m.get("parent")
        parent_fe = ""
        if isinstance(parent, dict):
            parent_fe = str(parent.get("numero_fe") or "").strip()
        if child and parent_fe and child != parent_fe:
            pairs.append({"child": child, "parent": parent_fe})
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(description="2e passe ENFANT_DE pour les tickets")
    parser.add_argument("--input", type=Path, required=True, help="tickets.json source")
    args = parser.parse_args()

    if not args.input.exists():
        logger.error("Fichier introuvable : %s", args.input)
        sys.exit(1)

    pairs = load_pairs(args.input)
    logger.info("Couples enfant/parent trouves dans le JSON : %d", len(pairs))

    with Neo4jClient(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD) as neo4j:
        result = neo4j.run(
            """
            UNWIND $pairs AS pair
            MATCH (c:Ticket {numero_fe: pair.child})
            MATCH (p:Ticket {numero_fe: pair.parent})
            MERGE (c)-[:ENFANT_DE]->(p)
            RETURN count(*) AS c
            """,
            pairs=pairs,
        )
        n = result[0]["c"] if result else 0

    print(f"Liens ENFANT_DE crees/confirmes : {n} (sur {len(pairs)} couples ; "
          f"les autres ont un parent absent de la base)")


if __name__ == "__main__":
    main()
