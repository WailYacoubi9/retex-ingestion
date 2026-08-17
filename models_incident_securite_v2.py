"""MODULE AUTO-GÉNÉRÉ par scripts/codegen_model.py — NE PAS ÉDITER À LA MAIN.
Source : schéma « incident_securite_v2 ». Régénérer après chaque édition du YAML."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, Optional

SOURCE_MODULE = "incident_securite_v2"
_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def make_uuid(numero_fe: str) -> str:
    """UUID v5 stable depuis l'identité (idempotence)."""
    if not numero_fe:
        raise ValueError("numero_fe ne peut pas être vide")
    return str(uuid.uuid5(_NS, f"{SOURCE_MODULE}:{numero_fe}"))

@dataclass
class EntiteLiee:
    """Nœud lié générique (Lieu, Compagnie, Societe...)."""
    noeud: str
    cle: str
    valeur: str
    relation: str


@dataclass
class IncidentSecuriteV2Canonique:
    """Modèle canonique « incident_securite_v2 » — généré depuis le schéma."""

    # --- identité ---
    incident_id: Optional[str] = None
    source_module: str = SOURCE_MODULE

    numero_fe: Optional[str] = None  # Référence unique de la fiche (identité). Format : FNE/AA/NNNN.
    titre: Optional[str] = None  # Titre court. ATTENTION : 2 554 fiches (28 %) partagent un titre stri
    detail: Optional[str] = None  # Narratif principal. Rempli 99,4 %, médiane 122 caractères. Utilité 0
    severite: Optional[str] = None  # Niveau de risque ECCAIRS. Rempli 99,8 %, utilité 0,63.
    classification: Optional[str] = None  # Incident / Occurrence sans effet / Incident sérieux / Accident. Util
    etape: Optional[str] = None  # Workflow : Valider (Terminé) / Agir / Analyser / Identifier. Utilité
    etat: Optional[str] = None  # Clos 98,4 % / Actif 1,2 % / Classé sans suite 0,5 %. Utilité 0,08 : 
    condition_lumineuse: Optional[str] = None  # Jour / Nuit. Rempli 47,1 %, entropie 0,73 — booléen bien équilibré, 
    aerodrome: Optional[str] = None  # LYS 94,7 % / Lyon Bron 5,3 %. Conservé pour isoler Bron ; à NE PAS v
    report_type: Optional[str] = None  # Marqueur de format de rapport, 2 modalités, rempli 59 %. Sert à dist
    type_fiche: Optional[str] = None  # Domaine de la fiche. CONSERVÉ malgré une entropie de 0,04 (98,6 % « 
    precisions_lieu: Optional[str] = None  # Point exact : « 35L », « 36L - MAN », « C83 », « D63 », « AD ». Remp
    cause_mo: Optional[str] = None  # Cause « Main d'œuvre » (facteur humain). 1 608 fiches, médiane 66 ca
    cause_methode: Optional[str] = None  # Cause « Méthodes » (procédure). 406 fiches, médiane 101 car — le tex
    cause_machine: Optional[str] = None  # Cause « Machines / équipement ». 992 fiches, médiane 41 car.
    cause_mp: Optional[str] = None  # Cause « Matières premières ». 17 fiches — marginal mais complète l'a
    cause_milieu: Optional[str] = None  # Cause « Milieu » (environnement, faune, météo). 849 fiches, médiane 
    cause_management: Optional[str] = None  # Cause « Management » (organisation, décision). 452 fiches, absent du
    facteur_mo: Optional[bool] = None  # Axe causal Main d'œuvre retenu. 17,9 % des fiches.
    facteur_methode: Optional[bool] = None  # Axe causal Méthodes retenu. 4,8 %.
    facteur_machine: Optional[bool] = None  # Axe causal Machines retenu. 12,2 %.
    facteur_mp: Optional[bool] = None  # Axe causal Matières premières retenu. 0,2 %.
    facteur_milieu: Optional[bool] = None  # Axe causal Milieu retenu. 10,8 %.
    facteur_management: Optional[bool] = None  # Axe causal Management retenu. 4,9 %.
    action_corrective: Optional[str] = None  # Action prise pendant l'événement. Rempli 36,8 %, médiane 46 car, uti
    premiere_analyse_terrain: Optional[str] = None  # Première analyse rédigée par l'agent au moment de l'événement, avant
    detail_verification: Optional[str] = None  # Détail de la vérification d'efficacité. Rempli 25,2 %, médiane 52 ca
    type_evenement_autre: Optional[str] = None  # Précision libre quand le type vaut « Autre, précisez : » (2ᵉ modalit
    immatriculation: Optional[str] = None  # Seule clé stable d'identification d'un appareil (« cet avion a-t-il 
    numero_vol: Optional[str] = None  # Numéro du vol. Rempli 22 %, formats hétérogènes (6374 / AF6145 / EJU
    concerne: Optional[str] = None  # Objet concerné (aéronef / véhicule / personne). Rempli 39,9 %, 3 mod
    type_materiel: Optional[str] = None  # Engin ou matériel de piste impliqué. Rempli 10,2 %, 396 valeurs, ent
    type_installation: Optional[str] = None  # Installation concernée. Rempli 3,4 %, 208 valeurs. Marginal mais bie
    autre_compagnie: Optional[str] = None  # Compagnie hors liste ECCAIRS, texte libre. Rempli 9,2 %, 145 valeurs
    compagnie_2: Optional[str] = None  # Compagnie du 2ᵉ aéronef. 1,4 %.
    type_aeronef_2: Optional[str] = None  # Type du 2ᵉ aéronef. 0,8 %.
    numero_vol_2: Optional[str] = None  # Vol du 2ᵉ aéronef. 1,4 %.
    phase_vol_2: Optional[str] = None  # Phase de vol du 2ᵉ aéronef. 1,4 %.
    conditions_meteo: Optional[str] = None  # Conditions météo. Rempli 1 %, 55 valeurs — trop peu couvert pour une
    date_creation: Optional[datetime] = None  # Date de saisie de la fiche.
    date_evenement: Optional[datetime] = None  # Date réelle de l'événement. C'est CE champ qui fait foi pour toute q
    heure_evenement: Optional[time] = None  # Heure locale. Rempli 63,9 % — permet les analyses par tranche horair
    date_maj: Optional[datetime] = None  # Dernière mise à jour de la fiche.
    presence_blesses: Optional[bool] = None  # Rempli sur 59 fiches (0,6 %). Les 4 modalités sont « Ne sais pas » 3
    est_significatif: Optional[bool] = None  # Événement significatif nécessitant une analyse détaillée. 0,9 %.
    est_rex: Optional[bool] = None  # Fiche marquée retour d'expérience. 0,2 %.
    actions_efficaces: Optional[bool] = None  # Efficacité constatée. Rempli 7,7 %, modalité unique « oui ». Il est 

    # --- relations ---
    entites: list[EntiteLiee] = field(default_factory=list)

    # --- techniques ---
    resume_llm: Optional[str] = None
    llm_model: Optional[str] = None
    is_test_data: bool = False
    last_indexed_at: Optional[str] = None

    CHAMPS_EMBEDDING = ("titre", "detail", "cause_mo", "cause_methode", "cause_machine", "cause_mp", "cause_milieu", "cause_management", "action_corrective", "premiere_analyse_terrain", "detail_verification", "type_evenement_autre",)

    def textes_pour_embedding(self, min_length: int = 20) -> dict[str, str]:
        """Narratifs assez longs pour vectorisation."""
        out: dict[str, str] = {}
        for nom in self.CHAMPS_EMBEDDING:
            v = getattr(self, nom, None)
            if isinstance(v, str) and len(v.strip()) >= min_length:
                out[nom] = v.strip()
        return out
