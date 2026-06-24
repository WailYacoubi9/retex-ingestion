"""
Loader — Incident Sécurité v2 : écrit IncidentSecuriteV2Canonique dans Neo4j + Qdrant.

Pipeline PARALLÈLE :
  - nœud incident sous le label dédié :IncidentSecu (n'interfère pas avec
    le :Incident du pipeline HAL existant) ;
  - nœuds liés génériques (Lieu, Compagnie, Societe...) créés depuis EntiteLiee ;
  - réutilise clients.py (Neo4jClient / QdrantWrapper / OllamaClient) sans le modifier.

Idempotent : MERGE Neo4j sur incident_id, upsert Qdrant sur un id stable.
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import fields
from datetime import date, datetime, time
from typing import Any

from clients import Neo4jClient, OllamaClient, QdrantWrapper
from models_incident_securite_v2 import IncidentSecuriteV2Canonique

logger = logging.getLogger(__name__)

LABEL_INCIDENT = "IncidentSecu"
_QDRANT_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

# Champs jamais écrits comme propriété simple (les relations sont gérées à part).
_NON_PROPS = {"entites"}


def _safe(ident: str) -> str:
    """Nettoie un label/relation pour interpolation Cypher (alphanum + _)."""
    return re.sub(r"[^0-9A-Za-z_]", "_", ident)


def bootstrap_neo4j(neo4j: Neo4jClient) -> None:
    """Contrainte d'unicité sur le nœud incident v2 (label dédié)."""
    neo4j.execute(
        f"CREATE CONSTRAINT incident_secu_v2_id IF NOT EXISTS "
        f"FOR (i:{LABEL_INCIDENT}) REQUIRE i.incident_id IS UNIQUE"
    )


def _incident_props(inc: IncidentSecuriteV2Canonique) -> dict[str, Any]:
    """Propriétés Neo4j en parcourant TOUS les champs du modèle (dynamique).

    Tout champ ajouté au schéma (donc au modèle généré) est écrit
    automatiquement — plus aucune liste à maintenir ici. Les relations
    (`entites`) sont gérées à part ; les types complexes (listes/dicts/objets)
    sont ignorés car Neo4j ne les accepte pas en propriété.
    """
    props: dict[str, Any] = {}
    for f in fields(inc):
        if f.name in _NON_PROPS:
            continue
        val = getattr(inc, f.name, None)
        if val is None:
            continue
        if isinstance(val, (datetime, date, time)):
            props[f.name] = val.isoformat()
        elif isinstance(val, (str, int, float, bool)):
            props[f.name] = val
        # autres types -> ignorés
    return props


def write_incident_to_neo4j(neo4j: Neo4jClient, inc: IncidentSecuriteV2Canonique) -> None:
    """MERGE l'incident + ses nœuds liés dans une seule session Neo4j."""
    with neo4j.session() as s:
        s.run(
            f"MERGE (i:{LABEL_INCIDENT} {{incident_id: $id}}) SET i += $props",
            id=inc.incident_id, props=_incident_props(inc),
        ).consume()

        for e in inc.entites:
            noeud = _safe(e.noeud)
            cle = _safe(e.cle)
            rel = _safe(e.relation)
            s.run(
                f"MATCH (i:{LABEL_INCIDENT} {{incident_id: $id}}) "
                f"MERGE (n:{noeud} {{{cle}: $valeur}}) "
                f"MERGE (i)-[:{rel}]->(n)",
                id=inc.incident_id, valeur=e.valeur,
            ).consume()


def write_incident_to_qdrant(inc: IncidentSecuriteV2Canonique, qdrant: QdrantWrapper,
                             ollama: OllamaClient) -> int:
    """Vectorise les narratifs utiles. Retourne le nombre de chunks écrits."""
    n = 0
    for champ, texte in inc.textes_pour_embedding().items():
        vector = ollama.embed(texte)
        point_id = str(uuid.uuid5(_QDRANT_NAMESPACE, f"{inc.incident_id}:{champ}"))
        payload = {
            "incident_id": inc.incident_id,
            "numero_fe": inc.numero_fe,
            "source_module": inc.source_module,
            "field_canonical": champ,
            "texte": texte,
            "severite": inc.severite,
            "is_test_data": inc.is_test_data,
        }
        qdrant.upsert(point_id=point_id, vector=vector, payload=payload)
        n += 1
    return n
