"""
Loader Neo4j + Qdrant pour les tickets intra'know.

Schema Neo4j cree :
  - Noeud  : Ticket (ticket_id, numero_fe, titre, detail, ...)
  - Noeuds : Personne (login), Application (name), Projet (projet_id)
  - Relations :
      (Ticket)-[:EMIS_PAR]     ->(Personne)
      (Ticket)-[:TRAITE_PAR]   ->(Personne)
      (Ticket)-[:DANS_APPLICATION]->(Application)
      (Ticket)-[:DANS_PROJET]  ->(Projet)
      (Ticket)-[:ENFANT_DE]    ->(Ticket)  si parent existe deja

Qdrant : chunks depuis titre / detail / resume_natif / llm.resume,
tous tagges source_module="intraknow_tickets" pour le filtrage retrieval.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from qdrant_client.http.models import PointStruct

from clients import Neo4jClient, OllamaClient, QdrantWrapper, INCIDENT_CHUNKS_COLLECTION
from models_tickets import TicketCanonique


logger = logging.getLogger(__name__)

# Champs courts vectorises en un seul point (champ, longueur_minimale).
# detail / cause_nc ne sont PLUS ici : ils sont chunkes semantiquement
# (1 vecteur par entree de fil) via ticket.detail_chunks / cause_chunks.
CHAMPS_VECTORISES = [
    ("titre",        10),
    ("resume_natif", 50),
]

# Longueur minimale d'un chunk pour etre vectorise
CHUNK_MIN_CHARS = 25


def bootstrap_neo4j_schema(neo4j: Neo4jClient) -> None:
    """Cree les contraintes Neo4j pour Ticket (idempotent)."""
    neo4j.execute(
        "CREATE CONSTRAINT ticket_id_unique IF NOT EXISTS "
        "FOR (t:Ticket) REQUIRE t.ticket_id IS UNIQUE"
    )
    neo4j.execute(
        "CREATE CONSTRAINT ticket_numero_fe_unique IF NOT EXISTS "
        "FOR (t:Ticket) REQUIRE t.numero_fe IS UNIQUE"
    )
    logger.info("Schema Neo4j Ticket : contraintes verifiees")


def link_tickets_hierarchie(neo4j: Neo4jClient) -> int:
    """2e passe : relie (Ticket)-[:ENFANT_DE]->(Ticket) une fois tous les
    tickets en base (corrige les liens manques quand l'enfant est ingere
    avant son parent). Idempotent. Necessite parent_numero_fe persiste.
    """
    result = neo4j.run(
        """
        MATCH (c:Ticket) WHERE c.parent_numero_fe IS NOT NULL
        MATCH (p:Ticket {numero_fe: c.parent_numero_fe})
        WHERE p <> c
        MERGE (c)-[:ENFANT_DE]->(p)
        RETURN count(*) AS c
        """
    )
    n = result[0]["c"] if result else 0
    logger.info("Liens Ticket -> parent (ENFANT_DE, 2e passe) : %d", n)
    return n


def get_enriched_ticket_ids(neo4j: Neo4jClient) -> set[str]:
    """Retourne les ticket_id deja enrichis par le LLM (llm_resume present).

    Sert a la reprise d'un run long : on saute ce qui est deja fait.
    """
    result = neo4j.run(
        "MATCH (t:Ticket) WHERE t.llm_resume IS NOT NULL RETURN t.ticket_id AS id"
    )
    return {r["id"] for r in result if r.get("id")}


def write_to_neo4j(ticket: TicketCanonique, neo4j: Neo4jClient) -> None:
    """MERGE le noeud Ticket et ses relations dans Neo4j."""
    ticket.last_indexed_at = datetime.now(timezone.utc).isoformat()

    props: dict[str, Any] = {
        "ticket_id": ticket.ticket_id,
        "numero_fe": ticket.numero_fe,
        "source_module": ticket.source_module,
        "titre": ticket.titre,
        "detail": ticket.detail,
        "resume_natif": ticket.resume_natif,
        "date_nc": ticket.date_nc,
        "type_nc": ticket.type_nc,
        "type_label": ticket.type_label,
        "type_code": ticket.type_code,
        "importance": ticket.importance,
        "etat": ticket.etat,
        "etape_label": ticket.etape_label,
        "abbr": ticket.abbr,
        "etape": ticket.etape,
        "archive_nc": ticket.archive_nc,
        "branche_developpement": ticket.branche_developpement,
        "priorite_projet": ticket.priorite_projet,
        "cause_nc": ticket.cause_nc,
        "version_effective": ticket.version_effective,
        "version_souhaitee": ticket.version_souhaitee,
        "site_application": ticket.site_application,
        "projet_id": ticket.projet_id,
        "projet_nom": ticket.projet_nom,
        "structure": ticket.structure,
        "urgence": ticket.urgence,
        "individu": ticket.individu,
        "parent_numero_fe": ticket.parent_numero_fe,
        "emetteur_login": ticket.emetteur_login,
        "societe_id": ticket.societe_id,
        "is_test_data": ticket.is_test_data,
        "last_indexed_at": ticket.last_indexed_at,
    }

    if ticket.llm:
        props["llm_resume"] = ticket.llm.resume
        props["llm_domaine_technique"] = ticket.llm.domaine_technique
        props["llm_model"] = ticket.llm.model_used

    neo4j.execute(
        """
        MERGE (t:Ticket {ticket_id: $ticket_id})
        SET t += $props
        """,
        ticket_id=ticket.ticket_id,
        props=props,
    )

    if ticket.emetteur_login:
        neo4j.execute(
            """
            MERGE (p:Personne {login: $login})
            WITH p
            MATCH (t:Ticket {ticket_id: $ticket_id})
            MERGE (t)-[:EMIS_PAR]->(p)
            """,
            login=ticket.emetteur_login,
            ticket_id=ticket.ticket_id,
        )

    if ticket.resp_traitement_login:
        neo4j.execute(
            """
            MERGE (p:Personne {login: $login})
            WITH p
            MATCH (t:Ticket {ticket_id: $ticket_id})
            MERGE (t)-[:TRAITE_PAR]->(p)
            """,
            login=ticket.resp_traitement_login,
            ticket_id=ticket.ticket_id,
        )

    if ticket.site_application:
        neo4j.execute(
            """
            MERGE (a:Application {name: $name})
            WITH a
            MATCH (t:Ticket {ticket_id: $ticket_id})
            MERGE (t)-[:DANS_APPLICATION]->(a)
            """,
            name=ticket.site_application,
            ticket_id=ticket.ticket_id,
        )

    if ticket.projet_id:
        neo4j.execute(
            """
            MERGE (proj:Projet {projet_id: $projet_id})
            SET proj.titre = coalesce($projet_nom, proj.titre)
            WITH proj
            MATCH (t:Ticket {ticket_id: $ticket_id})
            MERGE (t)-[:DANS_PROJET]->(proj)
            """,
            projet_id=ticket.projet_id,
            projet_nom=ticket.projet_nom,
            ticket_id=ticket.ticket_id,
        )

    if ticket.parent_numero_fe:
        neo4j.execute(
            """
            MATCH (parent:Ticket {numero_fe: $parent_fe})
            MATCH (child:Ticket {ticket_id: $ticket_id})
            MERGE (child)-[:ENFANT_DE]->(parent)
            """,
            parent_fe=ticket.parent_numero_fe,
            ticket_id=ticket.ticket_id,
        )


def write_to_qdrant(
    ticket: TicketCanonique,
    qdrant: QdrantWrapper,
    ollama: OllamaClient,
) -> int:
    """Vectorise et upsert les chunks du ticket dans Qdrant.

    Retourne le nombre de chunks upsertes.
    """
    points: list[PointStruct] = []

    base_payload = {
        "ticket_id": ticket.ticket_id,
        "numero_fe": ticket.numero_fe,
        "source_module": ticket.source_module,
        "type_nc": ticket.type_nc,
        "site_application": ticket.site_application,
        "is_test_data": ticket.is_test_data,
    }

    # Champs courts : un point chacun
    for champ, min_len in CHAMPS_VECTORISES:
        contenu = getattr(ticket, champ, None)
        if not contenu or len(contenu) < min_len:
            continue
        vector = ollama.embed(contenu)
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{ticket.ticket_id}_{champ}"))
        payload = {**base_payload, "field_canonical": champ, "text": contenu}
        points.append(PointStruct(id=point_id, vector=vector, payload=payload))

    # detail / cause_nc : un point par chunk semantique (entree de fil ou bloc)
    for field_name, chunks in (("detail", ticket.detail_chunks), ("cause_nc", ticket.cause_chunks)):
        for chunk in chunks:
            texte = f"{chunk.heading}\n{chunk.text}" if chunk.heading else chunk.text
            if not texte or len(texte) < CHUNK_MIN_CHARS:
                continue
            vector = ollama.embed(texte)
            point_id = str(uuid.uuid5(
                uuid.NAMESPACE_DNS, f"{ticket.ticket_id}_{field_name}_{chunk.index}"
            ))
            payload = {
                **base_payload,
                "field_canonical": field_name,
                "text": texte,
                "chunk_index": chunk.index,
                "chunk_kind": chunk.kind,
                "chunk_author": chunk.author,
                "chunk_date": chunk.date,
            }
            points.append(PointStruct(id=point_id, vector=vector, payload=payload))

    if ticket.llm and ticket.llm.resume:
        resume = ticket.llm.resume
        vector = ollama.embed(resume)
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{ticket.ticket_id}_llm_resume"))
        payload = {**base_payload, "field_canonical": "llm_resume", "text": resume}
        points.append(PointStruct(id=point_id, vector=vector, payload=payload))

    qdrant.upsert_points(points)
    return len(points)


def load_one(
    ticket: TicketCanonique,
    neo4j: Neo4jClient,
    qdrant: QdrantWrapper,
    ollama: OllamaClient,
) -> int:
    """Ecrit un ticket dans Neo4j et Qdrant. Retourne le nombre de chunks Qdrant."""
    write_to_neo4j(ticket, neo4j)
    n_chunks = write_to_qdrant(ticket, qdrant, ollama)
    return n_chunks
