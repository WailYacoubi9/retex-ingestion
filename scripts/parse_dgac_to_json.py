"""
Batch : applique parser_dgac sur les 53 Markdown DGAC et serialise
le resultat en JSON dans data/samples/dgac_canonique/.

Pas d'enrichissement LLM, pas de Neo4j, pas de Qdrant. Juste une etape
intermediaire pour valider le parser sur tout le corpus avant d'enchainer.

Produit un rapport synthetique : couverture par champ, taille moyenne
des contenus, IS atypiques a inspecter.

Usage :
    python scripts/parse_dgac_to_json.py
    python scripts/parse_dgac_to_json.py --force   # ecrase les JSON existants
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from parser_dgac import parse_markdown_to_canonique


MD_DIR = PROJECT_ROOT / "data" / "samples" / "dgac_parsed"
JSON_DIR = PROJECT_ROOT / "data" / "samples" / "dgac_canonique"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("parse_dgac_to_json")


def _json_default(obj: Any) -> Any:
    """Serializer JSON pour les types non natifs (date, set, etc.).

    Utilisation : json.dumps(..., default=_json_default).
    """
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, set):
        return sorted(obj)
    raise TypeError(f"Type non serialisable : {type(obj)}")


def parse_and_save_one(md_path: Path, out_path: Path) -> dict:
    """Parse un .md et sauve son dataclass en JSON.

    Utilisation : retourne un dict de stats pour l'agregation finale.

    Args:
        md_path: Chemin du .md a parser.
        out_path: Chemin du .json a creer.

    Returns:
        Dict avec : success (bool), error (str ou None), is_number, et
        flags de presence pour chaque champ canonique.
    """
    try:
        canonique = parse_markdown_to_canonique(md_path)
    except Exception as e:
        logger.error("Echec parsing %s : %s", md_path.name, e)
        return {
            "success": False,
            "error": str(e),
            "file": md_path.name,
        }

    # Serialisation JSON
    payload = asdict(canonique)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )

    return {
        "success": True,
        "error": None,
        "file": md_path.name,
        "is_number": canonique.is_number,
        "has_sujet": bool(canonique.sujet),
        "has_objectif": bool(canonique.objectif),
        "n_operateurs": len(canonique.operateurs_concernes),
        "has_contexte": bool(canonique.contexte),
        "len_contexte": len(canonique.contexte or ""),
        "has_actions": bool(canonique.actions_recommandees),
        "len_actions": len(canonique.actions_recommandees or ""),
        "has_annexe": bool(canonique.annexe),
        "has_references": bool(canonique.references),
        "has_hors_tableau": bool(canonique.contenu_hors_tableau),
        "len_hors_tableau": len(canonique.contenu_hors_tableau or ""),
        "has_version": canonique.version_numero is not None,
        "has_date": canonique.date_version is not None,
        "n_remplace": len(canonique.remplace),
        "n_extra_fields": len(canonique.extra_fields),
        "extra_field_keys": sorted(canonique.extra_fields.keys()),
    }


def run_batch(force: bool) -> int:
    """Orchestre le parsing de toutes les IS et affiche le rapport synthetique.

    Utilisation : point d'entree principal du script.

    Args:
        force: Si True, reecrase les JSON existants.

    Returns:
        Code de sortie (0 si tout OK, 1 si au moins une erreur).
    """
    if not MD_DIR.exists():
        logger.error("Repertoire absent : %s", MD_DIR)
        return 1

    md_files = sorted(MD_DIR.glob("*.md"))
    if not md_files:
        logger.error("Aucun .md trouve dans %s", MD_DIR)
        return 1

    logger.info("IS a parser : %d", len(md_files))
    JSON_DIR.mkdir(parents=True, exist_ok=True)

    all_stats: list[dict] = []
    n_skipped = 0

    for md_path in md_files:
        out_path = JSON_DIR / f"{md_path.stem}.json"

        if out_path.exists() and not force:
            logger.info("Skip (deja parse) : %s", out_path.name)
            n_skipped += 1
            continue

        stats = parse_and_save_one(md_path, out_path)
        all_stats.append(stats)
        if stats["success"]:
            logger.info(
                "OK %s : sujet=%s, ctx=%d, act=%d, hors_tab=%d, extra=%d",
                stats["is_number"],
                "Y" if stats["has_sujet"] else "N",
                stats["len_contexte"],
                stats["len_actions"],
                stats["len_hors_tableau"],
                stats["n_extra_fields"],
            )

    # Rapport synthetique
    successes = [s for s in all_stats if s["success"]]
    failures = [s for s in all_stats if not s["success"]]
    n_total = len(md_files)
    n_processed = len(all_stats)

    logger.info("")
    logger.info("===== Recapitulatif =====")
    logger.info("Total IS               : %d", n_total)
    logger.info("Traitees ce run        : %d", n_processed)
    logger.info("Skippees (deja parsees): %d", n_skipped)
    logger.info("Succes                 : %d", len(successes))
    logger.info("Echecs                 : %d", len(failures))

    if failures:
        logger.warning("Fichiers en echec :")
        for s in failures:
            logger.warning("  %s : %s", s["file"], s["error"])

    if successes:
        logger.info("")
        logger.info("===== Couverture par champ (sur %d succes) =====", len(successes))

        def pct(n: int) -> str:
            return f"{n}/{len(successes)} ({100*n/len(successes):.1f}%)"

        logger.info("sujet             : %s", pct(sum(1 for s in successes if s["has_sujet"])))
        logger.info("objectif          : %s", pct(sum(1 for s in successes if s["has_objectif"])))
        logger.info("contexte          : %s", pct(sum(1 for s in successes if s["has_contexte"])))
        logger.info("actions_recom.    : %s", pct(sum(1 for s in successes if s["has_actions"])))
        logger.info("annexe            : %s", pct(sum(1 for s in successes if s["has_annexe"])))
        logger.info("references        : %s", pct(sum(1 for s in successes if s["has_references"])))
        logger.info("contenu_hors_tab  : %s", pct(sum(1 for s in successes if s["has_hors_tableau"])))
        logger.info("version_numero    : %s", pct(sum(1 for s in successes if s["has_version"])))
        logger.info("date_version      : %s", pct(sum(1 for s in successes if s["has_date"])))
        logger.info("remplace (>=1)    : %s", pct(sum(1 for s in successes if s["n_remplace"] > 0)))
        logger.info("extra_fields (>=1): %s", pct(sum(1 for s in successes if s["n_extra_fields"] > 0)))

        # IS avec extra_fields (pour traçabilite)
        with_extra = [s for s in successes if s["n_extra_fields"] > 0]
        if with_extra:
            logger.info("")
            logger.info("===== IS avec extra_fields =====")
            for s in with_extra:
                logger.info(
                    "%s : %d champs (%s)",
                    s["is_number"],
                    s["n_extra_fields"],
                    ", ".join(s["extra_field_keys"]),
                )

        # IS atypiques : sans sujet, sans contexte, sans actions
        atypiques = [
            s for s in successes
            if not s["has_sujet"] or not s["has_contexte"] or not s["has_actions"]
        ]
        if atypiques:
            logger.info("")
            logger.info("===== IS atypiques (un champ standard manquant) =====")
            for s in atypiques:
                manques = []
                if not s["has_sujet"]:
                    manques.append("sujet")
                if not s["has_contexte"]:
                    manques.append("contexte")
                if not s["has_actions"]:
                    manques.append("actions")
                logger.info("%s : manque %s", s["is_number"], ", ".join(manques))

    logger.info("")
    logger.info("Sortie : %s", JSON_DIR)
    return 0 if not failures else 1


def main() -> int:
    """Point d'entree CLI.

    Utilisation : permet le flag --force pour reecraser les JSON existants.
    """
    parser = argparse.ArgumentParser(
        description="Parse les 53 IS DGAC en JSON canonique."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reecrase les JSON existants",
    )
    args = parser.parse_args()
    return run_batch(force=args.force)


if __name__ == "__main__":
    sys.exit(main())