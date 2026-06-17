"""
Chunker HTML semantique pour les champs detail_nc / cause_nc des tickets.

Contexte : ces champs sont les plus riches du ticket. Ce sont des FILS
CHRONOLOGIQUES ou chaque entree est :
    <span class="bold" data-tippy-content="Prenom NOM">INI</span>
    <span class="libelle_auteur_maj">jj/mm/aaaa hh:mm:ss</span>
    <br/> ...message...
    <hr class="hr_tinymce_historique">   (separateur entre entrees)

Probleme de l'ancien pipeline : tout etait aplati puis vectorise en UN seul
embedding (et tronque a 1500 chars). On perdait la granularite et les noms
d'auteurs (caches dans data-tippy-content).

Ce module produit UNE unite semantique par entree du fil (= 1 futur vecteur),
en conservant l'auteur (nom complet si dispo) et la date en metadonnees, et en
restituant la structure du message (listes -> "- ", titres, paragraphes).

Si le champ n'est pas un fil (pas de marqueur d'auteur), on decoupe par blocs
structurels (titres/paragraphes/listes) ; en dernier recours, un seul chunk.
"""
from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

MIN_CHUNK_CHARS = 25          # en-dessous, on fusionne avec le chunk precedent
MAX_CHUNK_CHARS = 1500        # au-dessus, on re-decoupe par paragraphes

WHITESPACE_RE = re.compile(r"[ \t]+")
MULTI_NEWLINE_RE = re.compile(r"\n{3,}")

# En-tete d'une entree de fil : auteur (data-tippy optionnel) + date
_ENTRY_HEADER_RE = re.compile(
    r'<span class="bold"(?:\s+data-tippy-content="(?P<nom>[^"]*)")?[^>]*>'
    r'(?P<ini>[^<]*)</span>\s*'
    r'<span class="libelle_auteur_maj">(?P<date>[^<]*)</span>',
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class Chunk:
    """Une unite semantique destinee a un embedding."""
    text: str
    kind: str                       # "thread_entry" | "block"
    index: int = 0
    author: Optional[str] = None    # nom complet ou initiales
    date: Optional[str] = None
    heading: Optional[str] = None   # titre de section pour les blocs


def _clean_fragment(fragment: str) -> str:
    """HTML -> texte propre en preservant listes (-) et sauts de ligne."""
    if not fragment:
        return ""
    soup = BeautifulSoup(fragment, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for li in soup.find_all("li"):
        li.insert_before("\n- ")
    for hr in soup.find_all("hr"):
        hr.decompose()
    text = soup.get_text(separator=" ")
    text = html.unescape(text)
    text = WHITESPACE_RE.sub(" ", text)
    text = MULTI_NEWLINE_RE.sub("\n\n", text)
    # nettoie les espaces autour des sauts de ligne
    text = "\n".join(line.strip() for line in text.splitlines())
    return text.strip()


def _split_long(text: str) -> list[str]:
    """Re-decoupe un texte trop long par double saut de ligne (paragraphes)."""
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    parts, cur = [], ""
    for para in text.split("\n\n"):
        if cur and len(cur) + len(para) > MAX_CHUNK_CHARS:
            parts.append(cur.strip())
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur.strip():
        parts.append(cur.strip())
    return parts


def _chunk_thread(raw_html: str) -> list[Chunk]:
    """Decoupe un fil chronologique en une entree par auteur/date."""
    headers = list(_ENTRY_HEADER_RE.finditer(raw_html))
    if not headers:
        return []

    chunks: list[Chunk] = []
    for i, h in enumerate(headers):
        body_start = h.end()
        body_end = headers[i + 1].start() if i + 1 < len(headers) else len(raw_html)
        body = _clean_fragment(raw_html[body_start:body_end])
        if not body:
            continue
        author = (h.group("nom") or "").strip() or (h.group("ini") or "").strip() or None
        date = (h.group("date") or "").strip() or None
        for piece in _split_long(body):
            if len(piece) < MIN_CHUNK_CHARS and chunks:
                # trop court : on rattache au chunk precedent
                chunks[-1].text = f"{chunks[-1].text}\n{piece}".strip()
                continue
            chunks.append(Chunk(text=piece, kind="thread_entry", author=author, date=date))
    return chunks


def _chunk_blocks(raw_html: str) -> list[Chunk]:
    """Decoupe un contenu non-fil par blocs structurels (titres/listes/paragraphes)."""
    soup = BeautifulSoup(raw_html or "", "html.parser")
    chunks: list[Chunk] = []
    current_heading: Optional[str] = None

    # Conteneurs de blocs de premier niveau
    block_tags = ["h1", "h2", "h3", "h4", "p", "ul", "ol", "table", "blockquote"]
    blocks = soup.find_all(block_tags)

    if not blocks:
        text = _clean_fragment(raw_html)
        return [Chunk(text=t, kind="block") for t in _split_long(text) if len(t) >= MIN_CHUNK_CHARS] or (
            [Chunk(text=text, kind="block")] if text else []
        )

    for b in blocks:
        if not isinstance(b, Tag):
            continue
        if b.name in ("h1", "h2", "h3", "h4"):
            current_heading = _clean_fragment(str(b)) or current_heading
            continue
        text = _clean_fragment(str(b))
        if not text:
            continue
        for piece in _split_long(text):
            if len(piece) < MIN_CHUNK_CHARS and chunks:
                chunks[-1].text = f"{chunks[-1].text}\n{piece}".strip()
                continue
            chunks.append(Chunk(text=piece, kind="block", heading=current_heading))
    return chunks


def chunk_field(raw_html: Optional[str]) -> list[Chunk]:
    """Decoupe un champ HTML en unites semantiques.

    Args:
        raw_html: Le HTML brut du champ (detail_nc ou cause_nc).

    Returns:
        Liste de Chunk indexes (index 0..n). Vide si pas de contenu.
    """
    if not raw_html or not raw_html.strip():
        return []

    if _ENTRY_HEADER_RE.search(raw_html):
        chunks = _chunk_thread(raw_html)
    else:
        chunks = _chunk_blocks(raw_html)

    for i, c in enumerate(chunks):
        c.index = i
    return chunks
