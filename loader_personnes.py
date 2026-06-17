"""
Loader des collaborateurs intra'know dans Neo4j.

Source : data/personnes_mapping.csv (login;nom), saisi manuellement a partir
de l'annuaire interne. Couvre 100% des resp_traitement_nc des tickets.

Strategie : on n'introduit PAS de nouveau type de noeud. Les collaborateurs
sont les noeuds Personne deja keyes par login (ceux que le loader tickets
cree pour emetteur_nc / resp_traitement_nc via EMIS_PAR / TRAITE_PAR). On les
ENRICHIT simplement avec :
  - p.nom            : nom complet ("FRINAULT Olivier")
  - label :Collaborateur (label secondaire, en plus de :Personne)
  - p.is_collaborateur = true

Ainsi les relations tickets existantes pointent deja vers ces memes noeuds,
sans recablage. Un login present dans le mapping mais absent des tickets cree
quand meme son noeud (collaborateur connu sans ticket).
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path

from clients import Neo4jClient

logger = logging.getLogger(__name__)


def bootstrap_neo4j_schema(neo4j: Neo4jClient) -> None:
    """Contrainte d'unicite sur Personne.login (idempotent).

    NB : les contraintes d'unicite Neo4j ignorent les valeurs nulles, donc
    les Personne sans login (ex. responsables projet keyes par nom) ne sont
    pas affectees.
    """
    neo4j.execute(
        "CREATE CONSTRAINT personne_login_unique IF NOT EXISTS "
        "FOR (p:Personne) REQUIRE p.login IS UNIQUE"
    )
    logger.info("Schema Neo4j Personne : contrainte login verifiee")


def load_mapping(mapping_csv: Path) -> dict[str, str]:
    """Lit le CSV login;nom -> dict {login: nom}. Encodage UTF-8, separateur ';'."""
    mapping: dict[str, str] = {}
    with mapping_csv.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter=";"):
            login = (row.get("login") or "").strip()
            nom = (row.get("nom") or "").strip()
            if login and nom:
                mapping[login] = nom
    logger.info("Mapping collaborateurs charge : %d entrees", len(mapping))
    return mapping


def load_collaborateurs(neo4j: Neo4jClient, mapping: dict[str, str]) -> int:
    """Cree/enrichit un noeud Personne:Collaborateur par login du mapping.

    Returns:
        Le nombre de collaborateurs ecrits.
    """
    n = 0
    for login, nom in mapping.items():
        neo4j.execute(
            """
            MERGE (p:Personne {login: $login})
            SET p.nom = $nom,
                p.is_collaborateur = true,
                p:Collaborateur
            """,
            login=login,
            nom=nom,
        )
        n += 1
    logger.info("Collaborateurs ecrits : %d", n)
    return n
