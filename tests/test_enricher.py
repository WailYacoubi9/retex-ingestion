"""Test rapide de l'enrichisseur LLM sur les 9 payloads."""
import json
import logging
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import OLLAMA_URL
from clients import OllamaClient
from extractor import extract_incident
from llm_enricher import enrich_incident

# Logs visibles pour voir ce qui se passe
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

INPUT = Path("data/samples/incidents_extracted.json")

with INPUT.open(encoding="utf-8") as f:
    records = json.load(f)

print(f"Testing enricher on {len(records)} payloads\n")

with OllamaClient(url=OLLAMA_URL) as ollama:
    for i, r in enumerate(records):
        meta = r["_extracted_meta"]
        payload = r["payload"]

        incident = extract_incident(payload, meta["detected_type"], meta["postman_path"])
        if incident is None:
            print(f"[{i}] EXTRACTION FAILED\n")
            continue

        enrichment = enrich_incident(ollama, incident)

        print(f"[{i}] {incident.source_type}")
        if enrichment is None:
            print(f"    skipped (no narrative content)\n")
        else:
            print(f"    resume: {enrichment.resume}")
            print(f"    facteur_causal: {enrichment.facteur_causal}")
            print(f"    severite_percue: {enrichment.severite_percue}")
            print(f"    etat_final: {enrichment.etat_final}")
            print()