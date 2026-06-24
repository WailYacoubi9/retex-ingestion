"""
Parse tous les PDFs DGAC avec OpenDataLoader et produit des Markdown nettoyes.

Pour chaque PDF dans data/samples/dgac_raw/ :
  - Lance OpenDataLoader avec les options validees :
      * reading_order='xycut'         : ordre de lecture XY-Cut++
      * include_header_footer=False   : exclut en-tetes et pieds de page
      * image_output='off'            : ignore les images decoratives
      * format='markdown'             : sortie Markdown structuree
  - Sauve le resultat dans data/samples/dgac_parsed/<nom_du_pdf>.md
  - Idempotent : skip si le .md existe deja

Produit un rapport synthetique en fin d'execution.

Usage :
    python scripts/parse_dgac_pdfs.py
    python scripts/parse_dgac_pdfs.py --force    # force le re-parsing meme si .md existe
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = PROJECT_ROOT / "data" / "samples" / "dgac_raw"
OUT_DIR = PROJECT_ROOT / "data" / "samples" / "dgac_parsed"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("parse_dgac")


def parse_one_pdf(
    pdf_path: Path,
    output_dir: Path,
    force: bool,
) -> tuple[bool, float, int]:
    """Parse un PDF avec OpenDataLoader.

    Utilisation : appelee pour chaque PDF dans le batch. Retourne un
    triplet (succes, duree_secondes, taille_markdown_caracteres).
    Skip si le .md final existe deja sauf si force=True.
    """
    import opendataloader_pdf  # import paresseux

    # Chemin du .md final attendu
    final_md_path = output_dir / f"{pdf_path.stem}.md"

    if final_md_path.exists() and not force:
        size = final_md_path.stat().st_size
        logger.info("Deja parse, skip : %s (%d octets)", final_md_path.name, size)
        return True, 0.0, size

    # OpenDataLoader cree le fichier dans output_dir avec le meme nom
    # que le PDF mais avec .md. Si on lui passe output_dir final
    # directement, le fichier sera la avec le bon nom.
    output_dir.mkdir(parents=True, exist_ok=True)

    # OpenDataLoader cree aussi des fichiers temporaires (json, image dir)
    # qu'on supprimera apres pour ne garder que le .md
    try:
        t0 = time.time()
        opendataloader_pdf.convert(
            input_path=str(pdf_path),
            output_dir=str(output_dir),
            format="markdown",
            reading_order="xycut",
            include_header_footer=False,
            image_output="off",
            quiet=True,
        )
        elapsed = time.time() - t0
    except Exception as e:
        logger.error("Echec parsing %s : %s", pdf_path.name, e)
        return False, 0.0, 0

    # Verifie que le .md a bien ete cree
    if not final_md_path.exists():
        logger.error(
            "Fichier .md attendu introuvable apres parsing : %s",
            final_md_path
        )
        return False, elapsed, 0

    size = final_md_path.stat().st_size
    logger.info(
        "OK (%.1fs, %d octets) : %s",
        elapsed, size, final_md_path.name
    )

    # Nettoyage des artefacts JSON eventuellement crees a cote
    json_artefact = output_dir / f"{pdf_path.stem}.json"
    if json_artefact.exists():
        try:
            json_artefact.unlink()
        except OSError:
            pass

    return True, elapsed, size


def run_batch(force: bool) -> int:
    """Orchestre le parsing de tous les PDFs dans PDF_DIR.

    Utilisation : point d'entree principal du script. Parcourt tous
    les .pdf du dossier, parse chacun via parse_one_pdf, agrege les
    statistiques, affiche un recap final.
    Retourne le code de sortie (0 succes, 1 si echec sur au moins 1 PDF).
    """
    if not PDF_DIR.exists():
        logger.error("Repertoire absent : %s", PDF_DIR)
        logger.error("Telecharge d'abord les PDFs via scripts/download_dgac_pdfs.py")
        return 1

    pdf_files = sorted(PDF_DIR.glob("*.pdf"))
    if not pdf_files:
        logger.error("Aucun PDF trouve dans %s", PDF_DIR)
        return 1

    logger.info("PDFs a traiter : %d", len(pdf_files))
    logger.info("Sortie         : %s", OUT_DIR)
    if force:
        logger.info("Mode FORCE : tous les PDFs seront re-parses meme si .md existe")
    logger.info("")

    stats = {
        "total": len(pdf_files),
        "parsed_ok": 0,
        "skipped": 0,
        "failed": 0,
        "total_duration_sec": 0.0,
        "total_md_bytes": 0,
        "failed_files": [],
    }

    for pdf_path in pdf_files:
        final_md_path = OUT_DIR / f"{pdf_path.stem}.md"
        was_already_there = final_md_path.exists() and not force

        success, duration, size = parse_one_pdf(pdf_path, OUT_DIR, force)

        if success and was_already_there:
            stats["skipped"] += 1
            stats["total_md_bytes"] += size
        elif success:
            stats["parsed_ok"] += 1
            stats["total_duration_sec"] += duration
            stats["total_md_bytes"] += size
        else:
            stats["failed"] += 1
            stats["failed_files"].append(pdf_path.name)

    logger.info("")
    logger.info("===== Recap =====")
    logger.info("PDFs traites      : %d", stats["total"])
    logger.info("Parses (nouveaux) : %d", stats["parsed_ok"])
    logger.info("Skip (deja la)    : %d", stats["skipped"])
    logger.info("Echecs            : %d", stats["failed"])
    if stats["parsed_ok"] > 0:
        avg = stats["total_duration_sec"] / stats["parsed_ok"]
        logger.info(
            "Temps total       : %.1fs (moyenne %.2fs/PDF)",
            stats["total_duration_sec"], avg
        )
    logger.info(
        "Taille totale .md : %.1f Ko",
        stats["total_md_bytes"] / 1024
    )
    if stats["failed_files"]:
        logger.warning("Fichiers en echec :")
        for f in stats["failed_files"]:
            logger.warning("  - %s", f)

    return 0 if stats["failed"] == 0 else 1


def main() -> int:
    """Point d'entree CLI : parse les arguments et lance le batch.

    Utilisation : permet le flag --force pour re-parser meme si
    le .md cible existe deja.
    """
    parser = argparse.ArgumentParser(
        description="Parse les PDFs DGAC avec OpenDataLoader."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force le re-parsing meme si le .md final existe deja",
    )
    args = parser.parse_args()
    return run_batch(force=args.force)


if __name__ == "__main__":
    sys.exit(main())