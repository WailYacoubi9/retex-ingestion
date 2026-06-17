"""Test du loader sur 1 seul incident extrait + enrichi."""
import json
import logging
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clients import Neo4jClient, OllamaClient, QdrantWrapper
from extractor import extract_incident
from llm_enricher import enrich_incident
from loader import (
    bootstrap_neo4j, write_incident_to_neo4j, write_incident_to_qdrant,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

INPUT = Path("data/samples/incidents_extracted.json")

with INPUT.open(encoding="utf-8") as f:
    records = json.load(f)

# On prend le premier incident (celui avec narrative)
r = records[0]
meta = r["_extracted_meta"]
payload = r["payload"]

print(f"Testing loader on incident from {meta['postman_path']}\n")

with Neo4jClient(uri="bolt://localhost:7687", user="neo4j", password="retex_dev_pwd") as neo4j, \
     OllamaClient(url="http://localhost:11434") as ollama:

    qdrant = QdrantWrapper(url="http://localhost:6333")

    # 1. Bootstrap
    bootstrap_neo4j(neo4j)
    qdrant.ensure_collection()

    # 2. Extract
    incident = extract_incident(payload, meta["detected_type"], meta["postman_path"])
    if incident is None:
        print("EXTRACTION FAILED")
        exit(1)

    # 3. Enrich
    incident.llm = enrich_incident(ollama, incident)

    # 4. Load
    write_incident_to_neo4j(neo4j, incident)
    n_chunks = write_incident_to_qdrant(qdrant, ollama, incident)

    # 5. Verify
    inc_count = neo4j.count_incidents()
    chunk_count = qdrant.count_chunks()

    print(f"\n=== Verification ===")
    print(f"Incidents in Neo4j: {inc_count}")
    print(f"Chunks in Qdrant: {chunk_count}")
    print(f"This incident contributed {n_chunks} chunks")