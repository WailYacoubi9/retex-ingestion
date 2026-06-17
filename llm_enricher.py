"""
Enrichissement LLM des incidents (v2).

Appelle Llama 3.1 8B pour produire un resume narratif et une
classification (facteur causal, severite, etat final) a partir des
champs textuels du nouveau format canonique.

Adapte au IncidentCanonique v2 (champs detail, recolte_faits, notes_suivi).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from clients import OllamaClient
from models import IncidentCanonique, LLMEnrichment

logger = logging.getLogger(__name__)


# =====================================================================
# CONFIGURATION
# =====================================================================

LLM_MODEL = "llama3.1:8b"

# Valeurs autorisees pour la classification (validation cote client)
ALLOWED_FACTEURS = {"humain", "technique", "organisationnel", "externe", "inconnu"}
ALLOWED_SEVERITES = {"mineure", "moderee", "majeure", "critique", "inconnu"}
ALLOWED_ETATS = {"resolu", "en_cours", "non_resolu", "inconnu"}

# Limite de longueur du contexte donne au LLM (caracteres)
MAX_CONTEXT_LENGTH = 3000


# =====================================================================
# POINT D'ENTREE PRINCIPAL
# =====================================================================

def enrich_incident(
    ollama: OllamaClient,
    incident: IncidentCanonique,
) -> Optional[LLMEnrichment]:
    """Enrichit un incident avec un resume + classification LLM.

    Utilisation : appelee par le pipeline d'ingestion pour les incidents
    avec narratif suffisant. Retourne None si pas assez de contexte ou
    si le LLM echoue de maniere recuperable.
    """
    context = _build_context(incident)
    if not context:
        return None

    try:
        resume = _generate_resume(ollama, context, incident.titre)
        classification = _generate_classification(ollama, context)
    except Exception as e:
        logger.warning(
            "Erreur LLM sur incident %s : %s",
            incident.incident_id_source, e,
        )
        return None

    return LLMEnrichment(
        resume=resume,
        facteur_causal=classification.get("facteur_causal"),
        severite_percue=classification.get("severite_percue"),
        etat_final=classification.get("etat_final"),
        model_used=LLM_MODEL,
    )


# =====================================================================
# CONSTRUCTION DU CONTEXTE TEXTUEL
# =====================================================================

def _build_context(incident: IncidentCanonique) -> Optional[str]:
    """Concatene les champs narratifs disponibles en un seul bloc.

    Utilisation : prepare le contexte qui sera passe au LLM. Lit les
    champs canoniques v2 (detail, recolte_faits, notes_suivi) et
    s'arrete a MAX_CONTEXT_LENGTH pour eviter les depassements.
    """
    parts: list[str] = []

    if incident.titre:
        parts.append(f"Titre : {incident.titre}")

    if incident.detail:
        parts.append(f"Description : {incident.detail}")

    if incident.recolte_faits:
        parts.append(f"Faits recueillis : {incident.recolte_faits}")

    if incident.notes_suivi:
        parts.append(f"Notes de suivi : {incident.notes_suivi}")

    if not parts:
        return None

    full_text = "\n\n".join(parts)

    if len(full_text) > MAX_CONTEXT_LENGTH:
        full_text = full_text[:MAX_CONTEXT_LENGTH] + "..."

    return full_text


# =====================================================================
# GENERATION DU RESUME
# =====================================================================

def _generate_resume(
    ollama: OllamaClient,
    context: str,
    titre: Optional[str],
) -> Optional[str]:
    """Genere un resume en 1-2 phrases du contexte fourni.

    Utilisation : interne. Le prompt est strict pour limiter les
    hallucinations et forcer un format court factuel.
    """
    prompt = f"""Tu es un expert en analyse d'incidents de securite aeronautique.

Voici les informations sur un incident :

{context}

Produis un resume factuel en 1 a 2 phrases (maximum 50 mots).
Reste fidele aux faits. N'invente rien.
Reponds uniquement avec le resume, sans preambule ni commentaire.

Resume :"""

    response = ollama.generate(model=LLM_MODEL, prompt=prompt)
    if not response:
        return None

    cleaned = response.strip()
    # Retire les eventuels prefixes ajoutes par le LLM
    for prefix in ["Resume :", "Resume:", "Voici le resume :"]:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()

    if len(cleaned) < 10:
        return None

    return cleaned


# =====================================================================
# GENERATION DE LA CLASSIFICATION
# =====================================================================

def _generate_classification(
    ollama: OllamaClient,
    context: str,
) -> dict:
    """Genere la classification 3 axes (facteur, severite, etat).

    Utilisation : interne. Demande une reponse JSON, valide les valeurs
    contre les listes autorisees, retourne 'inconnu' si invalide.
    """
    prompt = f"""Tu es un expert en analyse d'incidents de securite aeronautique.

Voici les informations sur un incident :

{context}

Classifie cet incident selon trois axes en repondant UNIQUEMENT en JSON :

1. facteur_causal : "humain", "technique", "organisationnel", "externe", ou "inconnu"
2. severite_percue : "mineure", "moderee", "majeure", "critique", ou "inconnu"
3. etat_final : "resolu", "en_cours", "non_resolu", ou "inconnu"

Reponds avec un JSON strict, sans texte autour, sans backticks, sans commentaire.
Format attendu :
{{"facteur_causal": "...", "severite_percue": "...", "etat_final": "..."}}

JSON :"""

    response = ollama.generate(model=LLM_MODEL, prompt=prompt)
    if not response:
        return {}

    parsed = _safe_parse_json(response)
    if not parsed:
        logger.debug("JSON invalide retourne par LLM : %s", response[:200])
        return {}

    return _validate_classification(parsed)


# =====================================================================
# UTILITAIRES DE PARSING ET VALIDATION
# =====================================================================

def _safe_parse_json(response: str) -> Optional[dict]:
    """Tente de parser une reponse LLM en JSON, tolerant aux artefacts.

    Utilisation : interne. Llama peut entourer son JSON de backticks,
    de prefixes "JSON :", ou de commentaires. On tente plusieurs
    strategies de nettoyage avant d'abandonner.
    """
    # Strategie 1 : parsing direct
    try:
        return json.loads(response)
    except (json.JSONDecodeError, TypeError):
        pass

    # Strategie 2 : extraction du premier objet JSON dans la reponse
    match = re.search(r"\{[^{}]*\}", response, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except (json.JSONDecodeError, TypeError):
            pass

    # Strategie 3 : retrait des backticks et prefixes courants
    cleaned = response.strip()
    for prefix in ["```json", "```", "JSON :", "JSON:"]:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].strip()

    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return None


def _validate_classification(parsed: dict) -> dict:
    """Valide les valeurs de classification contre les listes autorisees.

    Utilisation : interne. Garantit qu'on ne stocke que des valeurs
    canoniques en base, meme si le LLM hallucine. Les valeurs hors
    liste sont remplacees par 'inconnu'.
    """
    facteur = str(parsed.get("facteur_causal", "")).strip().lower()
    if facteur not in ALLOWED_FACTEURS:
        facteur = "inconnu"

    severite = str(parsed.get("severite_percue", "")).strip().lower()
    if severite not in ALLOWED_SEVERITES:
        severite = "inconnu"

    etat = str(parsed.get("etat_final", "")).strip().lower()
    if etat not in ALLOWED_ETATS:
        etat = "inconnu"

    return {
        "facteur_causal": facteur,
        "severite_percue": severite,
        "etat_final": etat,
    }
