"""
Chargement d'un IncidentCanonique dans Neo4j et Qdrant.

Materialise les entites du format canonique en noeuds et relations
dans le graphe, et embedde les champs textuels en vecteurs Qdrant.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from clients import Neo4jClient, OllamaClient, QdrantWrapper
from models import IncidentCanonique
from yaml_loader import ModuleMapping

logger = logging.getLogger(__name__)


# =====================================================================
# BOOTSTRAP DU SCHEMA
# =====================================================================

def bootstrap_neo4j(neo4j: Neo4jClient) -> None:
    """Cree les contraintes d'unicite Neo4j (idempotent).

    Utilisation : appelee une fois au demarrage du pipeline pour garantir
    que les MERGE Cypher beneficient des contraintes d'unicite.
    """
    constraints = [
        "CREATE CONSTRAINT incident_id_unique IF NOT EXISTS "
        "FOR (i:Incident) REQUIRE i.incident_id IS UNIQUE",

        "CREATE CONSTRAINT societe_id_unique IF NOT EXISTS "
        "FOR (s:Societe) REQUIRE s.id_societe IS UNIQUE",

        "CREATE CONSTRAINT personne_login_unique IF NOT EXISTS "
        "FOR (p:Personne) REQUIRE p.login IS UNIQUE",

        "CREATE CONSTRAINT referentiel_key_unique IF NOT EXISTS "
        "FOR (r:Referentiel) REQUIRE r.ref_key IS UNIQUE",
    ]

    for cypher in constraints:
        try:
            neo4j.execute(cypher)
        except Exception as e:
            logger.warning("Erreur creation contrainte : %s", e)


# =====================================================================
# ECRITURE NEO4J
# =====================================================================

def write_incident_to_neo4j(neo4j: Neo4jClient, incident: IncidentCanonique) -> None:
    """Ecrit un incident complet dans Neo4j (noeud + relations).

    Utilisation : pipeline de chargement principal. Cree ou met a jour
    le noeud Incident et toutes ses relations vers Societe, Personne,
    Referentiel.
    """
    _merge_incident_node(neo4j, incident)
    _merge_societes(neo4j, incident)
    _merge_personnes(neo4j, incident)
    _merge_referentiels(neo4j, incident)


def _merge_incident_node(neo4j: Neo4jClient, incident: IncidentCanonique) -> None:
    """Cree ou met a jour le noeud Incident principal.

    Utilisation : interne. Utilise MERGE pour idempotence. Met a jour
    toutes les proprietes y compris l'enrichissement LLM si present.
    """
    props = _incident_to_props(incident)

    cypher = """
    MERGE (i:Incident {incident_id: $incident_id})
    SET i += $props
    """

    neo4j.execute(cypher, incident_id=incident.incident_id, props=props)


def _incident_to_props(incident: IncidentCanonique) -> dict[str, Any]:
    """Convertit un IncidentCanonique en dict de proprietes Neo4j.

    Utilisation : interne. Filtre les valeurs None et convertit les
    types complexes (datetime, time, dict) en types Neo4j-friendly.
    """
    props: dict[str, Any] = {
        "incident_id_source": incident.incident_id_source,
        "source_module": incident.source_module,
        "is_test_data": incident.is_test_data,
        "last_indexed_at": incident.last_indexed_at,
    }

    # Champs scalaires simples
    for attr in ["numero_fe", "type_nc", "abbr", "titre", "detail",
                 "recolte_faits", "notes_suivi", "etape", "archive",
                 "blesses_raw", "presence_blesses", "pret_envoi_eccairs"]:
        value = getattr(incident, attr, None)
        if value is not None:
            props[attr] = value

    # Dates -> ISO strings (Neo4j accepte ISO datetime mais on standardise)
    if incident.date_evenement:
        props["date_evenement"] = incident.date_evenement.isoformat()
    if incident.date_creation:
        props["date_creation"] = incident.date_creation.isoformat()
    if incident.heure_evenement:
        props["heure_evenement"] = incident.heure_evenement.isoformat()

    # Enrichissement LLM (si present)
    if incident.llm:
        if incident.llm.resume:
            props["resume_llm"] = incident.llm.resume
        if incident.llm.facteur_causal:
            props["facteur_causal"] = incident.llm.facteur_causal
        if incident.llm.severite_percue:
            props["severite_percue"] = incident.llm.severite_percue
        if incident.llm.etat_final:
            props["etat_final"] = incident.llm.etat_final
        if incident.llm.model_used:
            props["llm_model"] = incident.llm.model_used

    # Extra fields : on les ajoute en prefixant pour eviter collisions
    for key, value in incident.extra_fields.items():
        # Neo4j n'accepte pas les dicts/listes complexes, on stringify
        if isinstance(value, (dict, list)):
            import json
            props[f"extra_{key}"] = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, (str, int, float, bool)):
            props[f"extra_{key}"] = value

    return props


def _merge_societes(neo4j: Neo4jClient, incident: IncidentCanonique) -> None:
    """Cree les noeuds Societe et les relations CONCERNE.

    Utilisation : interne. Une societe est identifiee par son id_societe
    unique. Plusieurs incidents peuvent pointer vers la meme societe.
    """
    cypher = """
    MATCH (i:Incident {incident_id: $incident_id})
    MERGE (s:Societe {id_societe: $id_societe})
    MERGE (i)-[:CONCERNE]->(s)
    """

    for societe in incident.societes:
        neo4j.execute(
            cypher,
            incident_id=incident.incident_id,
            id_societe=societe.id_societe,
        )


def _merge_personnes(neo4j: Neo4jClient, incident: IncidentCanonique) -> None:
    """Cree les noeuds Personne et les relations typees par role.

    Utilisation : interne. Une personne est identifiee par son login
    unique. La relation porte le role (EMIS_PAR, etc.).
    """
    for personne in incident.personnes:
        # Le type de relation est dynamique, donc on construit le Cypher
        # avec le nom de relation injecte (sans risque d'injection car
        # vient du YAML controle)
        relation_type = "EMIS_PAR" if personne.role == "emetteur" else "IMPLIQUE"

        cypher = f"""
        MATCH (i:Incident {{incident_id: $incident_id}})
        MERGE (p:Personne {{login: $login}})
        SET p += $props
        MERGE (i)-[:{relation_type}]->(p)
        """

        neo4j.execute(
            cypher,
            incident_id=incident.incident_id,
            login=personne.login,
            props=personne.to_neo4j_props(),
        )


def _merge_referentiels(neo4j: Neo4jClient, incident: IncidentCanonique) -> None:
    """Cree les noeuds Referentiel et les relations typees.

    Utilisation : interne. Un Referentiel est identifie par (family, code).
    Le type de relation vient du YAML.
    """
    for ref in incident.referentiels:
        relation_type = ref.relation_type

        cypher = f"""
        MATCH (i:Incident {{incident_id: $incident_id}})
        MERGE (r:Referentiel {{ref_key: $ref_key}})
        SET r += $props
        MERGE (i)-[:{relation_type}]->(r)
        """

        neo4j.execute(
            cypher,
            incident_id=incident.incident_id,
            ref_key=ref.ref_key,
            props=ref.to_neo4j_props(),
        )


# =====================================================================
# ECRITURE QDRANT
# =====================================================================

def write_incident_to_qdrant(
    qdrant: QdrantWrapper,
    ollama: OllamaClient,
    incident: IncidentCanonique,
    mapping: ModuleMapping,
) -> int:
    """Embedde et stocke les champs textuels d'un incident dans Qdrant.

    Utilisation : pipeline de chargement. Lit la config champs_textuels
    du YAML pour savoir quels champs embedder. Retourne le nombre de
    chunks ecrits.
    """
    n_chunks = 0

    for tf in mapping.champs_textuels:
        if not tf.for_embedding:
            continue

        text = incident.get_text_for_field(tf.canonical)
        if not text or len(text) < tf.min_length:
            continue

        chunk_id = _make_chunk_id(incident.incident_id, tf.canonical)
        vector = ollama.embed(text)

        payload = {
            "incident_id": incident.incident_id,
            "incident_id_source": incident.incident_id_source,
            "source_module": incident.source_module,
            "field_canonical": tf.canonical,
            "text": text,
            "is_test_data": incident.is_test_data,
        }

        qdrant.upsert(
            point_id=chunk_id,
            vector=vector,
            payload=payload,
        )
        n_chunks += 1

    # On embedde aussi le resume LLM s'il existe
    if incident.llm and incident.llm.resume:
        chunk_id = _make_chunk_id(incident.incident_id, "resume_llm")
        vector = ollama.embed(incident.llm.resume)
        payload = {
            "incident_id": incident.incident_id,
            "incident_id_source": incident.incident_id_source,
            "source_module": incident.source_module,
            "field_canonical": "resume_llm",
            "text": incident.llm.resume,
            "is_test_data": incident.is_test_data,
        }
        qdrant.upsert(point_id=chunk_id, vector=vector, payload=payload)
        n_chunks += 1

    return n_chunks


def _make_chunk_id(incident_id: str, field_name: str) -> str:
    """Genere un UUID v5 stable pour un chunk Qdrant.

    Utilisation : interne. Garantit qu'un meme (incident, champ) aura
    toujours le meme ID Qdrant, donc upsert au lieu de duplication.
    """
    namespace = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
    name = f"{incident_id}:{field_name}"
    return str(uuid.uuid5(namespace, name))
