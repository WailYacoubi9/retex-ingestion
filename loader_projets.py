"""
Loader Neo4j pour les projets client intra'know.

Schema :
  - Noeud Projet (projet_id [cle], titre, nom, statut, processus, ...)
  - Noeud Personne (nom)  : responsable projet
  - Noeud Client (nom)
  - Relations :
      (Ticket)-[:DANS_PROJET]->(Projet)        etablie PAR TITRE
      (Projet)-[:RESPONSABLE]->(Personne)      via resp (nom complet)
      (Projet)-[:POUR_CLIENT]->(Client)        via client
      (Projet)-[:SOUS_PROJET_DE]->(Projet)     via projet_parent (== titre du parent)

Le noeud Projet est partage avec le pipeline tickets (meme cle projet_id).
Cet ingest enrichit donc les noeuds existants au lieu d'en creer des doublons.

NB : les Personne responsables sont keyees par NOM (ex "FRINAULT Olivier"),
alors que les Personne emetteurs/traitants des tickets sont keyees par LOGIN
(ex "ofrinault"). Aucune jointure fiable nom<->login n'existe dans les exports
(derivation testee : 5/19). Ces deux familles de Personne restent donc distinctes
tant qu'une table de correspondance login<->nom n'est pas fournie.
"""
from __future__ import annotations

import logging
from typing import Any

from clients import Neo4jClient
from models_projets import ProjetCanonique

logger = logging.getLogger(__name__)


def bootstrap_neo4j_schema(neo4j: Neo4jClient) -> None:
    """Cree contrainte (projet_id) + index (titre) pour Projet. Idempotent."""
    neo4j.execute(
        "CREATE CONSTRAINT projet_id_unique IF NOT EXISTS "
        "FOR (p:Projet) REQUIRE p.projet_id IS UNIQUE"
    )
    neo4j.execute(
        "CREATE INDEX projet_titre_idx IF NOT EXISTS "
        "FOR (p:Projet) ON (p.titre)"
    )
    neo4j.execute(
        "CREATE CONSTRAINT client_nom_unique IF NOT EXISTS "
        "FOR (c:Client) REQUIRE c.nom IS UNIQUE"
    )
    logger.info("Schema Neo4j Projet : contraintes + index verifies")


def write_to_neo4j(projet: ProjetCanonique, neo4j: Neo4jClient) -> None:
    """MERGE le noeud Projet (par projet_id) et set ses proprietes."""
    props: dict[str, Any] = {
        "titre": projet.titre,
        "nom": projet.nom,
        "processus": projet.processus,
        "statut": projet.statut,
        "actif": projet.actif,
        "resp": projet.resp,
        "equipe": projet.equipe,
        "priorite": projet.priorite,
        "date_creation": projet.date_creation,
        "date_debut": projet.date_debut,
        "date_fin_prevue": projet.date_fin_prevue,
        "client": projet.client,
        "plateforme": projet.plateforme,
        "projet_parent": projet.projet_parent,
        "temps_prevu": projet.temps_prevu,
        "temps_consomme": projet.temps_consomme,
        "lien_drive": projet.lien_drive,
        "source_module": projet.source_module,
    }

    neo4j.execute(
        """
        MERGE (p:Projet {projet_id: $projet_id})
        SET p += $props
        """,
        projet_id=projet.projet_id,
        props=props,
    )

    # Responsable : Personne keyee par NOM (distincte des Personne-login des tickets)
    if projet.resp:
        neo4j.execute(
            """
            MERGE (pers:Personne {nom: $nom})
            WITH pers
            MATCH (p:Projet {projet_id: $projet_id})
            MERGE (p)-[:RESPONSABLE]->(pers)
            """,
            nom=projet.resp,
            projet_id=projet.projet_id,
        )

    # Client
    if projet.client:
        neo4j.execute(
            """
            MERGE (c:Client {nom: $nom})
            WITH c
            MATCH (p:Projet {projet_id: $projet_id})
            MERGE (p)-[:POUR_CLIENT]->(c)
            """,
            nom=projet.client,
            projet_id=projet.projet_id,
        )


def get_referenced_titres(neo4j: Neo4jClient) -> set[str]:
    """Retourne l'ensemble des titres de projets reellement references par un ticket.

    Base sur ticket.projet_nom (== titre). Necessite que les tickets soient
    deja ingeres. Sert a restreindre l'ingestion aux projets mentionnes.
    """
    result = neo4j.run(
        """
        MATCH (t:Ticket)
        WHERE t.projet_nom IS NOT NULL
        RETURN DISTINCT t.projet_nom AS titre
        """
    )
    titres = {r["titre"] for r in result if r.get("titre")}
    logger.info("Projets references par des tickets : %d", len(titres))
    return titres


def link_projet_hierarchie(neo4j: Neo4jClient) -> int:
    """Relie chaque projet a son parent via projet_parent (== titre du parent).

    Fait en 2e passe (apres ecriture de tous les projets) pour ne pas dependre
    de l'ordre. MATCH (pas MERGE) sur le parent : pas de creation de stub.

    Returns:
        Le nombre de relations SOUS_PROJET_DE creees.
    """
    result = neo4j.run(
        """
        MATCH (child:Projet)
        WHERE child.projet_parent IS NOT NULL
        MATCH (parent:Projet {titre: child.projet_parent})
        WHERE parent <> child
        MERGE (child)-[:SOUS_PROJET_DE]->(parent)
        RETURN count(*) AS c
        """
    )
    n = result[0]["c"] if result else 0
    logger.info("Liens Projet -> Projet parent (SOUS_PROJET_DE) : %d", n)
    return n


def link_tickets_to_projets(neo4j: Neo4jClient) -> int:
    """Relie les tickets aux projets PAR TITRE (ticket.projet_nom == projet.titre).

    Idempotent (MERGE). A appeler apres ingestion des tickets ET des projets.

    Returns:
        Le nombre de relations DANS_PROJET (re)creees.
    """
    result = neo4j.run(
        """
        MATCH (t:Ticket)
        WHERE t.projet_nom IS NOT NULL
        MATCH (p:Projet {titre: t.projet_nom})
        MERGE (t)-[:DANS_PROJET]->(p)
        RETURN count(*) AS c
        """
    )
    n = result[0]["c"] if result else 0
    logger.info("Liens Ticket -> Projet (par titre) : %d", n)
    return n
