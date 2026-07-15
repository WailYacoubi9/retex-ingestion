"""
Ingestion — Nœuds Action dans Neo4j.

Lit le JSON produit par csv_actions_to_json.py (incidents_avec_actions.json).
Pour chaque incident, crée les nœuds :Action et les relie à :IncidentSecu.

Modèle graph :
    (:IncidentSecu)-[:A_POUR_ACTION {type_action: "corrective"}]->(:Action)
    (:Action)-[:ACTION_PAR]->(:Personne)

Déduplication : MERGE sur (titre_action + responsable + date_ajout).
Une action partagée entre plusieurs incidents n'est créée qu'une seule fois.

Usage :
    python scripts/ingest_actions.py
    python scripts/ingest_actions.py --input data/samples/incidents_avec_actions.json
    python scripts/ingest_actions.py --dry-run
    python scripts/ingest_actions.py --limit 100
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import uuid
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
from clients import Neo4jClient

DEFAULT_INPUT = PROJECT_ROOT / "data" / "samples" / "incidents_avec_actions.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ingest_actions")

# Même namespace que le reste du pipeline pour cohérence
_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
SOURCE_MODULE = "incident_securite_v2"

LABEL_INCIDENT = "IncidentSecu"
LABEL_ACTION   = "Action"
LABEL_PERSONNE = "Personne"
REL_A_POUR_ACTION = "A_POUR_ACTION"
REL_ACTION_PAR    = "ACTION_PAR"


def _incident_id(numero_fe: str) -> str:
    """UUID v5 identique à celui du pipeline principal."""
    return str(uuid.uuid5(_NS, f"{SOURCE_MODULE}:{numero_fe}"))


def _action_id(titre: str, responsable: str, date_ajout: str) -> str:
    """UUID stable pour déduplication Action."""
    key = f"action:{titre.lower().strip()}:{responsable.lower().strip()}:{date_ajout}"
    return str(uuid.uuid5(_NS, key))


# Mapping clé JSON (label export, préfixe retiré) -> clé canonique du schéma
# (config/schemas/incident_securite_v2.schema.yaml, bloc actions).
# None = champ ignoré. Les clés inconnues sont ignorées avec un warning.
CHAMP_MAP: dict[str, str | None] = {
    "type d'action":                        None,  # porté par la relation
    "titre de l'action":                    "titre_action",
    "détail":                               "detail_action",
    "Comment sera vérifiée l'efficacité ?": "critere_efficacite",
    "responsable":                          "responsable",
    "resp. externe":                        "responsable_externe",
    "date d'ajout":                         "date_ajout",
    "date prévue":                          "date_prevue",
    "date de clôture":                      "date_cloture",
    "statut":                               "statut",
    "coût":                                 None,  # quasi-null, ignoré (cf schéma)
    "Service responsable":                  "service_action",
    "Etat d'avancement":                    "etat_avancement",
}

# Champs date à normaliser en ISO (tri et filtres par année possibles en Cypher)
DATE_KEYS = {"date_ajout", "date_prevue", "date_cloture"}


def _to_iso(value: str) -> str:
    """Convertit 'JJ/MM/AAAA' en 'AAAA-MM-JJ'. Valeur brute si format inattendu."""
    from datetime import datetime
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return value.strip()


def bootstrap_neo4j(neo4j: Neo4jClient) -> None:
    """Contrainte d'unicité + index sur Action."""
    neo4j.execute(
        "CREATE CONSTRAINT action_id IF NOT EXISTS "
        "FOR (a:Action) REQUIRE a.action_id IS UNIQUE"
    )
    logger.info("Contrainte Action créée (ou déjà présente)")


def _canonical_props(action: dict) -> dict[str, Any]:
    """Convertit les clés export en clés canoniques du schéma, dates en ISO."""
    props: dict[str, Any] = {}
    for k, v in action.items():
        if v is None:
            continue
        if k not in CHAMP_MAP:
            logger.warning("Champ action inconnu ignoré : %r", k)
            continue
        cle = CHAMP_MAP[k]
        if cle is None:
            continue
        props[cle] = _to_iso(v) if cle in DATE_KEYS else v
    return props


def write_actions(neo4j: Neo4jClient, incident_id: str, numero_fe: str,
                  actions: list[dict], type_action: str) -> tuple[int, int]:
    """
    Écrit les actions d'un type (corrective/préventive) pour un incident.
    Retourne (nb_actions_créées_ou_liées, nb_relations_créées).
    """
    n_actions = n_rels = 0
    with neo4j.session() as s:
        for action in actions:
            titre     = (action.get("titre de l'action") or "").strip()
            responsable = (action.get("responsable") or "").strip()
            date_ajout  = (action.get("date d'ajout") or "").strip()

            if not titre:
                continue

            action_id = _action_id(titre, responsable, date_ajout)
            props_neo4j = _canonical_props(action)
            props_neo4j["titre_action"] = titre
            props_neo4j["type_action"]  = type_action

            # MERGE Action (déduplication)
            s.run(
                f"MERGE (a:{LABEL_ACTION} {{action_id: $action_id}}) "
                f"SET a += $props",
                action_id=action_id,
                props=props_neo4j,
            ).consume()
            n_actions += 1

            # MERGE relation IncidentSecu → Action
            s.run(
                f"MATCH (i:{LABEL_INCIDENT} {{incident_id: $inc_id}}) "
                f"MATCH (a:{LABEL_ACTION}   {{action_id:   $act_id}}) "
                f"MERGE (i)-[:{REL_A_POUR_ACTION} {{type_action: $type}}]->(a)",
                inc_id=incident_id,
                act_id=action_id,
                type=type_action,
            ).consume()
            n_rels += 1

            # MERGE Personne (login) + relation Action → Personne
            if responsable:
                s.run(
                    f"MERGE (p:{LABEL_PERSONNE} {{login: $login}}) "
                    f"WITH p "
                    f"MATCH (a:{LABEL_ACTION} {{action_id: $act_id}}) "
                    f"MERGE (a)-[:{REL_ACTION_PAR}]->(p)",
                    login=responsable,
                    act_id=action_id,
                ).consume()

    return n_actions, n_rels


def run(input_path: Path, limit: int, dry_run: bool) -> int:
    if not input_path.exists():
        logger.error("Fichier introuvable : %s", input_path)
        return 1

    data = json.loads(input_path.read_text(encoding="utf-8"))
    if limit:
        data = data[:limit]

    logger.info("Incidents à traiter : %d | dry_run=%s", len(data), dry_run)

    if dry_run:
        n_inc = n_act = 0
        for inc in data:
            total = len(inc.get("actions_correctives", [])) + len(inc.get("actions_preventives", []))
            if total:
                n_inc += 1
                n_act += total
        logger.info("DRY RUN — %d incidents avec actions, %d actions au total", n_inc, n_act)
        return 0

    t0 = time.time()
    n_ok = n_skip = n_fail = 0
    n_actions_total = n_rels_total = 0

    with Neo4jClient(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD) as neo4j:
        bootstrap_neo4j(neo4j)

        for i, inc in enumerate(data, 1):
            fe = (inc.get("Num F.E.") or "").strip()
            if not fe:
                n_skip += 1
                continue

            inc_id = _incident_id(fe)
            correctives = inc.get("actions_correctives", [])
            preventives = inc.get("actions_preventives", [])
            curatives   = inc.get("actions_curatives", [])

            if not (correctives or preventives or curatives):
                n_skip += 1
                continue

            try:
                for actions, type_action in [
                    (correctives, "corrective"),
                    (preventives, "préventive"),
                    (curatives,   "curative"),
                ]:
                    na, nr = write_actions(neo4j, inc_id, fe, actions, type_action)
                    n_actions_total += na
                    n_rels_total    += nr

                n_ok += 1
                if i % 200 == 0:
                    logger.info("  ... %d/%d incidents traités", i, len(data))

            except Exception as e:
                logger.error("Échec %s : %s", fe, e)
                n_fail += 1

    dt = time.time() - t0
    logger.info("===== Récapitulatif =====")
    logger.info("Incidents avec actions : %d | sans action (ignorés) : %d | échecs : %d",
                n_ok, n_skip, n_fail)
    logger.info("Nœuds Action écrits/mis à jour : %d", n_actions_total)
    logger.info("Relations A_POUR_ACTION créées : %d", n_rels_total)
    logger.info("Durée : %.1fs", dt)
    return 0 if n_fail == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingestion des nœuds Action dans Neo4j")
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--limit", type=int, default=0, help="0 = tous les incidents")
    ap.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    args = ap.parse_args()
    return run(args.input, args.limit, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
