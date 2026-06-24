"""MODULE AUTO-GÉNÉRÉ par scripts/codegen_model.py — NE PAS ÉDITER À LA MAIN.
Source : schéma « incident_securite_v2 ». Régénérer après chaque édition du YAML."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, ClassVar, Optional

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

    numero_fe: Optional[str] = None  # Référence unique de la fiche (identité). Ex : FNE/26/0245.
    titre: Optional[str] = None  # Titre court de l'incident.
    detail: Optional[str] = None  # Narratif principal de l'événement.
    type_fiche: Optional[str] = None  # Type de fiche (FNE à 99%).
    etat: Optional[str] = None  # État de la fiche : Clos / Actif / Classé sans suite.
    etape: Optional[str] = None  # Workflow : Valider / Agir / Analyser / Identifier.
    statut_ecc: Optional[str] = None  # Statut ECCAIRS : Clos sommaire / Clos détaillé / Ouvert.
    aerodrome: Optional[str] = None  # Aérodrome : LYS (Lyon Saint-Exupéry) ou Lyon Bron.
    severite: Optional[str] = None  # Niveau de risque ECCAIRS (remplace la sévérité LLM). Complet à 99.8%
    classification: Optional[str] = None  # Incident / Occurrence sans effet / Incident sérieux / Accident.
    condition_lumineuse: Optional[str] = None  # Condition lumineuse : Jour / Nuit.
    processus: Optional[str] = None  # Processus interne (PM2, PM4, PM5...).
    categorie_id: Optional[str] = None  # Identifiant de catégorie d'événement.
    organisations_informees: Optional[str] = None  # Organisations informées (DSAC dans la quasi-totalité).
    action_corrective: Optional[str] = None  # Action corrective immédiate (massivement '0' à filtrer).
    analyse_chaud: Optional[str] = None  # Analyse terrain immédiate.
    desc_cause_1: Optional[str] = None  # Cause principale rédigée (analyse 5M).
    desc_cause_3: Optional[str] = None  # Cause complémentaire (5M).
    desc_cause_5: Optional[str] = None  # Cause complémentaire (5M).
    detail_verification: Optional[str] = None  # Détail de la vérification (filtrer les '0').
    date_creation: Optional[datetime] = None  # Date de saisie de la fiche.
    date_evenement: Optional[datetime] = None  # Date réelle de l'événement.
    heure_evenement: Optional[time] = None  # Heure locale de l'événement.
    date_maj: Optional[datetime] = None  # Date de dernière mise à jour de la fiche.
    presence_blesses: Optional[bool] = None  # Présence de blessés (Oui* -> vrai).
    analyse_causes_faite: Optional[bool] = None  # Une analyse des causes a-t-elle été faite.
    traitement_termine: Optional[bool] = None  # Traitement de la fiche terminé.
    est_significatif: Optional[bool] = None  # Événement significatif (analyse détaillée) — cas graves.
    est_rex: Optional[bool] = None  # Fiche marquée retour d'expérience.
    actions_efficaces: Optional[bool] = None  # Actions correctives jugées efficaces.

    # --- relations ---
    entites: list[EntiteLiee] = field(default_factory=list)

    # --- techniques ---
    resume_llm: Optional[str] = None
    llm_model: Optional[str] = None
    is_test_data: bool = False
    last_indexed_at: Optional[str] = None

    CHAMPS_EMBEDDING = ("titre", "detail", "action_corrective", "analyse_chaud", "desc_cause_1", "desc_cause_3", "desc_cause_5", "detail_verification",)

    _CHAMPS_MIN_LENGTH: ClassVar[dict[str, int]] = {
        "titre": 5,
        "detail": 20,
        "action_corrective": 20,
        "analyse_chaud": 20,
        "desc_cause_1": 15,
        "desc_cause_3": 15,
        "desc_cause_5": 15,
        "detail_verification": 20,
    }

    def textes_pour_embedding(self) -> dict[str, str]:
        """Narratifs assez longs pour vectorisation, avec seuils par champ."""
        out: dict[str, str] = {}
        for nom in self.CHAMPS_EMBEDDING:
            v = getattr(self, nom, None)
            min_len = self._CHAMPS_MIN_LENGTH.get(nom, 20)
            if isinstance(v, str) and len(v.strip()) >= min_len:
                out[nom] = v.strip()
        return out
