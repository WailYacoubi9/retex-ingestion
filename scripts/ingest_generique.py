"""
Driver d'ingestion GÉNÉRIQUE — piloté ENTIÈREMENT par le schéma YAML.

Aucun label, aucune relation, aucun modèle codé en dur : tout est lu du schéma
(`module.label_noeud`, et pour chaque champ `role: relation` ses `noeud` /
`cle_noeud` / `relation`). Déposer un nouveau YAML conforme suffit — le nœud,
ses propriétés et ses relations (avec leurs noms) sont dérivés automatiquement.

Réutilise le convertisseur CSV→lignes (mêmes cp1252 + déduplication de headers).

Usage :
  python scripts/ingest_generique.py \
      --schema config/schemas/incident_securite_v3.schema.yaml \
      --csv data/samples/<export>.csv --dry-run
  (--write pour écrire réellement dans Neo4j ; sinon dry-run par défaut.)
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from csv_actions_to_json import _dedup_headers, CSV_ENCODING, CSV_DELIMITER, _is_action_col

_VIDES = {"", "0", "n/a", "na", "sans objet"}
_VRAI = {"oui", "true", "vrai", "1"}


def _clean(v):
    return (v or "").strip()


def charger_schema(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def lire_lignes(csv_path: Path) -> tuple[list[str], list[dict]]:
    with open(csv_path, encoding=CSV_ENCODING, newline="") as f:
        raw = csv.reader(f, delimiter=CSV_DELIMITER)
        cols = _dedup_headers(next(raw))
        lignes = [dict(zip(cols, r + [""] * (len(cols) - len(r)))) for r in raw]
    return cols, lignes


def transformer(schema: dict, lignes: list[dict]) -> tuple[str, list[dict]]:
    """Applique le schéma aux lignes → (label_noeud, liste d'incidents dérivés)."""
    label = schema["module"]["label_noeud"]
    id_label = schema["module"]["cle_identite_label"]
    champs = schema["champs"]

    # dédup incident par identité (une ligne par action → 1er = incident)
    par_id: dict[str, dict] = {}
    for row in lignes:
        ident = _clean(row.get(id_label))
        if ident and ident not in par_id:
            par_id[ident] = row

    incidents = []
    for ident, row in par_id.items():
        props, relations = {}, []
        for c in champs:
            role = c.get("role")
            val = _clean(row.get(c["label"]))
            if role == "relation":
                if val.lower() not in _VIDES:
                    relations.append({"noeud": c["noeud"], "cle_noeud": c["cle_noeud"],
                                      "relation": c["relation"], "valeur": val})
            else:  # propriete | date | flag
                if c.get("filtre_vide") and val.lower() in _VIDES:
                    continue
                if role == "flag":
                    props[c["cle"]] = val.lower() in _VRAI
                elif val:
                    props[c["cle"]] = val
        incidents.append({"id": re.sub(r"\s+", "", ident), "label": label,
                          "props": props, "relations": relations})
    return label, incidents


def cypher_incident(label: str, inc: dict) -> list[str]:
    """Cypher générique dérivé du schéma (démonstration)."""
    out = [f"MERGE (i:{label} {{id: '{inc['id']}'}}) SET i += {{...{len(inc['props'])} props...}}"]
    for r in inc["relations"]:
        out.append(f"MERGE (n:{r['noeud']} {{{r['cle_noeud']}: '{r['valeur'][:24]}'}}) "
                   f"MERGE (i)-[:{r['relation']}]->(n)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema", type=Path, required=True)
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--write", action="store_true", help="écrit réellement dans Neo4j")
    args = ap.parse_args()

    schema = charger_schema(args.schema)
    _, lignes = lire_lignes(args.csv)
    label, incidents = transformer(schema, lignes)

    print(f"Schéma        : {args.schema.name}")
    print(f"label_noeud   : {label}   (lu du schéma, PAS codé en dur)")
    print(f"Incidents     : {len(incidents)}  (dédupliqués par « {schema['module']['cle_identite_label']} »)")

    # histogramme des relations produites (nom de relation -> nb d'arêtes)
    rels = Counter(r["relation"] for inc in incidents for r in inc["relations"])
    cibles = {r["relation"]: r["noeud"] for inc in incidents for r in inc["relations"]}
    print(f"\nRELATIONS dérivées du YAML ({len(rels)} types, toutes automatiques) :")
    for rel, n in rels.most_common():
        print(f"   -[:{rel}]->(:{cibles[rel]})   {n} arêtes")

    # un exemple de Cypher généré
    ex = next(i for i in incidents if i["relations"])
    print(f"\nExemple — Cypher généré pour {ex['id']} :")
    for l in cypher_incident(label, ex):
        print("   " + l)

    if args.write:
        print("\n(--write demandé : écriture Neo4j — non implémentée dans ce test dry-run)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
