"""Compare les champs presents dans incidents_extracted vs incidents_securite."""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "data/samples"

# --- Production : _embedded.module[] ---
with (BASE / "incidents_securite.json").open(encoding="utf-8") as f:
    prod = json.load(f)
prod_records = prod["_embedded"]["module"]
prod_keys = set()
for r in prod_records:
    prod_keys.update(r.keys())

# --- Extracted (Postman) : liste d'objets {_extracted_meta, payload} ---
# IMPORTANT : ce fichier melange plusieurs modules -> on filtre sur le bon type.
with (BASE / "incidents_extracted.json").open(encoding="utf-8") as f:
    extr = json.load(f)
extr_payloads = [
    item.get("payload", {})
    for item in extr
    if item.get("_extracted_meta", {}).get("detected_type") == "q_incident_securite"
]
print(f"(fiches extracted de type q_incident_securite : {len(extr_payloads)})\n")
extr_keys = set()
for p in extr_payloads:
    extr_keys.update(p.keys())

only_extr = sorted(extr_keys - prod_keys)
only_prod = sorted(prod_keys - extr_keys)
common = sorted(extr_keys & prod_keys)

print(f"Production : {len(prod_records)} fiches, {len(prod_keys)} champs distincts")
print(f"Extracted  : {len(extr_payloads)} fiches, {len(extr_keys)} champs distincts\n")

print("=" * 70)
print(f"CHAMPS DANS EXTRACTED MAIS PAS DANS PRODUCTION ({len(only_extr)})")
print("=" * 70)
# pour chaque champ, montrer un exemple de valeur et si c'est un referentiel
for k in only_extr:
    sample = None
    is_ref = False
    for p in extr_payloads:
        if k in p and p[k] not in (None, "", []):
            v = p[k]
            if isinstance(v, dict) and "_label" in v:
                sample = f"[référentiel] {v.get('_label')}"
                is_ref = True
            elif isinstance(v, list) and v and isinstance(v[0], dict) and "_label" in v[0]:
                sample = f"[liste référentiel] {v[0].get('_label')}"
                is_ref = True
            else:
                sample = repr(v)[:60]
            break
    print(f"  {k:<45} {sample}")

print("\n" + "=" * 70)
print(f"CHAMPS COMMUNS ({len(common)})")
print("=" * 70)
print("  " + ", ".join(common))

print("\n" + "=" * 70)
print(f"CHAMPS DANS PRODUCTION MAIS PAS DANS EXTRACTED ({len(only_prod)})")
print("=" * 70)
print("  " + ", ".join(only_prod))
