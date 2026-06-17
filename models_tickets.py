"""
Modeles canoniques pour le module Tickets intra'know.

Le format pivot TicketCanonique est l'interface entre :
  - parser_tickets.py qui lit le JSON intra'know
  - llm_enricher_tickets.py qui attache un resume + classification LLM
  - loader_tickets.py qui ecrit dans Neo4j + Qdrant

Convention d'identifiant : ticket_id est un UUID v5 stable derive
du numero_fe. Ingerer 10 fois le meme ticket produit toujours le meme
ID, ce qui garantit l'idempotence du MERGE Neo4j.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional


TICKETS_NAMESPACE_UUID = uuid.UUID("b8e5d3a1-4f6c-5b2e-9d1a-3c8e7f4a6b5d")


def make_ticket_uuid(numero_fe: str) -> str:
    """Genere un UUID v5 stable a partir du numero_fe."""
    if not numero_fe:
        raise ValueError("numero_fe ne peut pas etre vide")
    return str(uuid.uuid5(TICKETS_NAMESPACE_UUID, str(numero_fe)))


@dataclass
class LLMResumeTicket:
    """Sortie LLM minimale (design lean).

    Le LLM ne genere QUE ce que la source ne fournit pas :
      - resume : synthese lisible du fil HTML bruite (detail_nc + cause_nc)
      - domaine_technique : seul axe de classif absent du CSV/JSON

    Le reste (type, criticite/importance, statut/etape, urgence) vient des
    champs factuels du ticket (CSV/JSON) -> plus fiable et gratuit.
    """
    resume: str
    domaine_technique: str
    model_used: str


@dataclass
class TicketCanonique:
    """Format pivot pour un ticket intra'know.

    Tous les champs textuels (titre, detail, resume_natif) sont
    supposes deja nettoyes de leur HTML par le parser.
    """

    # Identification
    numero_fe: str
    ticket_id: str
    source_module: str = "intraknow_tickets"

    # Contenu narratif (clean HTML)
    titre: str = ""
    detail: str = ""
    resume_natif: Optional[str] = None
    cause_nc: Optional[str] = None

    # Unites semantiques (1 par entree de fil / bloc) pour l'embedding granulaire.
    # Produites par html_chunker depuis le HTML brut de detail_nc / cause_nc.
    # Liste de html_chunker.Chunk (typage souple pour eviter un import circulaire).
    detail_chunks: list = field(default_factory=list)
    cause_chunks: list = field(default_factory=list)

    # Metadonnees
    date_nc: Optional[str] = None
    etape: Optional[int] = None
    archive_nc: Optional[int] = None
    abbr: Optional[str] = None
    type_nc: Optional[str] = None
    # Champs factuels remplacant les classifs LLM (issus du CSV/JSON)
    importance: Optional[str] = None    # ex "Modere" (CSV Importance)
    etat: Optional[str] = None          # Actif / Clos (CSV etat)
    etape_label: Optional[str] = None   # ex "Traitement (termine)" (CSV etape)
    id_type: Optional[int] = None
    id_unite: Optional[int] = None
    branche_developpement: Optional[str] = None
    priorite_projet: Optional[str] = None
    version_effective: Optional[str] = None
    version_souhaitee: Optional[str] = None

    # Liaisons structurelles (alimentent les relations Neo4j)
    emetteur_login: Optional[str] = None
    emetteur_id: Optional[int] = None
    resp_traitement_login: Optional[str] = None
    societe_id: Optional[int] = None
    site_application: Optional[str] = None
    projet_id: Optional[str] = None
    # Champs absents du JSON intra'know, injectes depuis l'export CSV
    # (jointure sur numero_fe). projet_nom complete projet_id qui n'est
    # qu'un identifiant opaque. Voir enrich_tickets_csv.py.
    projet_nom: Optional[str] = None
    structure: Optional[str] = None
    urgence: Optional[str] = None
    individu: Optional[str] = None
    type_label: Optional[str] = None
    type_code: Optional[str] = None
    version_souhaitee_id: Optional[str] = None
    developpeur_login: Optional[str] = None
    parent_numero_fe: Optional[str] = None

    # Enrichissement LLM (attache apres parsing)
    llm: Optional[LLMResumeTicket] = None

    # Techniques
    is_test_data: bool = False
    last_indexed_at: Optional[str] = None

    def has_narrative_content(self) -> bool:
        """Retourne True si le ticket a assez de contenu pour l'enrichissement LLM."""
        titre_len = len(self.titre or "")
        detail_len = len(self.detail or "")
        return titre_len + detail_len >= 80
