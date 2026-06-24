"""
Extracteur — Incident Sécurité v2 (export plateforme à plat, libellés FR).

Piloté par le MÊME schéma que le codegen
(config/schemas/incident_securite_v2.schema.yaml) : un seul fichier documente,
génère le modèle ET pilote l'extraction.

Dispatch par `role` de chaque champ : propriete / date / flag / relation.
"""
from __future__ import annotations

import logging
from dataclasses import fields
from datetime import datetime, time
from pathlib import Path
from typing import Any, Optional

import yaml
from dateutil import parser as date_parser

from models_incident_securite_v2 import (
    EntiteLiee,
    IncidentSecuriteV2Canonique,
    make_uuid,
)

logger = logging.getLogger(__name__)

# Valeurs "vides sémantiques" : présentes mais sans contenu utile.
VALEURS_VIDES = {
    "", "0", "non", "n/a", "na", "néant", "neant", "false",
    "sans objet", "non applicable", "non applicable.", "ras",
}


def charger_schema(yaml_path: Path) -> dict:
    """Lit le schéma YAML du module."""
    return yaml.safe_load(Path(yaml_path).read_text(encoding="utf-8"))


def verifier_coherence(schema: dict) -> None:
    """Vérifie que le modèle généré est à jour avec le schéma.

    Lève une erreur claire si un champ du schéma (hors relation) n'existe pas
    dans le modèle — signe qu'on a édité le YAML sans régénérer le modèle.
    """
    champs_modele = {f.name for f in fields(IncidentSecuriteV2Canonique)}
    manquants = [
        c["cle"] for c in schema.get("champs", [])
        if c.get("role") != "relation" and c["cle"] not in champs_modele
    ]
    if manquants:
        raise RuntimeError(
            "Schéma et modèle désynchronisés — champs absents du modèle : "
            f"{manquants}.\nRégénère le modèle :\n"
            "  python scripts/codegen_model.py "
            "config/schemas/incident_securite_v2.schema.yaml "
            "--out models_incident_securite_v2.py"
        )


def _texte(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _est_vide_semantique(value: Any) -> bool:
    s = (str(value).strip().lower() if value is not None else "")
    return s in VALEURS_VIDES


def _to_bool(value: Any) -> Optional[bool]:
    s = _texte(value)
    if s is None:
        return None
    low = s.lower()
    if low.startswith("oui"):
        return True
    if low == "non":
        return False
    return None


def _to_datetime(value: Any) -> Optional[datetime]:
    s = _texte(value)
    if not s:
        return None
    try:
        return date_parser.parse(s, dayfirst=True)
    except (ValueError, TypeError, OverflowError):
        return None


def _to_time(value: Any) -> Optional[time]:
    s = _texte(value)
    if not s:
        return None
    try:
        return date_parser.parse(s, dayfirst=True).time()
    except (ValueError, TypeError, OverflowError):
        return None


def extraire(payload: dict, schema: dict) -> Optional[IncidentSecuriteV2Canonique]:
    """Transforme un payload (clés = libellés FR) en modèle canonique."""
    id_label = schema["module"]["cle_identite_label"]
    numero_fe = _texte(payload.get(id_label))
    if not numero_fe:
        logger.warning("Fiche sans '%s', ignorée", id_label)
        return None

    inc = IncidentSecuriteV2Canonique(
        incident_id=make_uuid(numero_fe),
        numero_fe=numero_fe,
        last_indexed_at=datetime.utcnow().isoformat() + "Z",
    )

    for c in schema.get("champs", []):
        role = c.get("role")
        raw = payload.get(c["label"])

        if role == "relation":
            items = str(raw).split("|") if isinstance(raw, str) else ([raw] if raw is not None else [])
            for it in items:
                if _est_vide_semantique(it):
                    continue
                val = _texte(it)
                if val:
                    inc.entites.append(EntiteLiee(
                        noeud=c["noeud"], cle=c["cle_noeud"],
                        valeur=val, relation=c["relation"],
                    ))
            continue

        if c["cle"] == "numero_fe":      # déjà posé
            continue

        if role == "date":
            parsed = _to_time(raw) if c.get("type") == "heure" else _to_datetime(raw)
            if parsed is not None:
                setattr(inc, c["cle"], parsed)
        elif role == "flag":
            b = _to_bool(raw)
            if b is not None:
                setattr(inc, c["cle"], b)
        else:  # propriete
            if c.get("filtre_vide") and _est_vide_semantique(raw):
                continue
            val = _texte(raw)
            if val is not None:
                setattr(inc, c["cle"], val)

    _detecter_test(inc)
    return inc


def _detecter_test(inc: IncidentSecuriteV2Canonique) -> None:
    for champ in (inc.numero_fe, inc.titre):
        if champ and ("{{" in champ or "POSTMAN" in champ.upper()):
            inc.is_test_data = True
            return
