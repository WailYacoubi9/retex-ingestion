"""
Enrichissement LLM des incidents sécurité v2.

Génère un résumé narratif via llama3.1:8b à partir des champs textuels
de IncidentSecuriteV2Canonique. Appelé optionnellement par le pipeline
d'ingestion avec --with-llm.
"""
from __future__ import annotations

import logging
from typing import Optional

from clients import OllamaClient
from models_incident_securite_v2 import IncidentSecuriteV2Canonique

logger = logging.getLogger(__name__)

LLM_MODEL = "llama3.1:8b"
MAX_CONTEXT_LENGTH = 3000

PROMPT_TEMPLATE = """Tu es un expert en sécurité aéroportuaire. Résume cet incident en 3 phrases maximum, en français, sans répéter la consigne. Commence directement par le résumé.

Incident : {titre}
Description : {description}
Action corrective : {action}
Causes : {causes}

Résumé :"""


def enrich_incident(
    ollama: OllamaClient,
    inc: IncidentSecuriteV2Canonique,
) -> Optional[str]:
    """Génère un résumé LLM pour l'incident. Retourne None si échec ou pas assez de contexte."""
    context = _build_context(inc)
    if not context:
        return None
    try:
        resume = ollama.generate(
            model=LLM_MODEL,
            prompt=PROMPT_TEMPLATE.format(**context),
        )
        inc.resume_llm = resume.strip()
        inc.llm_model = LLM_MODEL
        return inc.resume_llm
    except Exception as e:
        logger.warning("Enrichissement LLM échoué pour %s : %s", inc.numero_fe, e)
        return None


def _build_context(inc: IncidentSecuriteV2Canonique) -> Optional[dict]:
    """Construit le contexte textuel. Retourne None si trop peu de contenu."""
    description = inc.detail or ""
    action = inc.action_corrective if inc.action_corrective and inc.action_corrective.strip() != "0" else ""
    causes = " | ".join(filter(
        lambda x: x and x.strip() not in ("0", ""),
        [inc.desc_cause_1, inc.desc_cause_3, inc.desc_cause_5]
    ))

    total = len(description) + len(action) + len(causes)
    if total < 50:
        return None

    return {
        "titre": (inc.titre or "")[:200],
        "description": description[:MAX_CONTEXT_LENGTH],
        "action": action[:500],
        "causes": causes[:500],
    }
