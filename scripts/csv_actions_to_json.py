"""
Convertit le CSV actions en JSON structuré.

Format de sortie : liste d'objets, un par FE.
Chaque objet contient tous les champs incident + une clé "actions" (liste).

Usage :
    python scripts/csv_actions_to_json.py
    python scripts/csv_actions_to_json.py --input data/samples/mon_fichier.csv --output data/samples/out.json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

CSV_ENCODING = "cp1252"
CSV_DELIMITER = ";"

# Colonnes qui appartiennent à une action (préfixe [Action] ou [CHAMP_SUPP])
ACTION_PREFIXES = ("[Action]", "[CHAMP_SUPP]")

# Valeurs considérées comme vides (ne méritent pas d'être stockées)
EMPTY_VALUES = {
    "", "0", "non", "Non", "NON",
    "n/a", "N/A", "NA", "na",
    "sans objet", "Sans objet", "SANS OBJET",
    "Non applicable.", "non applicable",
    "nil", "NIL", "ras", "RAS", "N/A.",
    "false", "False",
}


def _clean(value: str | None) -> str | None:
    """Retourne None pour les valeurs vides/placeholder, sinon la valeur nettoyée."""
    if value is None:
        return None
    v = value.strip()
    return None if v in EMPTY_VALUES else (v or None)


# Clés action où la valeur brute est significative : statut '0' = action en cours
# (ne doit PAS être traité comme valeur vide).
KEEP_RAW_ACTION_KEYS = {"statut"}


def _clean_action(key: str, value: str | None) -> str | None:
    if key in KEEP_RAW_ACTION_KEYS:
        v = (value or "").strip()
        return v or None
    return _clean(value)


def _is_action_col(col: str) -> bool:
    return any(col.startswith(p) for p in ACTION_PREFIXES)


def _action_key(col: str) -> str:
    """Retire le préfixe [Action] ou [CHAMP_SUPP] du nom de colonne."""
    for p in ACTION_PREFIXES:
        if col.startswith(p):
            return col[len(p):]
    return col


def csv_to_json(input_path: Path, output_path: Path) -> None:
    with open(input_path, encoding=CSV_ENCODING, newline="") as f:
        reader = csv.DictReader(f, delimiter=CSV_DELIMITER)
        all_cols = reader.fieldnames or []
        rows = list(reader)

    incident_cols = [c for c in all_cols if not _is_action_col(c)]
    action_cols   = [c for c in all_cols if _is_action_col(c)]

    # Grouper les lignes par FE
    by_fe: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        fe = (row.get("Num F.E.") or "").strip()
        if fe:
            by_fe[fe].append(row)

    incidents: list[dict] = []

    for fe, fe_rows in by_fe.items():
        # Données incident = première ligne (identiques sur toutes les lignes du même FE)
        first = fe_rows[0]
        incident: dict = {}
        for col in incident_cols:
            incident[col] = _clean(first.get(col))

        # Actions = toutes les lignes qui ont au moins un champ [Action] non vide
        # Séparées par type dans l'objet incident
        actions_correctives: list[dict] = []
        actions_preventives: list[dict] = []
        actions_curatives:   list[dict] = []

        for row in fe_rows:
            action: dict = {}
            for col in action_cols:
                key = _action_key(col)
                v = _clean_action(key, row.get(col))
                if v is not None:
                    action[key] = v
            if not (action.get("type d'action") or action.get("titre de l'action")):
                continue
            t = (action.get("type d'action") or "").lower()
            if "préventive" in t or "preventive" in t:
                actions_preventives.append(action)
            elif "curative" in t:
                actions_curatives.append(action)
            else:
                actions_correctives.append(action)

        incident["actions_correctives"] = actions_correctives
        incident["actions_preventives"] = actions_preventives
        if actions_curatives:
            incident["actions_curatives"] = actions_curatives
        incidents.append(incident)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(incidents, f, ensure_ascii=False, indent=2)

    # Résumé
    n_corr = sum(len(i["actions_correctives"]) for i in incidents)
    n_prev = sum(len(i["actions_preventives"]) for i in incidents)
    n_cura = sum(len(i.get("actions_curatives", [])) for i in incidents)
    fe_with_actions = sum(1 for i in incidents if i["actions_correctives"] or i["actions_preventives"])
    print(f"FE traités          : {len(incidents):,}")
    print(f"FE avec actions     : {fe_with_actions:,}  ({fe_with_actions/len(incidents)*100:.1f}%)")
    print(f"  actions_correctives : {n_corr:,}")
    print(f"  actions_preventives : {n_prev:,}")
    print(f"  actions_curatives   : {n_cura:,}")
    print(f"Fichier écrit       : {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Convertit le CSV actions en JSON structuré.")
    parser.add_argument(
        "--input",
        default="data/samples/aeroportsdelyon_export_securite_aeroport_actions_20260701_160819.csv",
    )
    parser.add_argument(
        "--output",
        default="data/samples/incidents_avec_actions.json",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    input_path  = Path(args.input) if Path(args.input).is_absolute() else root / args.input
    output_path = Path(args.output) if Path(args.output).is_absolute() else root / args.output

    if not input_path.exists():
        print(f"[ERREUR] Fichier introuvable : {input_path}", file=sys.stderr)
        sys.exit(1)

    csv_to_json(input_path, output_path)


if __name__ == "__main__":
    main()
