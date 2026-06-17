"""
Chargement et validation des fichiers YAML de mapping.

Centralise la lecture des configurations declaratives qui pilotent
l'extracteur generique.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


# =====================================================================
# STRUCTURES PYTHON DU MAPPING
# =====================================================================

@dataclass
class FieldMapping:
    """Description d'un mapping champ source -> champ canonique."""
    canonical: str
    source: str
    type: str = "str"
    required: bool = False


@dataclass
class DerivedFieldMapping:
    """Description d'un champ derive (calcule depuis un autre champ)."""
    canonical: str
    derived_from: str
    logic: str
    type: str = "str"


@dataclass
class DateFieldMapping:
    """Description d'un mapping pour un champ date/heure."""
    canonical: str
    source: str
    type: str  # "datetime", "date", ou "time"
    required: bool = False


@dataclass
class SocieteMapping:
    """Description du mapping multi-tenancy."""
    source: str
    type: str  # "list_of_ids"
    relation_type: str


@dataclass
class PersonneMapping:
    """Description du mapping d'une personne (login + id)."""
    role: str
    source_login: str
    source_id: Optional[str]
    relation_type: str


@dataclass
class ReferentielMapping:
    """Description du mapping d'un referentiel (ChampSupp\\ListeContenu)."""
    canonical: str
    source: str
    family: str
    is_list: bool
    relation_type: str


@dataclass
class TextFieldMapping:
    """Description d'un champ textuel pour embedding/LLM."""
    canonical: str
    min_length: int
    for_embedding: bool = True
    for_llm: bool = False


@dataclass
class IgnoredField:
    """Documentation d'un champ explicitement ignore."""
    field: str
    reason: str


@dataclass
class ExtrasConfig:
    """Configuration de la capture des champs rares non types."""
    enabled: bool = False
    whitelist: list[str] = field(default_factory=list)


@dataclass
class ModuleMapping:
    """Mapping complet d'un module intra'know.

    Utilisation : objet retourne par load_mapping(). Contient toutes
    les regles d'extraction declarees dans un fichier YAML.
    """
    module_name: str
    module_label: str
    source_format: str
    embedded_key: Optional[str]
    description: str
    champs_metier: list[FieldMapping]
    champs_derives: list[DerivedFieldMapping]
    dates_heures: list[DateFieldMapping]
    societe: Optional[SocieteMapping]
    personnes: list[PersonneMapping]
    referentiels: list[ReferentielMapping]
    champs_textuels: list[TextFieldMapping]
    champs_ignores: list[IgnoredField]
    extras: ExtrasConfig

    def get_text_field(self, canonical: str) -> Optional[TextFieldMapping]:
        """Retourne la config textuelle d'un champ canonique."""
        for tf in self.champs_textuels:
            if tf.canonical == canonical:
                return tf
        return None

    def is_ignored(self, source_field: str) -> bool:
        """Indique si un champ source est dans la liste des ignores."""
        return any(ig.field == source_field for ig in self.champs_ignores)

    def is_mapped(self, source_field: str) -> bool:
        """Indique si un champ source est mappe quelque part."""
        for fm in self.champs_metier:
            if fm.source == source_field:
                return True
        for dt in self.dates_heures:
            if dt.source == source_field:
                return True
        if self.societe and self.societe.source == source_field:
            return True
        for pers in self.personnes:
            if pers.source_login == source_field or pers.source_id == source_field:
                return True
        for ref in self.referentiels:
            if ref.source == source_field:
                return True
        return False


# =====================================================================
# CHARGEMENT DEPUIS YAML
# =====================================================================

def load_mapping(yaml_path: Path) -> ModuleMapping:
    """Lit un fichier YAML et retourne un ModuleMapping valide.

    Utilisation : appelee par l'extracteur au demarrage pour charger
    les regles. Leve une erreur explicite si le fichier est invalide.
    """
    if not yaml_path.exists():
        raise FileNotFoundError(f"Mapping YAML introuvable : {yaml_path}")

    with yaml_path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"YAML mal forme : la racine doit etre un dict")

    return _build_mapping(raw)


def _build_mapping(raw: dict) -> ModuleMapping:
    """Construit un ModuleMapping a partir du dict YAML brut.

    Utilisation : interne. Separe le parsing YAML (load_mapping) de la
    construction des objets typés (cette fonction).
    """
    meta = raw.get("metadata", {})

    return ModuleMapping(
        module_name=meta.get("module_name", "unknown"),
        module_label=meta.get("module_label", ""),
        source_format=meta.get("source_format", "list"),
        embedded_key=meta.get("embedded_key"),
        description=meta.get("description", ""),
        champs_metier=_build_field_list(raw.get("champs_metier", [])),
        champs_derives=_build_derived_list(raw.get("champs_derives", [])),
        dates_heures=_build_date_list(raw.get("dates_heures", [])),
        societe=_build_societe(raw.get("relations_societe")),
        personnes=_build_personne_list(raw.get("relations_personne", [])),
        referentiels=_build_ref_list(raw.get("relations_referentiel", [])),
        champs_textuels=_build_text_list(raw.get("champs_textuels", [])),
        champs_ignores=_build_ignored_list(raw.get("champs_ignores", [])),
        extras=_build_extras(raw.get("extras", {})),
    )


def _build_field_list(items: list) -> list[FieldMapping]:
    return [
        FieldMapping(
            canonical=item["canonical"],
            source=item["source"],
            type=item.get("type", "str"),
            required=item.get("required", False),
        )
        for item in items
    ]


def _build_derived_list(items: list) -> list[DerivedFieldMapping]:
    return [
        DerivedFieldMapping(
            canonical=item["canonical"],
            derived_from=item["derived_from"],
            logic=item["logic"],
            type=item.get("type", "str"),
        )
        for item in items
    ]


def _build_date_list(items: list) -> list[DateFieldMapping]:
    return [
        DateFieldMapping(
            canonical=item["canonical"],
            source=item["source"],
            type=item["type"],
            required=item.get("required", False),
        )
        for item in items
    ]


def _build_societe(item: Optional[dict]) -> Optional[SocieteMapping]:
    if not item:
        return None
    return SocieteMapping(
        source=item["source"],
        type=item["type"],
        relation_type=item["relation_type"],
    )


def _build_personne_list(items: list) -> list[PersonneMapping]:
    return [
        PersonneMapping(
            role=item["role"],
            source_login=item["source_login"],
            source_id=item.get("source_id"),
            relation_type=item["relation_type"],
        )
        for item in items
    ]


def _build_ref_list(items: list) -> list[ReferentielMapping]:
    return [
        ReferentielMapping(
            canonical=item["canonical"],
            source=item["source"],
            family=item["family"],
            is_list=item.get("is_list", False),
            relation_type=item["relation_type"],
        )
        for item in items
    ]


def _build_text_list(items: list) -> list[TextFieldMapping]:
    return [
        TextFieldMapping(
            canonical=item["canonical"],
            min_length=item.get("min_length", 0),
            for_embedding=item.get("for_embedding", True),
            for_llm=item.get("for_llm", False),
        )
        for item in items
    ]


def _build_ignored_list(items: list) -> list[IgnoredField]:
    return [
        IgnoredField(field=item["field"], reason=item.get("reason", ""))
        for item in items
    ]


def _build_extras(item: dict) -> ExtrasConfig:
    return ExtrasConfig(
        enabled=item.get("enabled", False),
        whitelist=item.get("whitelist", []),
    )
