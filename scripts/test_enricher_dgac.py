"""
Test rapide de l'enrichissement LLM sur une IS donnee.

Charge le JSON parse, applique enrich_with_resume_operateur,
affiche le resume produit pour validation visuelle.

Utile pour iterer sur le prompt avant de lancer le batch sur les 53.

Usage :
    python scripts/test_enricher_dgac.py is_2023_02.json
    python scripts/test_enricher_dgac.py is_2026_01.json
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from clients import OllamaClient
from llm_enricher_info_securite import (
    build_prompt,
    enrich_with_resume_operateur,
)
from models_info_securite import (
    InfoSecuriteCanonique,
    LLMResumeOperateur,
)


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


OLLAMA_URL = "http://localhost:11434"


def _load_canonique_from_json(json_path: Path) -> InfoSecuriteCanonique:
    """Reconstitue un InfoSecuriteCanonique depuis le JSON serialise.

    Utilisation : on a sauve les dataclasses via asdict() qui transforme
    les date en isoformat string. On doit reparser ces dates pour que
    le dataclass soit complet.
    """
    data: dict[str, Any] = json.loads(json_path.read_text(encoding="utf-8"))

    # Reparser la date_version si presente
    date_str = data.get("date_version")
    if date_str:
        data["date_version"] = date.fromisoformat(date_str)

    # Le sous-objet llm n'est pas reinstancie en V1 (None de toute facon
    # pour un JSON pre-enrichissement)
    if data.get("llm"):
        data["llm"] = LLMResumeOperateur(**data["llm"])

    return InfoSecuriteCanonique(**data)


def main() -> int:
    """Point d'entree CLI : enrichit une IS et affiche le resultat."""
    if len(sys.argv) < 2:
        print("Usage : python scripts/test_enricher_dgac.py <nom_fichier.json>")
        return 1

    json_path = PROJECT_ROOT / "data" / "samples" / "dgac_canonique" / sys.argv[1]
    if not json_path.exists():
        print(f"Fichier introuvable : {json_path}")
        return 1

    canonique = _load_canonique_from_json(json_path)

    print(f"===== IS {canonique.is_number} =====")
    print(f"Sujet    : {canonique.sujet}")
    print(f"Objectif : {canonique.objectif}")
    print()

    # Affichage du prompt construit (utile pour debug)
    prompt = build_prompt(canonique)
    print(f"===== Prompt construit ({len(prompt)} chars) =====")
    print(prompt[:1000])
    if len(prompt) > 1000:
        print("...[tronque pour l'affichage]")
    print()

    # Enrichissement
    print("===== Appel LLM =====")
    with OllamaClient(url=OLLAMA_URL) as ollama:
        canonique = enrich_with_resume_operateur(canonique, ollama)

    print()
    print(f"===== Resume produit =====")
    if canonique.llm:
        print(f"Modele : {canonique.llm.model_used}")
        print(f"Longueur : {len(canonique.llm.resume)} chars")
        print()
        print(canonique.llm.resume)
    else:
        print("(echec, llm reste None)")

    return 0


if __name__ == "__main__":
    sys.exit(main())