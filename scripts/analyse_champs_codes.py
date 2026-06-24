"""Analyse les 100 payloads FNE pour reperer les champs CODES.

But : distinguer les champs dont le sens est devinable (texte libre,
referentiels avec _label, dates) de ceux qui sont des CODES NUS dont la
signification doit venir du metier (comme etape / archive_nc).
"""
import json
from collections import Counter
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "data/samples/incidents_securite.json"

with SRC.open(encoding="utf-8") as f:
    data = json.load(f)

records = data["_embedded"]["module"]
n = len(records)
print(f"Payloads analyses : {n}\n")

# Champs scalaires (hors dict/list) : candidats "code" ou "texte"
scalar_values: dict[str, list] = {}
has_label_struct: set[str] = set()   # champs referentiels (sens dans _label)

for rec in records:
    for key, val in rec.items():
        if isinstance(val, dict) and "_label" in val:
            has_label_struct.add(key)
        elif isinstance(val, list) and val and isinstance(val[0], dict) and "_label" in val[0]:
            has_label_struct.add(key)
        elif isinstance(val, (str, int, float, bool)) and not isinstance(val, bool):
            scalar_values.setdefault(key, []).append(val)
        elif isinstance(val, list) and val and isinstance(val[0], (int, str)):
            # liste de codes nus (societe, id_unite, site_application)
            scalar_values.setdefault(key + " [liste]", []).extend(val)

print("=" * 70)
print("CHAMPS SCALAIRES — cardinalite et nature")
print("=" * 70)
rows = []
for key, vals in sorted(scalar_values.items()):
    distinct = set(map(str, vals))
    card = len(distinct)
    presence = len([r for r in records if key.replace(" [liste]", "") in r])
    # heuristique : peu de valeurs distinctes + numerique/court = CODE
    sample = list(distinct)[:6]
    is_text = any(len(str(v)) > 25 for v in vals)
    if is_text:
        nature = "texte libre"
    elif card == 1:
        nature = "CONSTANTE"
    elif card <= 12:
        nature = ">>> CODE A CLARIFIER"
    else:
        nature = "identifiant / haute cardinalite"
    rows.append((key, presence, card, nature, sample))

for key, presence, card, nature, sample in rows:
    print(f"\n- {key}")
    print(f"    presence   : {presence}/{n}")
    print(f"    distinctes : {card}")
    print(f"    nature     : {nature}")
    if "CODE" in nature or "CONSTANTE" in nature:
        print(f"    valeurs    : {sorted(sample)}")

print("\n" + "=" * 70)
print("CHAMPS REFERENTIELS (sens DEJA dans _label — pas besoin du metier)")
print("=" * 70)
for key in sorted(has_label_struct):
    labels = Counter()
    for rec in records:
        v = rec.get(key)
        items = v if isinstance(v, list) else [v] if isinstance(v, dict) else []
        for it in items:
            if isinstance(it, dict) and it.get("_label"):
                labels[it["_label"]] += 1
    print(f"\n- {key}  (present {sum(1 for r in records if key in r)}/{n})")
    for lab, cnt in labels.most_common(8):
        print(f"    {cnt:>3}x  {lab}")
