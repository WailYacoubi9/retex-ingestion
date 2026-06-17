"""
Extracteurs déterministes : payload Postman -> IncidentCanonique.
Un extracteur par type de _module.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime
from typing import Any, Callable

from dateutil import parser as dtparser

from models import (
    IncidentCanonique, PersonneRef, ReferentielRef,
)

logger = logging.getLogger(__name__)


# =====================================================================
# Helpers
# =====================================================================

def stable_uuid(source_ref: str, content_hint: str = "") -> str:
    """Génère un UUID v5 stable à partir de la source.
    Permet de rejouer l'ingestion sans dupliquer."""
    seed = f"{source_ref}|{content_hint}"
    return str(uuid.uuid5(uuid.NAMESPACE_OID, seed))


def parse_date(value: Any) -> datetime | None:
    """Parse permissif d'une date. Retourne None si non parsable."""
    if not value or not isinstance(value, str):
        return None
    if "{{" in value:  # template Postman non résolu
        return None
    try:
        return dtparser.parse(value)
    except (ValueError, TypeError, OverflowError):
        return None


def clean_text(value: Any) -> str | None:
    """Nettoie une string. Retourne None si vide ou template Postman."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.startswith("{{") and cleaned.endswith("}}"):
        return None
    return cleaned


def normalize_person_name(name: str) -> str:
    """Normalise un nom de personne pour dédoublonnage."""
    return name.strip().lower() if name else ""


def extract_ref_single(data: dict | None, family: str, role: str) -> list[ReferentielRef]:
    """Extrait un référentiel unique de forme {_code, _label, _id, ...}."""
    if not isinstance(data, dict):
        return []
    code = data.get("_code")
    if not code:
        return []
    return [ReferentielRef(
        family=family,
        code=str(code),
        label=data.get("_label"),
        code_externe=data.get("_code_externe") or None,
        id_source=data.get("_id") if isinstance(data.get("_id"), int) else None,
        role=role,
    )]


def extract_ref_list(data: Any, family: str, role: str) -> list[ReferentielRef]:
    """Extrait une liste de référentiels."""
    if not isinstance(data, list):
        return []
    refs = []
    for item in data:
        refs.extend(extract_ref_single(item, family, role))
    return refs


# =====================================================================
# Extracteurs par type
# =====================================================================

# Pour q_incident_securite : mapping champ source -> (family, role, is_list)
SECURITE_REFERENTIELS: dict[str, tuple[str, str, bool]] = {
    "contxtcondmeteo": ("meteo", "condition_meteo", True),
    "contxtetatsol": ("etat_sol", "etat_sol", True),
    "contxtlorsdejournuit": ("moment_journee", "moment_journee", False),
    "securitelieu1": ("lieu_securite", "lieu_primaire", False),
    "securitelieu2": ("lieu_securite", "lieu_secondaire", False),
    "securitetypeevnt0": ("type_evenement", "type_evt_niveau_0", False),
    "securitetypeevnt1": ("type_evenement", "type_evt_niveau_1", False),
    "securitetypeevnt2": ("type_evenement", "type_evt_niveau_2", False),
    "graviteecc": ("gravite", "gravite", False),
    "contributionatm": ("contribution_atm", "contribution_atm", False),
    "effetsurleserviceatm": ("effet_service_atm", "effet_service", False),
    "notifiant": ("notifiant", "notifiant", False),
    "type_de_no": ("type_notification", "type_notification", False),
    "organisationsinformees": ("organisation", "organisation_informee", True),
}


def extract_q_incident_securite(payload: dict, source_ref: str) -> IncidentCanonique:
    """Extracteur spécialisé pour q_incident_securite (FNE aéronautique)."""

    incident_id = stable_uuid(source_ref, payload.get("titre_nc", ""))

    # Personnes
    personnes: list[PersonneRef] = []
    if emetteur := clean_text(payload.get("emetteur_nc")):
        personnes.append(PersonneRef(
            name=normalize_person_name(emetteur),
            display_name=emetteur,
            role="emetteur",
        ))
    if resp := clean_text(payload.get("resp_traitement_nc")):
        personnes.append(PersonneRef(
            name=normalize_person_name(resp),
            display_name=resp,
            role="resp_traitement",
        ))

    # Référentiels
    referentiels: list[ReferentielRef] = []
    for field, (family, role, is_list) in SECURITE_REFERENTIELS.items():
        value = payload.get(field)
        if is_list:
            referentiels.extend(extract_ref_list(value, family, role))
        else:
            referentiels.extend(extract_ref_single(value, family, role))

    return IncidentCanonique(
        incident_id=incident_id,
        source_type="q_incident_securite",
        source_ref=source_ref,
        titre=clean_text(payload.get("titre_nc")),
        detail=clean_text(payload.get("detail_nc")),
        causes_presumees=clean_text(payload.get("causespresumees")),
        analyse_causes=clean_text(payload.get("analysedescausessuppecc")),
        precision_lieu=clean_text(payload.get("precisionsurlelieu"))
                       or clean_text(payload.get("contxtprecisionsmeteo")),
        date_evenement=parse_date(payload.get("date_evenement")),
        date_creation=parse_date(payload.get("date_nc")),
        type_nc=clean_text(payload.get("type_nc")),
        site_application=clean_text(payload.get("site_application")),
        personnes=personnes,
        referentiels=referentiels,
    )


def extract_q_incident_ticket(payload: dict, source_ref: str) -> IncidentCanonique:
    """Extracteur pour q_incident_ticket (ticket simple)."""

    incident_id = stable_uuid(source_ref, payload.get("titre_nc", ""))

    personnes: list[PersonneRef] = []
    if emetteur := clean_text(payload.get("emetteur_nc")):
        personnes.append(PersonneRef(
            name=normalize_person_name(emetteur),
            display_name=emetteur,
            role="emetteur",
        ))
    if resp := clean_text(payload.get("resp_traitement_nc")):
        personnes.append(PersonneRef(
            name=normalize_person_name(resp),
            display_name=resp,
            role="resp_traitement",
        ))

    return IncidentCanonique(
        incident_id=incident_id,
        source_type="q_incident_ticket",
        source_ref=source_ref,
        titre=clean_text(payload.get("titre_nc")),
        detail=clean_text(payload.get("detail_nc")) or clean_text(payload.get("demande")),
        date_evenement=parse_date(payload.get("date_nc")),
        type_nc=clean_text(payload.get("type_nc")),
        site_application=clean_text(payload.get("site_application")),
        personnes=personnes,
        referentiels=[],  # tickets n'ont pas de référentiels riches
    )


def extract_q_incident_generic(payload: dict, source_ref: str) -> IncidentCanonique:
    """Extracteur générique pour q_incident et q_incident_incident15.
    Moins riche, on récupère ce qui est commun."""

    incident_id = stable_uuid(source_ref, str(payload.get("_id", "")))

    personnes: list[PersonneRef] = []
    if emetteur := clean_text(payload.get("emetteur_nc")):
        personnes.append(PersonneRef(
            name=normalize_person_name(emetteur),
            display_name=emetteur,
            role="emetteur",
        ))

    # Certains payloads incident15 ont des référentiels similaires à securite
    referentiels: list[ReferentielRef] = []
    for field, (family, role, is_list) in SECURITE_REFERENTIELS.items():
        value = payload.get(field)
        if is_list:
            referentiels.extend(extract_ref_list(value, family, role))
        else:
            referentiels.extend(extract_ref_single(value, family, role))

    # Détecter le type source précis depuis _module si disponible
    source_type = payload.get("_module", "q_incident")

    return IncidentCanonique(
        incident_id=incident_id,
        source_type=source_type,
        source_ref=source_ref,
        titre=clean_text(payload.get("titre_nc")),
        detail=clean_text(payload.get("detail_nc")),
        causes_presumees=clean_text(payload.get("causespresumees")),
        precision_lieu=clean_text(payload.get("precisionsurlelieu")),
        date_evenement=parse_date(payload.get("date_evenement")) or parse_date(payload.get("date_nc")),
        type_nc=clean_text(payload.get("type_nc")),
        site_application=clean_text(payload.get("site_application")),
        personnes=personnes,
        referentiels=referentiels,
    )


# =====================================================================
# Routeur
# =====================================================================

_EXTRACTORS: dict[str, Callable[[dict, str], IncidentCanonique]] = {
    "q_incident_securite": extract_q_incident_securite,
    "q_incident_ticket": extract_q_incident_ticket,
    "q_incident_incident15": extract_q_incident_generic,
    "q_incident": extract_q_incident_generic,
}


def extract_incident(payload: dict, source_type: str, source_ref: str) -> IncidentCanonique | None:
    """Route le payload vers le bon extracteur selon son type détecté."""
    extractor = _EXTRACTORS.get(source_type)
    if extractor is None:
        # Fallback : tenter detection via _module
        module = payload.get("_module", "")
        extractor = _EXTRACTORS.get(module)

    if extractor is None:
        logger.warning("No extractor for source_type=%s", source_type)
        return None

    try:
        return extractor(payload, source_ref)
    except Exception as e:
        logger.exception("Extraction failed for %s: %s", source_ref, e)
        return None