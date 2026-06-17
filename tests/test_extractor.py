"""Test rapide de l'extracteur sur les 9 payloads extraits."""
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extractor import extract_incident

INPUT = Path("data/samples/incidents_extracted.json")

with INPUT.open(encoding="utf-8") as f:
    records = json.load(f)

print(f"Testing extractor on {len(records)} payloads\n")

for i, r in enumerate(records):
    meta = r["_extracted_meta"]
    payload = r["payload"]
    source_type = meta["detected_type"]
    source_ref = meta["postman_path"]

    incident = extract_incident(payload, source_type, source_ref)

    if incident is None:
        print(f"[{i}] {source_type} -> FAILED")
        continue

    print(f"[{i}] {source_type}")
    print(f"    incident_id: {incident.incident_id}")
    print(f"    titre: {incident.titre[:60] if incident.titre else 'None'}")
    print(f"    personnes: {len(incident.personnes)}")
    print(f"    referentiels: {len(incident.referentiels)}")
    print(f"    embeddable sections: {list(incident.embeddable_sections().keys())}")
    print(f"    has_narrative_content: {incident.has_narrative_content()}")
    print()