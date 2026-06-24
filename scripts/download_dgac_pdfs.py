"""
Telecharge les PDFs principaux des Info Securite DGAC.

Lit data/samples/dgac_grouped.json et telecharge uniquement les
pdf_principal (pas les annexes), dans data/samples/dgac_raw/.

Chaque fichier est nomme avec son is_number pour faciliter l'analyse :
    is_2024_01.pdf, is_2023_02.pdf, ...

Idempotent : skip si le fichier existe deja avec une taille non nulle.

Usage :
    python scripts/download_dgac_pdfs.py
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import requests


PROJECT_ROOT = Path(__file__).resolve().parent.parent
GROUPED_PATH = PROJECT_ROOT / "data" / "samples" / "dgac_grouped.json"
OUT_DIR = PROJECT_ROOT / "data" / "samples" / "dgac_raw"

DOWNLOAD_TIMEOUT_SEC = 30
SLEEP_BETWEEN_DOWNLOADS_SEC = 0.5  # politesse envers le serveur DGAC

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; YielooRetexBot/0.1)"
}


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("download_dgac")


def is_number_to_filename(is_number: str) -> str:
    """Convertit '2024/01' en 'is_2024_01.pdf'.

    Utilisation : produit un nom de fichier propre sans slash, qui
    permet ensuite de retrouver l'IS par son numero depuis le nom.
    """
    safe = is_number.replace("/", "_")
    return f"is_{safe}.pdf"


def download_one(url: str, dest_path: Path) -> bool:
    """Telecharge un PDF si pas deja present localement.

    Utilisation : idempotent, retourne True si succes (telechargement
    effectif ou fichier deja present), False si echec.
    """
    if dest_path.exists() and dest_path.stat().st_size > 0:
        logger.info("Deja present, skip : %s", dest_path.name)
        return True

    try:
        response = requests.get(
            url,
            headers=HTTP_HEADERS,
            timeout=DOWNLOAD_TIMEOUT_SEC,
            stream=True,
        )
        response.raise_for_status()

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with dest_path.open("wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        size_kb = dest_path.stat().st_size / 1024
        logger.info("Telecharge (%.1f Ko) : %s", size_kb, dest_path.name)
        return True

    except requests.RequestException as e:
        logger.error("Echec %s : %s", url, e)
        return False


def run_download() -> None:
    """Orchestre le telechargement de tous les pdf_principal.

    Utilisation : point d'entree principal du script. Lit le JSON
    groupe, parcourt chaque IS, telecharge son pdf_principal s'il
    existe. Les annexes ne sont pas telechargees ici (V1 minimaliste).
    """
    if not GROUPED_PATH.exists():
        logger.error("Fichier introuvable : %s", GROUPED_PATH)
        logger.error("Lance d'abord scripts/scrape_dgac_links.py puis scripts/group_dgac_links.py")
        return

    groups = json.loads(GROUPED_PATH.read_text(encoding="utf-8"))
    logger.info("IS a traiter : %d", len(groups))

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    stats = {
        "total": 0,
        "downloaded": 0,
        "skipped": 0,
        "failed": 0,
    }

    for group in groups:
        is_number = group.get("is_number")
        pdf_principal = group.get("pdf_principal")
        if not is_number or not pdf_principal:
            continue

        url = pdf_principal.get("url")
        if not url:
            continue

        stats["total"] += 1
        filename = is_number_to_filename(is_number)
        dest_path = OUT_DIR / filename

        already_exists = dest_path.exists() and dest_path.stat().st_size > 0

        success = download_one(url, dest_path)
        if success and already_exists:
            stats["skipped"] += 1
        elif success:
            stats["downloaded"] += 1
            time.sleep(SLEEP_BETWEEN_DOWNLOADS_SEC)
        else:
            stats["failed"] += 1

    logger.info("===== Recap =====")
    logger.info("IS traitees       : %d", stats["total"])
    logger.info("Telecharges       : %d", stats["downloaded"])
    logger.info("Deja presents     : %d", stats["skipped"])
    logger.info("Echecs            : %d", stats["failed"])
    logger.info("Sortie            : %s", OUT_DIR)


if __name__ == "__main__":
    run_download()