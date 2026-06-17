"""
Parser tickets intra'know : JSON brut -> TicketCanonique.

Strategie :
  1. Nettoyer le HTML profond (BeautifulSoup) pour titre / detail / resume
  2. Extraire les champs simples et imbriques avec resilience aux nulls
  3. Filtrer le resume natif a < 50 chars apres clean
  4. Aplatir parent en parent_numero_fe uniquement

Dependances : beautifulsoup4 (pip install beautifulsoup4).
"""
from __future__ import annotations

import html
import logging
import re
from typing import Any, Optional

from bs4 import BeautifulSoup

from html_chunker import chunk_field
from models_tickets import TicketCanonique, make_ticket_uuid


logger = logging.getLogger(__name__)

RESUME_MIN_LENGTH = 50
CAUSE_NC_MAX_LENGTH = 4000

WHITESPACE_RE = re.compile(r"[ \t]+")
MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


def clean_html(raw: Optional[str]) -> str:
    """Strip HTML profond avec BeautifulSoup + normalisation."""
    if not raw:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    text = soup.get_text(separator=" ")
    text = html.unescape(text)
    text = WHITESPACE_RE.sub(" ", text)
    text = MULTI_NEWLINE_RE.sub("\n\n", text)
    return text.strip()


def _get_nested(d: Optional[dict], *keys: str) -> Any:
    """Acces sur dict imbrique resilient aux None / cles absentes."""
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _safe_int(val: Any) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _safe_str(val: Any) -> Optional[str]:
    if val is None or val == "":
        return None
    return str(val)


def parse_ticket(raw: dict) -> Optional[TicketCanonique]:
    """Transforme un dict ticket source en TicketCanonique.

    Retourne None si le ticket n'a pas de numero_fe exploitable.
    """
    numero_fe = _safe_str(raw.get("numero_fe"))
    if not numero_fe:
        logger.warning("Ticket sans numero_fe, ignore: %s", raw.get("_id"))
        return None

    ticket_id = make_ticket_uuid(numero_fe)

    titre = clean_html(raw.get("titre_nc"))
    detail = clean_html(raw.get("detail_nc"))

    resume_raw = raw.get("resume")
    resume_clean = clean_html(resume_raw)
    resume_natif: Optional[str] = (
        resume_clean if len(resume_clean) >= RESUME_MIN_LENGTH else None
    )

    cause_raw = raw.get("cause_nc")
    cause_clean = clean_html(cause_raw)
    cause_nc: Optional[str] = cause_clean[:CAUSE_NC_MAX_LENGTH] if len(cause_clean) >= RESUME_MIN_LENGTH else None

    type_label = _get_nested(raw, "type_de_de", "_label")
    type_code = _get_nested(raw, "type_de_de", "_code")
    projet_id = _get_nested(raw, "projet_ticket", "_id")
    version_souhaitee_id = _get_nested(raw, "ticket_version_souhaitee", "_id")
    developpeur_login = _get_nested(raw, "developpeur_responsable", "loginUser")
    parent_numero_fe = _get_nested(raw, "parent", "numero_fe")

    version_effective_raw = raw.get("versioneffective")
    if isinstance(version_effective_raw, list) and version_effective_raw:
        version_effective: Optional[str] = ", ".join(
            str(v) for v in version_effective_raw if v
        )[:200] or None
    else:
        version_effective = None

    version_souhaitee_label = _get_nested(raw, "versionsouhaitee", "_label")

    rt = raw.get("resp_traitement_nc")
    resp_traitement_login = rt if isinstance(rt, str) and rt else None

    # Unites semantiques pour l'embedding granulaire (depuis le HTML BRUT)
    detail_chunks = chunk_field(raw.get("detail_nc"))
    cause_chunks = chunk_field(raw.get("cause_nc"))

    return TicketCanonique(
        numero_fe=numero_fe,
        ticket_id=ticket_id,
        titre=titre,
        detail=detail,
        resume_natif=resume_natif,
        cause_nc=cause_nc,
        detail_chunks=detail_chunks,
        cause_chunks=cause_chunks,
        date_nc=_safe_str(raw.get("date_nc")),
        etape=_safe_int(raw.get("etape")),
        archive_nc=_safe_int(raw.get("archive_nc")),
        abbr=_safe_str(raw.get("abbr")),
        type_nc=_safe_str(raw.get("type_nc")),
        importance=_safe_str(raw.get("importance")),
        etat=_safe_str(raw.get("etat")),
        etape_label=_safe_str(raw.get("etape_label")),
        id_type=_safe_int(raw.get("id_type")),
        id_unite=_safe_int(raw.get("id_unite")),
        branche_developpement=_safe_str(raw.get("branchededeveloppement")),
        priorite_projet=_safe_str(raw.get("ticket_priorite_par_projet")),
        version_effective=version_effective,
        version_souhaitee=_safe_str(version_souhaitee_label),
        emetteur_login=_safe_str(raw.get("emetteur_nc")),
        emetteur_id=_safe_int(raw.get("id_emetteur_nc")),
        resp_traitement_login=resp_traitement_login,
        societe_id=_safe_int(raw.get("societe")),
        site_application=_safe_str(raw.get("site_application")),
        projet_id=_safe_str(projet_id),
        projet_nom=_safe_str(raw.get("projet_nom")),
        structure=_safe_str(raw.get("structure")),
        urgence=_safe_str(raw.get("urgence")),
        individu=_safe_str(raw.get("individu")),
        type_label=_safe_str(type_label),
        type_code=_safe_str(type_code),
        version_souhaitee_id=_safe_str(version_souhaitee_id),
        developpeur_login=_safe_str(developpeur_login),
        parent_numero_fe=_safe_str(parent_numero_fe),
    )


def parse_tickets(raw_list: list[dict]) -> list[TicketCanonique]:
    """Parse une liste de tickets, en sautant les invalides."""
    result = []
    skipped = 0
    for raw in raw_list:
        ticket = parse_ticket(raw)
        if ticket is None:
            skipped += 1
            continue
        result.append(ticket)
    if skipped:
        logger.info("Parse: %d tickets OK, %d skipped", len(result), skipped)
    return result
