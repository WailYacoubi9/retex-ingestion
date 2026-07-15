"""
Enrichissement LLM des incidents sécurité v2.

Génère un résumé narratif à partir des champs textuels de la fiche.
Appelé par le pipeline d'ingestion (--with-llm) et par scripts/enrich_resumes.py.

Garde-fous (leçons du banc qualité du 2026-07-03) :
  - seuil de contexte relevé : sous MIN_CONTEXT caractères, pas de résumé
    (le détail brut EST le résumé — les modèles inventent sur les fiches pauvres)
  - prompt anti-invention (aucun fait absent de la source)
  - contrôles post-génération : refus/écho, alphabet non latin (qwen dérive
    parfois en chinois), formules de remplissage — avec UNE relance, sinon abandon
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from clients import OllamaClient
from models_incident_securite_v2 import IncidentSecuriteV2Canonique

logger = logging.getLogger(__name__)

LLM_MODEL = "qwen2.5:7b"       # choix par défaut ; le banc comparatif peut le changer
MAX_CONTEXT_LENGTH = 3000
MIN_CONTEXT = 100              # en dessous : le détail brut suffit, pas de résumé
                               # (150 validé 07/07 ; abaissé à 100 le 13/07 — fiches 100-149c
                               #  ont titre+detail suffisants pour 1 phrase fidèle)

# Le prompt vit dans un fichier éditable par un non-technicien.
# Chargé à chaque exécution du pipeline (processus batch → toujours à jour).
_PROMPT_FICHIER = Path(__file__).resolve().parent / "config" / "prompts" / "resume_incident.txt"
PROMPT_TEMPLATE = _PROMPT_FICHIER.read_text(encoding="utf-8")

# ─── Contrôles post-génération ───────────────────────────────────────────────

_REFUS = ("je ne peux", "je suis désolé", "désolé,", "en tant qu'ia",
          "en tant que modèle", "je suis un assistant", "veuillez fournir",
          "pouvez-vous fournir", "résumé :", "voici un résumé", "voici le résumé")

# CJK, cyrillique, arabe… : tout alphabet inattendu dans un résumé français
_NON_LATIN = re.compile(r"[Ѐ-ӿ؀-ۿ一-鿿぀-ヿ가-힯]")

_REMPLISSAGE = (
    "des mesures correctives ont été prises",
    "des mesures ont été prises",
    "les causes exactes n'ont pas été",
    "les causes n'ont pas été précisées",
    "aucune information supplémentaire",
)


def valider_resume(texte: str) -> Optional[str]:
    """Retourne None si le résumé est acceptable, sinon le motif de rejet."""
    t = (texte or "").strip()
    if len(t) < 30:
        return "trop court"
    low = t.lower()
    if any(m in low for m in _REFUS):
        return "refus ou écho de consigne"
    if _NON_LATIN.search(t):
        return "alphabet non latin"
    if sum(low.count(f) for f in _REMPLISSAGE) >= 2 or (
            len(t) < 120 and any(f in low for f in _REMPLISSAGE)):
        return "formules de remplissage"
    return None


def enrich_incident(
    ollama: OllamaClient,
    inc: IncidentSecuriteV2Canonique,
    model: str = LLM_MODEL,
) -> Optional[str]:
    """Génère un résumé validé. Retourne None si contexte insuffisant ou rejets répétés."""
    context = _build_context(inc)
    if not context:
        return None

    prompt = PROMPT_TEMPLATE
    for cle, val in context.items():
        prompt = prompt.replace('{' + cle + '}', str(val))
    # Une section vide (« Causes : » sans valeur) pousse le modèle à inventer
    # du contenu pour la remplir → on retire ces lignes du prompt.
    _SECTIONS = ("Incident :", "Description :", "Analyse à chaud :",
                 "Action corrective :", "Causes :", "Vérification :")
    prompt = "\n".join(
        l for l in prompt.splitlines()
        if not (any(l.startswith(s) for s in _SECTIONS) and not l.split(":", 1)[1].strip())
    )
    for tentative in (1, 2):
        try:
            # température 0 : génération DÉTERMINISTE (reproductible, testable)
            resume = ollama.generate(model=model, prompt=prompt,
                                     temperature=0.0).strip()
        except Exception as e:
            logger.warning("Génération échouée pour %s : %s", inc.numero_fe, e)
            return None
        motif = valider_resume(resume)
        if motif is None:
            inc.resume_llm = resume
            inc.llm_model = model
            return resume
        logger.info("Résumé rejeté (%s) pour %s — tentative %d",
                    motif, inc.numero_fe, tentative)
    return None


def _texte_utile(val: Optional[str]) -> str:
    """Valeur nettoyée, vide si placeholder ('0', vide…)."""
    v = (val or "").strip()
    return "" if v in ("", "0") else v


def _build_context(inc: IncidentSecuriteV2Canonique) -> Optional[dict]:
    """Contexte textuel — TOUS les champs narratifs de qualité de la fiche.

    None si trop peu de contenu (le détail brut suffit alors).
    """
    description = _texte_utile(inc.detail)
    analyse = _texte_utile(getattr(inc, "analyse_chaud", None))
    action = _texte_utile(inc.action_corrective)
    verification = _texte_utile(getattr(inc, "detail_verification", None))
    causes = " | ".join(filter(
        lambda x: x and x.strip() not in ("0", ""),
        [inc.desc_cause_1, inc.desc_cause_3, inc.desc_cause_5]
    ))

    total = len(description) + len(analyse) + len(action) + len(verification) + len(causes)
    if total < MIN_CONTEXT:
        return None

    return {
        "titre": (inc.titre or "")[:200],
        "description": description[:MAX_CONTEXT_LENGTH],
        "analyse": analyse[:800],
        "action": action[:500],
        "causes": causes[:500],
        "verification": verification[:500],
    }
