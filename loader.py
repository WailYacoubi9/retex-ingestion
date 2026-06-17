"""
Loader : écrit les IncidentCanonique dans Neo4j et Qdrant.
Idempotent : rejoignable sans duplication grâce aux UUID stables et MERGE.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from qdrant_client.http.models import PointStruct

from clients import Neo4jClient, OllamaClient, QdrantWrapper
from models import IncidentCanonique

logger = logging.getLogger(__name__)


# =====================================================================
# Initialisation du schéma Neo4j
# =====================================================================

CONSTRAINTS_AND_INDEXES = [
    # Unicité sur les IDs
    "CREATE CONSTRAINT incident_id IF NOT EXISTS FOR (n:Incident) REQUIRE n.incident_id IS UNIQUE",
    "CREATE CONSTRAINT personne_name IF NOT EXISTS FOR (n:Personne) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT referentiel_key IF NOT EXISTS FOR (n:Referentiel) REQUIRE n.ref_key IS UNIQUE",
    # Index utiles pour les requêtes
    "CREATE INDEX incident_source_type IF NOT EXISTS FOR (n:Incident) ON (n.source_type)",
    "CREATE INDEX incident_date IF NOT EXISTS FOR (n:Incident) ON (n.date_evenement)",
    "CREATE INDEX referentiel_family IF NOT EXISTS FOR (n:Referentiel) ON (n.family)",
]


def bootstrap_neo4j(neo4j: Neo4jClient) -> None:
    """Applique les contraintes et index. Idempotent."""
    logger.info("Bootstrapping Neo4j constraints and indexes")
    with neo4j.session() as s:
        for stmt in CONSTRAINTS_AND_INDEXES:
            s.run(stmt)
    logger.info("Neo4j schema ready")


# =====================================================================
# Écriture Neo4j
# =====================================================================

def _is_test_data(incident: IncidentCanonique) -> bool:
    """Détecte les payloads de test (contiennent des templates Postman)."""
    for field in [incident.titre, incident.detail]:
        if field and "{{" in field:
            return True
    return False


def write_incident_to_neo4j(neo4j: Neo4jClient, incident: IncidentCanonique) -> None:
    """Écrit un incident complet dans Neo4j avec toutes ses relations.
    Idempotent via MERGE."""

    is_test = _is_test_data(incident)

    # Préparation des propriétés de l'incident
    props: dict[str, Any] = {
        "incident_id": incident.incident_id,
        "source_type": incident.source_type,
        "source_ref": incident.source_ref,
        "titre": incident.titre,
        "detail": incident.detail,
        "causes_presumees": incident.causes_presumees,
        "analyse_causes": incident.analyse_causes,
        "precision_lieu": incident.precision_lieu,
        "type_nc": incident.type_nc,
        "site_application": incident.site_application,
        "is_test_data": is_test,
    }
    # Dates : stockées en format ISO pour que Neo4j puisse les convertir
    if incident.date_evenement:
        props["date_evenement"] = incident.date_evenement.isoformat()
    if incident.date_creation:
        props["date_creation"] = incident.date_creation.isoformat()

    # Enrichissement LLM si présent
    if incident.llm:
        props["resume_llm"] = incident.llm.resume
        props["facteur_causal"] = incident.llm.facteur_causal
        props["severite_percue"] = incident.llm.severite_percue
        props["etat_final"] = incident.llm.etat_final
        props["llm_model"] = incident.llm.llm_model

    # 1. MERGE du nœud Incident
    with neo4j.session() as s:
        s.run("""
            MERGE (i:Incident {incident_id: $incident_id})
            SET i += $props,
                i.last_indexed_at = datetime(),
                i.date_evenement = CASE WHEN $date_evenement_iso IS NULL
                                         THEN i.date_evenement
                                         ELSE datetime($date_evenement_iso) END,
                i.date_creation = CASE WHEN $date_creation_iso IS NULL
                                        THEN i.date_creation
                                        ELSE datetime($date_creation_iso) END
        """,
               incident_id=incident.incident_id,
               props=props,
               date_evenement_iso=props.get("date_evenement"),
               date_creation_iso=props.get("date_creation"))

        # 2. MERGE des personnes + relations
        for p in incident.personnes:
            rel_type = {
                "emetteur": "EMIS_PAR",
                "resp_traitement": "TRAITE_PAR",
                "notifiant": "NOTIFIE_PAR",
            }.get(p.role, "LIEE_A")

            s.run(f"""
                MERGE (pers:Personne {{name: $name}})
                ON CREATE SET pers.display_name = $display_name
                WITH pers
                MATCH (i:Incident {{incident_id: $incident_id}})
                MERGE (i)-[:{rel_type}]->(pers)
            """,
                  name=p.name,
                  display_name=p.display_name or p.name,
                  incident_id=incident.incident_id)

        # 3. MERGE des référentiels + relations
        for r in incident.referentiels:
            ref_key = f"{r.family}::{r.code}"
            s.run("""
                MERGE (ref:Referentiel {ref_key: $ref_key})
                ON CREATE SET ref.family = $family,
                              ref.code = $code,
                              ref.label = $label,
                              ref.code_externe = $code_externe,
                              ref.id_source = $id_source
                ON MATCH SET ref.label = COALESCE(ref.label, $label)
                WITH ref
                MATCH (i:Incident {incident_id: $incident_id})
                MERGE (i)-[rel:REFERENCE {role: $role}]->(ref)
            """,
                  ref_key=ref_key,
                  family=r.family,
                  code=r.code,
                  label=r.label,
                  code_externe=r.code_externe,
                  id_source=r.id_source,
                  incident_id=incident.incident_id,
                  role=r.role)

    logger.info("Incident %s written to Neo4j (test_data=%s)",
                incident.incident_id, is_test)


# =====================================================================
# Écriture Qdrant
# =====================================================================

def _qdrant_point_id(incident_id: str, section: str) -> str:
    """Génère un ID stable pour un point Qdrant, dérivé de (incident, section)."""
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"{incident_id}::{section}"))


def write_incident_to_qdrant(qdrant: QdrantWrapper, ollama: OllamaClient,
                              incident: IncidentCanonique) -> int:
    """Écrit les chunks embeddés d'un incident dans Qdrant.
    Retourne le nombre de points insérés."""

    sections = incident.embeddable_sections()
    if not sections:
        logger.debug("No embeddable sections for %s", incident.incident_id)
        return 0

    # Embedding batch (plus efficace que un par un)
    section_names = list(sections.keys())
    texts = list(sections.values())

    try:
        vectors = ollama.embed_batch(texts)
    except Exception as e:
        logger.error("Embedding failed for %s: %s", incident.incident_id, e)
        return 0

    if len(vectors) != len(texts):
        logger.error("Embedding count mismatch for %s: %d vectors for %d texts",
                     incident.incident_id, len(vectors), len(texts))
        return 0

    # Construction des points Qdrant
    points: list[PointStruct] = []
    for section, vector in zip(section_names, vectors):
        payload = {
            "incident_id": incident.incident_id,
            "section": section,
            "source_type": incident.source_type,
        }
        if incident.date_evenement:
            payload["date_evenement"] = incident.date_evenement.isoformat()
        if incident.type_nc:
            payload["type_nc"] = incident.type_nc

        points.append(PointStruct(
            id=_qdrant_point_id(incident.incident_id, section),
            vector=vector,
            payload=payload,
        ))

    qdrant.upsert_points(points)
    logger.info("Incident %s written to Qdrant (%d chunks)",
                incident.incident_id, len(points))
    return len(points)