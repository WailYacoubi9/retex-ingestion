"""
Codegen — génère un modèle canonique (dataclass) à partir d'un schéma YAML.

Le schéma (config/schemas/*.schema.yaml) est la SOURCE DE VÉRITÉ. On édite le
YAML, on régénère ; le dev n'écrit jamais le modèle à la main.

Deux formats acceptés :
  - UNIFIÉ      : `champs:` où chaque entrée a un `role` (propriete/date/flag/relation)
  - SECTIONNÉ   : `champs:` + `champs_derives:` + `relations:` + `techniques:`

Usage :
    python scripts/codegen_model.py config/schemas/incident_securite_v2.schema.yaml \
        --out models_incident_securite_v2.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

TYPE_MAP = {
    "texte": "str", "entier": "int", "decimal": "float", "booleen": "bool",
    "date": "date", "horodatage": "datetime", "heure": "time",
    "dictionnaire": "dict[str, Any]", "objet": "Any",
}

ENTITES_REFS = '''
@dataclass
class SocieteRef:
    id_societe: int


@dataclass
class PersonneRef:
    login: str
    id_emetteur: Optional[int] = None
    role: str = "emetteur"


@dataclass
class ReferentielRef:
    family: str
    ref_id: int
    code: str
    label: str
    code_externe: Optional[str] = None
    relation_type: str = "LIE_A"
'''

ENTITE_LIEE = '''
@dataclass
class EntiteLiee:
    """Nœud lié générique (Lieu, Compagnie, Societe...)."""
    noeud: str
    cle: str
    valeur: str
    relation: str
'''


def _classe(nom_technique: str) -> str:
    return "".join(p.capitalize() for p in nom_technique.split("_")) + "Canonique"


def _pytype(t: str) -> str:
    return TYPE_MAP.get(t, "Any")


def _ligne(cle: str, type_yaml: str, description: str | None) -> str:
    pt = _pytype(type_yaml)
    com = f"  # {description.splitlines()[0][:68]}" if description else ""
    return f"    {cle}: Optional[{pt}] = None{com}"


def _entete(nom_tech: str) -> list[str]:
    return [
        '"""MODULE AUTO-GÉNÉRÉ par scripts/codegen_model.py — NE PAS ÉDITER À LA MAIN.',
        f'Source : schéma « {nom_tech} ». Régénérer après chaque édition du YAML."""',
        "from __future__ import annotations",
        "",
        "import uuid",
        "from dataclasses import dataclass, field",
        "from datetime import date, datetime, time",
        "from typing import Any, Optional",
        "",
    ]


def _uuid_helper(nom_tech: str, id_canon: str) -> list[str]:
    return [
        f'SOURCE_MODULE = "{nom_tech}"',
        '_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")',
        "",
        "",
        f"def make_uuid({id_canon}: str) -> str:",
        '    """UUID v5 stable depuis l\'identité (idempotence)."""',
        f"    if not {id_canon}:",
        f'        raise ValueError("{id_canon} ne peut pas être vide")',
        f'    return str(uuid.uuid5(_NS, f"{{SOURCE_MODULE}}:{{{id_canon}}}"))',
    ]


def generer_unifie(schema: dict) -> str:
    module = schema["module"]
    nom = module["nom_technique"]
    classe = _classe(nom)
    id_canon = module.get("cle_identite_canonical", "id_source")
    champs = schema.get("champs", [])
    a_relations = any(c.get("role") == "relation" for c in champs)
    embed = [c["cle"] for c in champs if c.get("embedding")]

    L = _entete(nom)
    L += _uuid_helper(nom, id_canon)
    if a_relations:
        L.append("")
        L.append(ENTITE_LIEE.strip())
    L += ["", "", "@dataclass", f"class {classe}:",
          f'    """Modèle canonique « {nom} » — généré depuis le schéma."""', "",
          "    # --- identité ---",
          "    incident_id: Optional[str] = None",
          "    source_module: str = SOURCE_MODULE", ""]

    for c in champs:
        if c.get("role") == "relation":
            continue
        L.append(_ligne(c["cle"], c.get("type", "texte"), c.get("description")))

    if a_relations:
        L += ["", "    # --- relations ---",
              "    entites: list[EntiteLiee] = field(default_factory=list)"]

    L += ["", "    # --- techniques ---",
          "    resume_llm: Optional[str] = None",
          "    llm_model: Optional[str] = None",
          "    is_test_data: bool = False",
          "    last_indexed_at: Optional[str] = None"]

    if embed:
        items = ", ".join(f'"{e}"' for e in embed)
        L += ["", f"    CHAMPS_EMBEDDING = ({items},)", "",
              "    def textes_pour_embedding(self, min_length: int = 20) -> dict[str, str]:",
              '        """Narratifs assez longs pour vectorisation."""',
              "        out: dict[str, str] = {}",
              "        for nom in self.CHAMPS_EMBEDDING:",
              "            v = getattr(self, nom, None)",
              "            if isinstance(v, str) and len(v.strip()) >= min_length:",
              "                out[nom] = v.strip()",
              "        return out"]
    return "\n".join(L) + "\n"


def generer_sections(schema: dict) -> str:
    """Format historique (champs/champs_derives/relations dict/techniques)."""
    module = schema.get("module", {})
    nom = module.get("nom_technique", "module")
    classe = _classe(nom)

    L = _entete(nom)
    L.append(ENTITES_REFS.strip())
    L += ["", "", "@dataclass", f"class {classe}:",
          f'    """Modèle canonique « {nom} » — généré depuis le schéma."""', ""]
    for c in schema.get("champs", []):
        L.append(_ligne(c["cle"], c.get("type", "texte"), c.get("description")))
    if schema.get("champs_derives"):
        L.append("")
        L.append("    # --- dérivés ---")
        for c in schema["champs_derives"]:
            L.append(_ligne(c["cle"], c.get("type", "texte"), c.get("description")))
    for c in schema.get("techniques", []):
        if c.get("type") not in ("dictionnaire", "objet"):
            L.append(_ligne(c["cle"], c.get("type", "texte"), c.get("description")))
    rel = schema.get("relations", {})
    if isinstance(rel, dict) and rel:
        L.append("")
        L.append("    # --- relations ---")
        if "societe" in rel:
            L.append("    societes: list[SocieteRef] = field(default_factory=list)")
        if "personnes" in rel:
            L.append("    personnes: list[PersonneRef] = field(default_factory=list)")
        if "referentiels" in rel:
            L.append("    referentiels: list[ReferentielRef] = field(default_factory=list)")
    L += ["", "    extra_fields: dict[str, Any] = field(default_factory=dict)",
          "    llm: Optional[Any] = None"]
    return "\n".join(L) + "\n"


def generer(schema: dict) -> str:
    champs = schema.get("champs", [])
    unifie = any("role" in c for c in champs)
    return generer_unifie(schema) if unifie else generer_sections(schema)


def main() -> int:
    ap = argparse.ArgumentParser(description="Génère une dataclass depuis un schéma YAML")
    ap.add_argument("schema", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    schema = yaml.safe_load(args.schema.read_text(encoding="utf-8"))
    args.out.write_text(generer(schema), encoding="utf-8")
    print(f"OK -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
