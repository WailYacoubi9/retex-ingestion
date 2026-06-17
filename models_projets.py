"""
Modele canonique pour les projets client intra'know.

Source : export CSV des projets (yieloo_export_projet_client_*.csv).
Le noeud Projet est partage avec le pipeline tickets : la cle d'identite
est projet_id (= colonne [identifiant] du CSV), qui correspond au
projet_ticket._id du JSON des tickets (verifie : 1893/1895 concordances).
L'export projets enrichit donc les memes noeuds avec titre + metadonnees.

Le lien Ticket -> Projet est etabli PAR TITRE (ticket.projet_nom == projet.titre),
correspondance verifiee a 212/212 sur les titres utilises par les tickets.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ProjetCanonique:
    """Format pivot pour un projet client intra'know.

    Attributes:
        projet_id: Identifiant du projet (colonne [identifiant]). Cle Neo4j.
        titre: Titre du projet (colonne projet_client_titre). Cle de jointure
            avec les tickets (== ticket.projet_nom).
        nom: Nom du projet (colonne projet_client_libelle).
        processus, statut, actif, resp, equipe, priorite : metadonnees.
        date_creation, date_debut, date_fin_prevue : dates.
        client, plateforme, projet_parent : liaisons.
        temps_prevu, temps_consomme : suivi de charge (en jours).
        lien_drive : URL du dossier Drive.
    """

    projet_id: str
    titre: str
    nom: Optional[str] = None
    processus: Optional[str] = None
    statut: Optional[str] = None
    actif: Optional[str] = None
    resp: Optional[str] = None
    equipe: Optional[str] = None
    priorite: Optional[str] = None
    date_creation: Optional[str] = None
    date_debut: Optional[str] = None
    date_fin_prevue: Optional[str] = None
    client: Optional[str] = None
    plateforme: Optional[str] = None
    projet_parent: Optional[str] = None
    temps_prevu: Optional[str] = None
    temps_consomme: Optional[str] = None
    lien_drive: Optional[str] = None
    source_module: str = "intraknow_projets"
