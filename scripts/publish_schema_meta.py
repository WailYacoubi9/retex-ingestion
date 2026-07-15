"""
Publie les métadonnées d'un schéma YAML dans le graphe Neo4j.

Crée :  (:ModuleMeta {nom_technique, libelle})
           -[:A_POUR_CHAMP]-> (:ChampMeta {module, cle, label, description,
                                           type, role, bloc, embedding})

Objectif : le YAML reste LA source de vérité unique. L'API (field_catalog.py,
moteur générique) lit ces nœuds pour connaître les labels et descriptions
métier des champs — aucune duplication côté code.

Usage :
    python scripts/publish_schema_meta.py                       # schéma incident v2
    python scripts/publish_schema_meta.py --schema config/schemas/autre.schema.yaml

Idempotent (MERGE) : relançable après chaque évolution du YAML.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
from clients import Neo4jClient

DEFAULT_SCHEMA = PROJECT_ROOT / "config" / "schemas" / "incident_securite_v2.schema.yaml"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("publish_schema_meta")


def _champ_props(champ: dict, bloc: str) -> dict:
    """Extrait les propriétés à publier pour un champ du schéma."""
    props = {
        "cle": champ["cle"],
        "label": champ.get("label") or champ["cle"],
        "description": champ.get("description") or "",
        "type": champ.get("type") or "texte",
        "role": champ.get("role") or "propriete",
        "bloc": bloc,
        "embedding": bool(champ.get("embedding")),
    }
    valeurs = champ.get("valeurs_possibles")
    if valeurs:
        # stockées en liste "code — sens" (lisible par le LLM du moteur générique)
        props["valeurs_possibles"] = [f"{k} — {v}" for k, v in valeurs.items()]
    if champ.get("role") == "relation":
        props["noeud"] = champ.get("noeud")
        props["relation"] = champ.get("relation")
        props["cle_noeud"] = champ.get("cle_noeud")
    return props


def publish(schema_path: Path) -> int:
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    module = schema["module"]["nom_technique"]
    libelle = schema["module"].get("libelle") or module

    champs = [(_champ_props(c, "principal")) for c in schema.get("champs", [])]
    for c in (schema.get("actions") or {}).get("champs", []):
        champs.append(_champ_props(c, "actions"))

    logger.info("Module %s : %d champs à publier", module, len(champs))

    label_noeud = schema["module"].get("label_noeud") or ""
    exemples = schema["module"].get("exemples_questions") or []
    synonymes = schema["module"].get("synonymes_fiche") or []

    with Neo4jClient(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD) as neo4j:
        neo4j.execute(
            "MERGE (m:ModuleMeta {nom_technique: $module}) "
            "SET m.libelle = $libelle, m.label_noeud = $label_noeud, "
            "    m.exemples = $exemples, m.synonymes = $synonymes",
            module=module, libelle=libelle, label_noeud=label_noeud,
            exemples=exemples, synonymes=synonymes,
        )
        # purge des champs disparus du schéma
        neo4j.execute(
            "MATCH (:ModuleMeta {nom_technique: $module})-[:A_POUR_CHAMP]->(c:ChampMeta) "
            "WHERE NOT c.cle IN $cles DETACH DELETE c",
            module=module, cles=[c["cle"] for c in champs],
        )
        for props in champs:
            neo4j.execute(
                "MATCH (m:ModuleMeta {nom_technique: $module}) "
                "MERGE (c:ChampMeta {module: $module, cle: $cle}) "
                "SET c += $props "
                "MERGE (m)-[:A_POUR_CHAMP]->(c)",
                module=module, cle=props["cle"],
                props={**props, "module": module},
            )

        n = neo4j.run(
            "MATCH (:ModuleMeta {nom_technique: $module})-[:A_POUR_CHAMP]->(c) "
            "RETURN count(c) AS n", module=module,
        )[0]["n"]
        logger.info("Publié : %d ChampMeta pour le module %s", n, module)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Publie un schéma YAML dans le graphe (ModuleMeta/ChampMeta)")
    ap.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    args = ap.parse_args()
    if not args.schema.exists():
        logger.error("Schéma introuvable : %s", args.schema)
        return 1
    return publish(args.schema)


if __name__ == "__main__":
    sys.exit(main())
