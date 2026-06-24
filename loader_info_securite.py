"""
Loader Neo4j + Qdrant pour les Info Securite DGAC.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from qdrant_client.http.models import PointStruct

from clients import Neo4jClient, OllamaClient, QdrantWrapper
from models_info_securite import InfoSecuriteCanonique


logger = logging.getLogger(__name__)


# Champs textuels du dataclass vectorises dans Qdrant
CHAMPS_VECTORISES = [
    ("sujet", 10),
    ("objectif", 20),
    ("contexte", 100),
    ("actions_recommandees", 50),
    ("annexe", 100),
    ("references", 30),
    ("contenu_hors_tableau", 100),
]


def _strip_html(text: str | None) -> str:
    """Retire <br> pour avoir du texte propre dans Qdrant."""
    if not text:
        return ""
    cleaned = text.replace("<br><br>", "\n\n").replace("<br>", " ")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def bootstrap_neo4j_schema(neo4j: Neo4jClient) -> None:
    """Cree les contraintes Neo4j pour InfoSecurite (idempotent)."""
    neo4j.execute(
        "CREATE CONSTRAINT info_securite_id_unique IF NOT EXISTS "
        "FOR (i:InfoSecurite) REQUIRE i.info_securite_id IS UNIQUE"
    )
    neo4j.execute(
        "CREATE CONSTRAINT info_securite_number_unique IF NOT EXISTS "
        "FOR (i:InfoSecurite) REQUIRE i.is_number IS UNIQUE"
    )
    logger.info("Schema Neo4j InfoSecurite : contraintes verifiees")


def write_to_neo4j(canonique: InfoSecuriteCanonique, neo4j: Neo4jClient) -> None:
    """MERGE le noeud InfoSecurite et ses relations dans Neo4j."""
    canonique.last_indexed_at = datetime.now(timezone.utc).isoformat()

    props: dict[str, Any] = {
        "info_securite_id": canonique.info_securite_id,
        "is_number": canonique.is_number,
        "annee": canonique.annee,
        "source_module": canonique.source_module,
        "titre": canonique.titre,
        "operateurs_concernes": canonique.operateurs_concernes,
        "sujet": canonique.sujet,
        "objectif": canonique.objectif,
        "contexte": canonique.contexte,
        "actions_recommandees": canonique.actions_recommandees,
        "annexe": canonique.annexe,
        "references_pdf": canonique.references,
        "contenu_hors_tableau": canonique.contenu_hors_tableau,
        "version_numero": canonique.version_numero,
        "date_version": canonique.date_version.isoformat() if canonique.date_version else None,
        "is_test_data": canonique.is_test_data,
        "last_indexed_at": canonique.last_indexed_at,
    }

    if canonique.llm:
        props["llm_resume"] = canonique.llm.resume
        props["llm_model"] = canonique.llm.model_used

    if canonique.extra_fields:
        for key, value in canonique.extra_fields.items():
            safe_key = re.sub(r"[^a-z0-9_]", "_", key.lower())
            props[f"extra_{safe_key}"] = value

    neo4j.execute(
        """
        MERGE (i:InfoSecurite {info_securite_id: $info_securite_id})
        SET i += $props
        """,
        info_securite_id=canonique.info_securite_id,
        props=props,
    )

    # Relations IS -> IS (remplace)
    for ancien_num in canonique.remplace:
        neo4j.execute(
            """
            MERGE (ancien:InfoSecurite {is_number: $ancien_num})
            ON CREATE SET ancien.is_stub = true, ancien.statut = "remplacee"
            WITH ancien
            MATCH (nouveau:InfoSecurite {info_securite_id: $nouveau_id})
            MERGE (nouveau)-[:REMPLACE]->(ancien)
            """,
            ancien_num=ancien_num,
            nouveau_id=canonique.info_securite_id,
        )


def write_to_qdrant(
    canonique: InfoSecuriteCanonique,
    qdrant: QdrantWrapper,
    ollama: OllamaClient,
) -> int:
    """Vectorise et upsert les chunks textuels dans Qdrant.

    Retourne le nombre de chunks upsertes.
    """
    points: list[PointStruct] = []

    # Chunks depuis les champs textuels du dataclass
    for champ, min_len in CHAMPS_VECTORISES:
        contenu_brut = getattr(canonique, champ, None)
        contenu = _strip_html(contenu_brut)
        if not contenu or len(contenu) < min_len:
            continue

        vector = ollama.embed(contenu)
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{canonique.info_securite_id}_{champ}"))
        payload = {
            "info_securite_id": canonique.info_securite_id,
            "is_number": canonique.is_number,
            "annee": canonique.annee,
            "source_module": canonique.source_module,
            "field_canonical": champ,
            "is_test_data": canonique.is_test_data,
            "text": contenu,
        }
        points.append(PointStruct(id=point_id, vector=vector, payload=payload))

    # Chunk du resume LLM si present
    if canonique.llm and canonique.llm.resume:
        resume = canonique.llm.resume
        vector = ollama.embed(resume)
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{canonique.info_securite_id}_llm_resume"))
        payload = {
            "info_securite_id": canonique.info_securite_id,
            "is_number": canonique.is_number,
            "annee": canonique.annee,
            "source_module": canonique.source_module,
            "field_canonical": "llm_resume",
            "is_test_data": canonique.is_test_data,
            "text": resume,
        }
        points.append(PointStruct(id=point_id, vector=vector, payload=payload))

    qdrant.upsert_points(points)
    return len(points)


def load_one(
    canonique: InfoSecuriteCanonique,
    neo4j: Neo4jClient,
    qdrant: QdrantWrapper,
    ollama: OllamaClient,
) -> int:
    """Ecrit une IS dans Neo4j et Qdrant. Retourne le nombre de chunks Qdrant."""
    write_to_neo4j(canonique, neo4j)
    n_chunks = write_to_qdrant(canonique, qdrant, ollama)
    return n_chunks