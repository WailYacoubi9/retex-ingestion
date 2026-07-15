"""
Audit read-only : état du graphe Neo4j + collection Qdrant.
Aucune écriture (pas de CREATE/MERGE/SET/DELETE/index).
Usage : python scripts/audit_graph.py
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, QDRANT_URL
from clients import Neo4jClient, QdrantWrapper, INCIDENT_CHUNKS_COLLECTION

SEP = "=" * 70
SUB = "-" * 50
MAIN_LABELS = {"Incident", "IncidentSecu", "Ticket", "InfoSecurite"}
NAME_PROPS = {"nom", "label", "valeur", "name", "login", "titre", "libelle"}


# ─── helpers ──────────────────────────────────────────────────────────────────

def _hdr(title: str) -> None:
    print(f"\n{SEP}\n  {title}\n{SEP}")


def _sub(title: str) -> None:
    print(f"\n{SUB}\n  {title}\n{SUB}")


def _rows(rows: list[dict], keys: list[str], widths: list[int]) -> None:
    fmt = "  " + "  ".join(f"{{:<{w}}}" for w in widths)
    header = fmt.format(*keys)
    print(header)
    print("  " + "  ".join("-" * w for w in widths))
    for row in rows:
        print(fmt.format(*[str(row.get(k, "")) for k in keys]))


# ─── Neo4j ────────────────────────────────────────────────────────────────────

def audit_neo4j() -> None:
    _hdr("NEO4J")
    try:
        with Neo4jClient(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD) as neo4j:
            _section_labels(neo4j)
            _section_relations(neo4j)
            _section_properties(neo4j)
            _section_satellites(neo4j)
            _section_triplets(neo4j)
    except Exception as exc:
        print(f"\n  [ERREUR Neo4j] {exc}")


def _section_labels(neo4j: Neo4jClient) -> None:
    _sub("1. Nœuds par label")
    rows = neo4j.run(
        "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS total "
        "ORDER BY total DESC"
    )
    _rows(rows, ["label", "total"], [25, 10])
    total = sum(r["total"] for r in rows)
    print(f"\n  Total nœuds : {total:,}")


def _section_relations(neo4j: Neo4jClient) -> None:
    _sub("2. Relations par type")
    rows = neo4j.run(
        "MATCH ()-[r]->() RETURN type(r) AS type, count(r) AS total "
        "ORDER BY total DESC"
    )
    _rows(rows, ["type", "total"], [30, 10])
    total = sum(r["total"] for r in rows)
    print(f"\n  Total relations : {total:,}")


def _section_properties(neo4j: Neo4jClient) -> None:
    _sub("3. Propriétés par label  (focus Incident vs IncidentSecu)")
    raw = neo4j.run(
        "CALL db.schema.nodeTypeProperties() "
        "YIELD nodeLabels, propertyName "
        "RETURN nodeLabels, propertyName"
    )
    props_by_label: dict[str, list[str]] = defaultdict(list)
    for row in raw:
        label = row["nodeLabels"][0] if row["nodeLabels"] else "?"
        prop = row["propertyName"]
        if prop and prop not in props_by_label[label]:
            props_by_label[label].append(prop)

    # Tous les labels
    for label in sorted(props_by_label):
        props = sorted(props_by_label[label])
        print(f"\n  [{label}]  ({len(props)} propriétés)")
        for chunk_start in range(0, len(props), 5):
            chunk = props[chunk_start:chunk_start + 5]
            print("    " + ",  ".join(chunk))

    # Incident vs IncidentSecu côte à côte
    inc_old = set(props_by_label.get("Incident", []))
    inc_new = set(props_by_label.get("IncidentSecu", []))
    if inc_old or inc_new:
        print(f"\n  {'Incident':35s}  {'IncidentSecu':35s}")
        print("  " + "-" * 72)
        all_props = sorted(inc_old | inc_new)
        for p in all_props:
            old_mark = "✓" if p in inc_old else " "
            new_mark = "✓" if p in inc_new else " "
            print(f"  {old_mark} {p:<33s}  {new_mark} {p}")


def _section_satellites(neo4j: Neo4jClient) -> None:
    _sub("4. Nœuds satellites (hors labels principaux)")
    label_rows = neo4j.run(
        "MATCH (n) WITH labels(n)[0] AS lbl, count(n) AS cnt "
        "WHERE lbl IS NOT NULL "
        "RETURN lbl, cnt ORDER BY cnt DESC"
    )
    raw_props = neo4j.run(
        "CALL db.schema.nodeTypeProperties() "
        "YIELD nodeLabels, propertyName "
        "RETURN nodeLabels, propertyName"
    )
    props_map: dict[str, list[str]] = defaultdict(list)
    for row in raw_props:
        lbl = row["nodeLabels"][0] if row["nodeLabels"] else "?"
        p = row["propertyName"]
        if p and p not in props_map[lbl]:
            props_map[lbl].append(p)

    for row in label_rows:
        lbl = row["lbl"]
        if lbl in MAIN_LABELS:
            continue
        props = sorted(props_map.get(lbl, []))
        name_prop = next((p for p in props if p in NAME_PROPS), None)
        print(f"\n  {lbl}  ({row['cnt']:,} nœuds)  props: {', '.join(props)}")
        if name_prop:
            samples = neo4j.run(
                f"MATCH (n:`{lbl}`) WHERE n.`{name_prop}` IS NOT NULL "
                f"RETURN n.`{name_prop}` AS val LIMIT 3"
            )
            vals = [str(r["val"]) for r in samples]
            print(f"    Exemples ({name_prop}) : {' | '.join(vals)}")


def _section_triplets(neo4j: Neo4jClient) -> None:
    _sub("5. Motifs de relation (src)-[rel]->(tgt)  — top 50 par fréquence")
    rows = neo4j.run(
        "MATCH (a)-[r]->(b) "
        "WITH labels(a)[0] AS src, type(r) AS rel, labels(b)[0] AS tgt, count(*) AS cnt "
        "ORDER BY cnt DESC LIMIT 50 "
        "RETURN src, rel, tgt, cnt"
    )
    _rows(rows, ["src", "rel", "tgt", "cnt"], [20, 25, 20, 8])


# ─── Qdrant ───────────────────────────────────────────────────────────────────

def audit_qdrant() -> None:
    _hdr("QDRANT")
    try:
        qdrant = QdrantWrapper(QDRANT_URL)
        _section_collection(qdrant)
        _section_scroll(qdrant)
    except Exception as exc:
        print(f"\n  [ERREUR Qdrant] {exc}")
        print("  → Vérifiez que le service Qdrant est démarré.")


def _section_collection(qdrant: QdrantWrapper) -> None:
    _sub("6. Collection")
    try:
        info = qdrant._client.get_collection(INCIDENT_CHUNKS_COLLECTION)
        cfg = info.config.params.vectors
        print(f"  Nom         : {INCIDENT_CHUNKS_COLLECTION}")
        print(f"  Points      : {info.points_count:,}")
        if hasattr(cfg, "size"):
            print(f"  Dim vecteur : {cfg.size}")
            print(f"  Distance    : {cfg.distance}")
    except Exception as exc:
        print(f"  [ERREUR collection] {exc}")


def _section_scroll(qdrant: QdrantWrapper) -> None:
    _sub("7 & 8. Agrégation payloads (scroll paginé)")
    print("  Chargement en cours…", flush=True)

    source_counts: Counter = Counter()
    field_counts: dict[str, Counter] = defaultdict(Counter)
    n_points = 0
    offset = None

    try:
        while True:
            points, offset = qdrant._client.scroll(
                collection_name=INCIDENT_CHUNKS_COLLECTION,
                with_payload=["source_module", "field_canonical"],
                with_vectors=False,
                limit=1000,
                offset=offset,
            )
            for p in points:
                sm = (p.payload or {}).get("source_module", "unknown")
                fc = (p.payload or {}).get("field_canonical", "unknown")
                source_counts[sm] += 1
                field_counts[sm][fc] += 1
                n_points += 1
            if offset is None:
                break
    except Exception as exc:
        print(f"  [ERREUR scroll] {exc}")
        return

    print(f"  Points parcourus : {n_points:,}\n")

    print("  Source modules :")
    for sm, cnt in source_counts.most_common():
        print(f"    {sm:<40s} {cnt:>8,}")

    target_module = "incident_securite_v2"
    if target_module in field_counts:
        print(f"\n  Champs (field_canonical) pour module '{target_module}' :")
        for fc, cnt in sorted(field_counts[target_module].items(),
                              key=lambda x: -x[1]):
            print(f"    {fc:<35s} {cnt:>8,}")
    else:
        known = list(source_counts.keys())
        print(f"\n  Module '{target_module}' absent. Modules présents : {known}")


# ─── main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n{'#' * 70}")
    print(f"  AUDIT GRAPHE  —  Neo4j: {NEO4J_URI}  |  Qdrant: {QDRANT_URL}")
    print(f"{'#' * 70}")

    audit_neo4j()
    audit_qdrant()

    print(f"\n{SEP}\n  FIN DU RAPPORT\n{SEP}\n")
