"""
Enrichissement LLM des Info Securite DGAC.

Strategie V1 : un seul appel LLM par IS, qui produit un resume
oriente "point de vue d'un operateur qui rencontre le probleme".

Pas d'etiquettes de classification en V1. Decision motivee : on attend
de voir les vrais cas d'usage avant de figer une taxonomie. Le resume
est suffisant pour le matching semantique en RAG ("j'ai rencontre ce
probleme, quels conseils ?").

L'enricher est volontairement decouple :
  - Prend en entree un InfoSecuriteCanonique deja parse
  - Recoit un OllamaClient (injection de dependance pour testabilite)
  - Modifie le dataclass en place en attachant un LLMResumeOperateur
  - Retourne le dataclass enrichi

En cas d'echec LLM, le dataclass est retourne sans modification de
canonique.llm (qui reste None). Le loader saura gerer ce cas.
"""
from __future__ import annotations

import logging
from typing import Optional

from clients import OllamaClient
from models_info_securite import (
    InfoSecuriteCanonique,
    LLMResumeOperateur,
)


logger = logging.getLogger(__name__)


# Limites par defaut. Llama 3.1 8B accepte 128k tokens mais on veut un
# prompt court pour rester rapide et focalise. ~8000 chars = ~2000 tokens.
DEFAULT_MAX_INPUT_CHARS = 8000

# Modele par defaut, override possible via OllamaClient ou argument.
DEFAULT_LLM_MODEL = "llama3.1:8b"


# =====================================================================
# CONSTRUCTION DU PROMPT
# =====================================================================

SYSTEM_INSTRUCTIONS = (
    "Tu es un assistant qui resume des bulletins de securite aeronautique de la DGAC.\n"
    "Tu produis un resume centre sur le point de vue d'un operateur "
    "(pilote, exploitant, controleur) qui rencontrerait concretement le probleme decrit.\n\n"
    "Ton resume doit :\n"
    "- Faire 3 a 4 phrases maximum\n"
    "- Decrire le risque ou le probleme operationnel terrain\n"
    "- Mentionner les facteurs aggravants, contextes typiques, ou mecanismes causaux\n"
    "- Etre 100% descriptif, jamais prescriptif\n"
    "- Ne JAMAIS contenir de phrase commencant par 'Les operateurs doivent', "
    "'Les pilotes doivent', 'Il faut', 'La DGAC recommande', 'Il convient de'\n"
    "- Ne JAMAIS dire ce qu'il faut faire, seulement decrire ce qui se passe\n"
    "- Ne pas commencer par \"Cette IS\" ou \"Ce bulletin\"\n\n"
    "Tu reponds uniquement par le resume, sans preambule, sans titre, sans guillemets."
)


def _strip_html_tags(text: Optional[str]) -> str:
    """Retire les balises <br> pour avoir un texte plus propre dans le prompt.

    Utilisation : OpenDataLoader laisse beaucoup de <br><br> dans les
    champs. Le LLM comprend mieux du texte propre avec des newlines.

    Args:
        text: Le texte a nettoyer. None est gere (retourne "").

    Returns:
        Le texte sans balises HTML, avec espaces collapses.
    """
    if not text:
        return ""
    # Remplacer <br><br> par double newline, <br> par espace
    cleaned = text.replace("<br><br>", "\n\n").replace("<br>", " ")
    # Collapse les espaces multiples (en gardant les newlines)
    import re
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def build_prompt(
    canonique: InfoSecuriteCanonique,
    max_input_chars: int = DEFAULT_MAX_INPUT_CHARS,
) -> str:
    """Construit le prompt complet a envoyer au LLM.

    Utilisation : concatene SYSTEM_INSTRUCTIONS + contenu de l'IS
    (sujet, objectif, contexte, actions). Tronque proportionnellement
    si le total depasse max_input_chars pour ne pas exploser la fenetre
    de contexte du LLM.

    Args:
        canonique: L'IS parsee a resumer.
        max_input_chars: Budget total en caracteres pour les champs source.

    Returns:
        Le prompt complet, pret a etre envoye via OllamaClient.generate().
    """
    sujet = _strip_html_tags(canonique.sujet) or "(non specifie)"
    objectif = _strip_html_tags(canonique.objectif) or "(non specifie)"
    contexte = _strip_html_tags(canonique.contexte) or "(non specifie)"
    actions = _strip_html_tags(canonique.actions_recommandees) or "(non specifie)"

    # Budget : sujet et objectif sont courts par construction. On donne
    # priorite au contexte et aux actions (les blocs narratifs).
    sujet_max = 500
    objectif_max = 500
    sujet = sujet[:sujet_max]
    objectif = objectif[:objectif_max]

    remaining_budget = max_input_chars - len(sujet) - len(objectif) - 500  # marge
    if remaining_budget < 1000:
        remaining_budget = 1000

    # Tout le budget restant pour le contexte (les actions ne sont plus dans le prompt)
    contexte = contexte[:remaining_budget]
    # actions reste defini plus haut pour l'instant, mais non utilise dans user_content

    user_content = (
        f"Voici une Info Securite DGAC. Resume UNIQUEMENT le probleme terrain "
        f"et ses mecanismes, sans mentionner les actions a entreprendre.\n\n"
        f"SUJET : {sujet}\n\n"
        f"OBJECTIF : {objectif}\n\n"
        f"CONTEXTE :\n{contexte}"
    )

    full_prompt = f"{SYSTEM_INSTRUCTIONS}\n\n---\n\n{user_content}"
    return full_prompt


# =====================================================================
# ENRICHISSEMENT
# =====================================================================

def _clean_resume(resume_brut: str) -> str:
    """Nettoie le resume retourne par le LLM.

    Utilisation : retire les guillemets parasites en debut/fin, les
    prefixes type "Resume :", les sauts de ligne aberrants.

    Args:
        resume_brut: La string brute retournee par OllamaClient.generate().

    Returns:
        Le resume nettoye, pret a etre stocke dans LLMResumeOperateur.
    """
    if not resume_brut:
        return ""
    cleaned = resume_brut.strip()

    # Retirer les guillemets ouvrants/fermants
    if cleaned.startswith('"') and cleaned.endswith('"'):
        cleaned = cleaned[1:-1].strip()
    if cleaned.startswith("«") and cleaned.endswith("»"):
        cleaned = cleaned[1:-1].strip()

    # Retirer les prefixes courants que le LLM pourrait ajouter
    prefixes_to_strip = (
        "Resume :", "Résumé :", "Resume:", "Résumé:",
        "Voici le resume :", "Voici le résumé :",
    )
    for prefix in prefixes_to_strip:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()

    return cleaned


def enrich_with_resume_operateur(
    canonique: InfoSecuriteCanonique,
    ollama_client: OllamaClient,
    model: Optional[str] = None,
    max_input_chars: int = DEFAULT_MAX_INPUT_CHARS,
) -> InfoSecuriteCanonique:
    """Enrichit une IS avec un resume LLM oriente operateur.

    Utilisation : modifie le dataclass en place en remplissant le champ
    canonique.llm. Si l'appel LLM echoue, log un warning et retourne
    le dataclass sans modification (canonique.llm reste None).

    Args:
        canonique: L'IS parsee a enrichir.
        ollama_client: Client Ollama deja instancie.
        model: Override du modele a utiliser (sinon utilise celui du client).
        max_input_chars: Budget total pour le contenu source du prompt.

    Returns:
        Le meme dataclass, eventuellement avec canonique.llm rempli.
    """
    prompt = build_prompt(canonique, max_input_chars=max_input_chars)
    model_used = model or DEFAULT_LLM_MODEL

    try:
        resume_brut = ollama_client.generate(
            prompt=prompt,
            model=model_used,
            json_format=False,
            temperature=0.3,
        )
    except Exception as e:
        logger.warning(
            "Echec LLM pour %s : %s. canonique.llm reste None.",
            canonique.is_number, e,
        )
        return canonique

    resume = _clean_resume(resume_brut)
    if not resume:
        logger.warning(
            "Resume LLM vide pour %s. canonique.llm reste None.",
            canonique.is_number,
        )
        return canonique

    canonique.llm = LLMResumeOperateur(
        resume=resume,
        model_used=model_used,
    )
    logger.info(
        "Enrichissement OK pour %s : %d chars de resume",
        canonique.is_number, len(resume),
    )
    return canonique