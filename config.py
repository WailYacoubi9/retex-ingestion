"""
Configuration centrale — charge le .env et expose les variables d'environnement.

Tous les scripts d'ingestion importent depuis ce module :
    from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, QDRANT_URL, OLLAMA_URL

Créer un fichier .env à la racine du projet (voir .env.example).
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
TICKETS_LLM_MODEL = os.environ.get("TICKETS_LLM_MODEL", "qwen2.5:7b")
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "600"))

if not NEO4J_PASSWORD:
    raise RuntimeError(
        "NEO4J_PASSWORD non défini. "
        "Créez un fichier .env à la racine du projet (voir .env.example)."
    )
