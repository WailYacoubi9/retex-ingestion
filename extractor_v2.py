"""
Extracteur generique pilote par YAML.

Transforme un payload brut (dict JSON) en IncidentCanonique en
appliquant les regles declarees dans un ModuleMapping.
"""
from __future__ import annotations

import logging
from datetime import datetime, time
from typing import Any, Optional

from dateutil import parser as date_parser

from models import (
    IncidentCanonique,
    PersonneRef,
    ReferentielRef,
    SocieteRef,
    make_incident_uuid,
)
from yaml_loader import (
    DateFieldMapping,
    DerivedFieldMapping,
    FieldMapping,
    ModuleMapping,
    ReferentielMapping,
)

logger = logging.getLogger(__name__)


# =====================================================================
# POINT D'ENTREE PRINCIPAL
# =====================================================================

def extract_incident(payload: dict, mapping: ModuleMapping) -> Optional[IncidentCanonique]:
    """Transforme un payload brut en IncidentCanonique.

    Utilisation : point d'entree de l'extracteur. Appele pour chaque
    incident a ingerer. Retourne None si extraction impossible (champs
    requis manquants).
    """
    # ID source obligatoire pour generer l'UUID stable
    source_id_field = _find_source_for_canonical(mapping, "incident_id_source")
    if not source_id_field:
        logger.error("Mapping invalide : pas de champ pour incident_id_source")
        return None

    source_id = payload.get(source_id_field)
    if source_id is None:
        logger.warning("Payload sans %s, skipping", source_id_field)
        return None

    incident_id = make_incident_uuid(mapping.module_name, str(source_id))

    # Construction de l'incident vide
    incident = IncidentCanonique(
        incident_id=incident_id,
        incident_id_source=str(source_id),
        source_module=mapping.module_name,
        last_indexed_at=datetime.utcnow().isoformat() + "Z",
    )

    # Application des regles dans l'ordre
    _apply_metier_fields(payload, mapping, incident)
    _apply_date_fields(payload, mapping, incident)
    _apply_derived_fields(payload, mapping, incident)
    _apply_societe(payload, mapping, incident)
    _apply_personnes(payload, mapping, incident)
    _apply_referentiels(payload, mapping, incident)
    _apply_extras(payload, mapping, incident)
    _detect_test_data(incident)

    return incident


# =====================================================================
# APPLICATION DES REGLES PAR SECTION
# =====================================================================

def _apply_metier_fields(payload: dict, mapping: ModuleMapping, incident: IncidentCanonique) -> None:
    """Applique les mappings champs_metier (mapping direct).

    Utilisation : remplit les attributs simples de l'incident a partir
    des champs source. Utilise setattr car les noms canoniques sont
    declares dans le YAML.
    """
    for fm in mapping.champs_metier:
        raw_value = payload.get(fm.source)

        if raw_value is None:
            if fm.required:
                logger.warning(
                    "Champ requis '%s' absent dans incident %s",
                    fm.source, incident.incident_id_source
                )
            continue

        typed_value = _coerce_type(raw_value, fm.type, fm.source)
        if typed_value is not None:
            setattr(incident, fm.canonical, typed_value)


def _apply_date_fields(payload: dict, mapping: ModuleMapping, incident: IncidentCanonique) -> None:
    """Applique les mappings dates_heures (parsing string -> datetime/time).

    Utilisation : utilise dateutil pour parser les dates ISO-like. Tolere
    les chaines vides et les valeurs nulles.
    """
    for dm in mapping.dates_heures:
        raw_value = payload.get(dm.source)

        if not raw_value:
            if dm.required:
                logger.warning(
                    "Date requise '%s' absente dans incident %s",
                    dm.source, incident.incident_id_source
                )
            continue

        try:
            if dm.type == "datetime":
                parsed = date_parser.parse(raw_value)
                setattr(incident, dm.canonical, parsed)
            elif dm.type == "time":
                parsed = date_parser.parse(raw_value).time()
                setattr(incident, dm.canonical, parsed)
            elif dm.type == "date":
                parsed = date_parser.parse(raw_value).date()
                setattr(incident, dm.canonical, parsed)
        except (ValueError, TypeError) as e:
            logger.warning(
                "Erreur parsing date '%s' = '%s' : %s",
                dm.source, raw_value, e
            )


def _apply_derived_fields(payload: dict, mapping: ModuleMapping, incident: IncidentCanonique) -> None:
    """Applique les mappings champs_derives (champs calcules).

    Utilisation : execute des logiques nommees declarees dans le YAML.
    Chaque logique est implementee dans _DERIVED_LOGICS.
    """
    for dm in mapping.champs_derives:
        logic_fn = _DERIVED_LOGICS.get(dm.logic)
        if logic_fn is None:
            logger.warning("Logique derivee inconnue : %s", dm.logic)
            continue

        # La source est soit un champ canonique deja peuple soit le payload brut
        source_value = getattr(incident, dm.derived_from, None)
        if source_value is None:
            source_value = payload.get(dm.derived_from)

        derived_value = logic_fn(source_value)
        setattr(incident, dm.canonical, derived_value)


def _apply_societe(payload: dict, mapping: ModuleMapping, incident: IncidentCanonique) -> None:
    """Construit la liste des SocieteRef depuis le champ societe.

    Utilisation : le champ source est typiquement une liste d'ints
    (ex: [5, 30]). Chaque int devient un SocieteRef qui sera materialise
    en noeud Neo4j (:Societe).
    """
    if mapping.societe is None:
        return

    raw_value = payload.get(mapping.societe.source)
    if not raw_value or not isinstance(raw_value, list):
        return

    for id_societe in raw_value:
        if isinstance(id_societe, int):
            incident.societes.append(SocieteRef(id_societe=id_societe))


def _apply_personnes(payload: dict, mapping: ModuleMapping, incident: IncidentCanonique) -> None:
    """Construit la liste des PersonneRef depuis les champs personne.

    Utilisation : pour chaque mapping personne, lit le login et l'id
    associes et cree un PersonneRef.
    """
    for pm in mapping.personnes:
        login = payload.get(pm.source_login)
        if not login:
            continue

        id_em = None
        if pm.source_id:
            id_em = payload.get(pm.source_id)

        incident.personnes.append(PersonneRef(
            login=str(login),
            id_emetteur=int(id_em) if id_em is not None else None,
            role=pm.role,
        ))


def _apply_referentiels(payload: dict, mapping: ModuleMapping, incident: IncidentCanonique) -> None:
    """Construit la liste des ReferentielRef depuis les sous-objets.

    Utilisation : gere a la fois les sous-objets seuls et les listes.
    Extrait _id, _code, _label, _object des sous-dicts.
    """
    for rm in mapping.referentiels:
        raw_value = payload.get(rm.source)
        if not raw_value:
            continue

        if rm.is_list:
            if isinstance(raw_value, list):
                for item in raw_value:
                    ref = _build_referentiel(item, rm)
                    if ref:
                        incident.referentiels.append(ref)
        else:
            if isinstance(raw_value, dict):
                ref = _build_referentiel(raw_value, rm)
                if ref:
                    incident.referentiels.append(ref)


def _build_referentiel(item: dict, rm: ReferentielMapping) -> Optional[ReferentielRef]:
    """Construit un ReferentielRef depuis un sous-dict source.

    Utilisation : facteur commun entre cas liste et cas objet seul.
    Retourne None si le sous-dict ne contient pas les champs attendus.
    """
    if not isinstance(item, dict):
        return None

    ref_id = item.get("_id")
    code = item.get("_code")
    label = item.get("_label")

    if ref_id is None or not code or not label:
        return None

    return ReferentielRef(
        family=rm.family,
        ref_id=int(ref_id),
        code=str(code),
        label=str(label),
        code_externe=item.get("_code_externe") or None,
        relation_type=rm.relation_type,
    )


def _apply_extras(payload: dict, mapping: ModuleMapping, incident: IncidentCanonique) -> None:
    """Capture les champs rares whitelistes dans extra_fields.

    Utilisation : permet de ne pas perdre les champs qui ne sont pas
    explicitement mappes mais qui apparaissent rarement.
    """
    if not mapping.extras.enabled:
        return

    whitelist = set(mapping.extras.whitelist)
    for source_field in whitelist:
        if source_field in payload and payload[source_field] is not None:
            incident.extra_fields[source_field] = payload[source_field]


def _detect_test_data(incident: IncidentCanonique) -> None:
    """Marque l'incident comme donnee de test si patterns detectes.

    Utilisation : detecte les templates Postman residuels (ex: {{...}})
    qui auraient pu rester dans la base. Permet de filtrer ces incidents
    dans les requetes Cypher.
    """
    if not incident.titre:
        return

    if "{{" in incident.titre or "POSTMAN" in incident.titre.upper():
        incident.is_test_data = True


# =====================================================================
# COERCITION DE TYPE
# =====================================================================

def _coerce_type(value: Any, target_type: str, field_name: str) -> Any:
    """Convertit une valeur source au type canonique attendu.

    Utilisation : tolere les valeurs deja typees correctement, tente une
    conversion sinon, logge un warning en cas d'echec.
    """
    if value is None:
        return None

    try:
        if target_type == "str":
            return str(value).strip() if str(value).strip() else None
        if target_type == "int":
            return int(value)
        if target_type == "float":
            return float(value)
        if target_type == "bool":
            return bool(value)
        return value
    except (ValueError, TypeError) as e:
        logger.warning("Coercition impossible pour '%s' = %r en %s : %s",
                       field_name, value, target_type, e)
        return None


# =====================================================================
# LOGIQUES DERIVEES (extensibles)
# =====================================================================

def _logic_value_not_zero(value: Any) -> bool:
    """Logique : retourne True si la valeur est non-nulle et != 0.

    Utilisation : convertit le code blesses_raw en booleen presence_blesses.
    """
    if value is None:
        return False
    try:
        return int(value) != 0
    except (ValueError, TypeError):
        return False


def _logic_list_label_is_oui(value: Any) -> bool:
    """Logique : retourne True si la liste contient un dict avec _label == 'oui'.

    Utilisation : convertit pretPourEnvoiEccairs (liste avec un dict)
    en booleen pret_envoi_eccairs.
    """
    if not isinstance(value, list) or not value:
        return False
    for item in value:
        if isinstance(item, dict):
            label = str(item.get("_label", "")).strip().lower()
            if label == "oui":
                return True
    return False


# Registre des logiques derivees nommees
_DERIVED_LOGICS = {
    "value_not_zero": _logic_value_not_zero,
    "list_label_is_oui": _logic_list_label_is_oui,
}


# =====================================================================
# UTILITAIRES INTERNES
# =====================================================================

def _find_source_for_canonical(mapping: ModuleMapping, canonical_name: str) -> Optional[str]:
    """Retrouve le nom source associe a un nom canonique.

    Utilisation : interne. Sert a localiser le champ _id source pour
    construire l'UUID stable.
    """
    for fm in mapping.champs_metier:
        if fm.canonical == canonical_name:
            return fm.source
    return None
