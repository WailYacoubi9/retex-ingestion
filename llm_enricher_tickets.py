"""
Enrichissement LLM des tickets intra'know (design "lean").

Principe : ne PAS payer le LLM pour re-deviner ce que la source fournit deja.
Le type (type_nc), l'importance, l'urgence et l'etat/etape viennent du CSV/JSON
(factuels, fiables, gratuits). Le LLM ne genere donc que ce qui manque :

  - resume            : synthese lisible du fil HTML bruite (le seul vrai apport)
  - domaine_technique : seul axe de classif absent de la source

Les champs factuels sont quand meme injectes dans le prompt comme CONTEXTE,
pour que le resume soit pertinent.

Sortie reduite (2 champs) => beaucoup moins de tokens a generer => ~3x plus
rapide que l'ancienne fiche a 10 champs.
"""
from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from typing import Optional

from clients import OllamaClient
from models_tickets import LLMResumeTicket, TicketCanonique


logger = logging.getLogger(__name__)

DEFAULT_MAX_INPUT_CHARS = 6000
DEFAULT_LLM_MODEL = os.environ.get("TICKETS_LLM_MODEL", "qwen2.5:7b")

VALID_DOMAINE = {
    "backend", "frontend", "database", "infra",
    "securite", "integration", "metier", "autre",
}

TYPE_LABELS = {
    "SUP": "Support : incident ou question d'un utilisateur",
    "SRV": "Demande de service : prestation, chiffrage, configuration",
    "OPS": "Operation technique : jobs, exploitation, infrastructure",
    "PRD": "Produit / developpement : evolution, nouvelle fonctionnalite",
    "AUT": "Autre / incident divers",
}

# Tampons "jj/mm/aaaa hh:mm(:ss)" et lignes d'initiales auteur seules
_STAMP_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}(?::\d{2})?")
_AUTHOR_ONLY_RE = re.compile(r"^[A-Z]{2,4}$")


def _denoise(text: Optional[str]) -> str:
    """Retire les tampons auteur/date du fil chronologique."""
    if not text:
        return ""
    text = _STAMP_RE.sub("", text)
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s or _AUTHOR_ONLY_RE.fullmatch(s):
            continue
        lines.append(s)
    return "\n".join(lines)


def _normalize_enum(value: str, allowed: set[str], default: str) -> str:
    """Recale une valeur sur l'ensemble autorise (accents/casse/espaces ignores)."""
    if not value:
        return default
    norm = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    norm = norm.strip().lower().replace(" ", "_").replace("-", "_")
    if norm in allowed:
        return norm
    for a in allowed:
        if norm.startswith(a):
            return a
    return default


SYSTEM_INSTRUCTIONS = """\
Tu es un analyste qui resume des tickets de support/maintenance du systeme \
intra'know. Tu produis une synthese FACTUELLE et fidele au contenu fourni. \
N'invente jamais d'information absente.

On te donne des metadonnees FACTUELLES (type, importance, urgence, etat) : \
sers-t'en comme contexte, NE LES RECLASSE PAS. Ton seul travail de classement \
est le domaine technique.

Reponds UNIQUEMENT avec un objet JSON valide, sans texte ni markdown autour :

{
  "resume": "2 a 4 phrases factuelles : la demande/le probleme/la tache, le contexte (application/projet), et ce qui a ete fait ou ou ca en est (d'apres le fil de suivi). Pas de blabla, pas de prescription.",
  "domaine_technique": "backend|frontend|database|infra|securite|integration|metier|autre"
}

Regles :
- resume en francais, factuel ; integre la resolution si le fil de suivi en montre une.
- domaine_technique : choisis la valeur la plus probable d'apres le contenu technique.\
"""


def build_prompt(ticket: TicketCanonique, max_input_chars: int = DEFAULT_MAX_INPUT_CHARS) -> str:
    type_code = (ticket.type_nc or "").upper()
    type_label = TYPE_LABELS.get(type_code, "Type inconnu")

    detail = _denoise(ticket.detail)
    suivi = _denoise(ticket.cause_nc)
    resume_natif = (ticket.resume_natif or "").strip()[:300]

    budget = max_input_chars - len(resume_natif)
    suivi = suivi[: min(len(suivi), int(budget * 0.55))]
    budget -= len(suivi)
    detail = detail[: max(0, budget)]

    lines = [
        f"TYPE : {type_code} ({type_label})",
        f"IMPORTANCE : {ticket.importance or 'inconnue'}",
        f"URGENCE : {ticket.urgence or 'Non'}",
        f"ETAT : {ticket.etat or ticket.etape_label or 'inconnu'}",
        f"TITRE : {(ticket.titre or '')[:200]}",
        f"APPLICATION : {ticket.site_application or 'inconnue'}",
        f"PROJET : {ticket.projet_nom or 'inconnu'}",
    ]
    if resume_natif:
        lines.append(f"RESUME SAISI : {resume_natif}")
    if detail:
        lines.append(f"\nDEMANDE / DESCRIPTION :\n{detail}")
    if suivi:
        lines.append(f"\nFIL DE SUIVI ET ACTIONS :\n{suivi}")

    return f"{SYSTEM_INSTRUCTIONS}\n\n---\n\n" + "\n".join(lines)


def _parse_llm_json(raw: str, model_used: str) -> Optional[LLMResumeTicket]:
    raw = raw.strip()
    if "```" in raw:
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if m:
            raw = m.group(1)
    if not raw.startswith("{"):
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            raw = m.group(0)

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        logger.debug("JSON parse error : %s | raw=%s", e, raw[:200])
        return None

    resume = str(data.get("resume", "")).strip()
    domaine = _normalize_enum(
        str(data.get("domaine_technique", "")).strip(), VALID_DOMAINE, "autre"
    )
    return LLMResumeTicket(resume=resume, domaine_technique=domaine, model_used=model_used)


def enrich_ticket(
    ticket: TicketCanonique,
    ollama: OllamaClient,
    model: Optional[str] = None,
    max_input_chars: int = DEFAULT_MAX_INPUT_CHARS,
) -> TicketCanonique:
    """Enrichit un ticket avec le LLM (resume + domaine). Modifie ticket.llm en place."""
    model_used = model or DEFAULT_LLM_MODEL
    prompt = build_prompt(ticket, max_input_chars=max_input_chars)

    try:
        raw = ollama.generate(
            prompt=prompt,
            model=model_used,
            json_format=True,
            temperature=0.1,
        )
    except Exception as e:
        logger.warning("Echec LLM pour ticket %s : %s", ticket.numero_fe, e)
        return ticket

    enrichment = _parse_llm_json(raw, model_used)
    if not enrichment or not enrichment.resume:
        logger.warning("JSON LLM invalide pour ticket %s.", ticket.numero_fe)
        return ticket

    ticket.llm = enrichment
    logger.debug("Enrichissement OK pour ticket %s", ticket.numero_fe)
    return ticket
