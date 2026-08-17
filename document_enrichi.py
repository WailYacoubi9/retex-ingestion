"""
Document enrichi — un chunk = une fiche verbalisée (réforme §1, variante D du banc).

Remplace `IncidentSecuriteV2Canonique.textes_pour_embedding()` (un chunk par champ)
par UN document par fiche : ligne d'identité, ligne de métadonnées VALEURS SEULES
(pas d'étiquettes `Type:`/`Lieu:` — IDF nul, homogénéisent), puis les narratifs.

Mesuré sur banc (bge-m3, bootstrap apparié) : rappel@10 40,0 % -> 58,4 %.

Le loader appelle `construire_chunks(inc, titres_actions)`. La fonction reste pure :
elle ne reçoit qu'un modèle typé + une liste de titres déjà dédupliqués (la lecture
du payload brut des actions se fait côté ingestion, cf. extractor.titres_actions_du_payload).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

# Seuils en CARACTÈRES (proxy ~3,8 car/token).
# SEUIL_DECOUPE = 1800 (~470 tok) : ne découpe que ~5,4 % de fiches (les plus longues),
#   conforme au « < 5 % » du brief ; « 250 tok » découperait 16 % (incohérent avec son « <5 % »).
# PLANCHER = 50 : garde-fou seulement — aucune fiche réelle n'est sous ce seuil (min mesuré
#   = 102 car : titre + métadonnées). Le brief supposait ~2 fiches vides ; il n'y en a AUCUNE,
#   et un plancher à 150 dropperait 57 fiches legacy à titre porteur (régression).
SEUIL_DECOUPE = 1800
PLANCHER = 50

# Relations réelles du schéma (EntiteLiee.relation) utilisées dans la ligne de métadonnées.
_REL_TYPE = "DE_TYPE"
_REL_LIEU = "LOCALISE_EN"
_REL_PHASE = "EN_PHASE_DE_VOL"
_REL_COMPAGNIE = "IMPLIQUE_COMPAGNIE"
_REL_AERONEF = "IMPLIQUE_AERONEF"
_REL_UNITE = "CONCERNE_UNITE"
_REL_NOTIFIANT = "NOTIFIE_PAR"

# Axes causaux : (attribut flag, attribut texte, libellé affiché), ordre 6M canonique.
_AXES = [
    ("facteur_mo", "cause_mo", "Main d'œuvre"),
    ("facteur_methode", "cause_methode", "Méthodes"),
    ("facteur_machine", "cause_machine", "Machines"),
    ("facteur_mp", "cause_mp", "Matières premières"),
    ("facteur_milieu", "cause_milieu", "Milieu"),
    ("facteur_management", "cause_management", "Management"),
]


def _val(v: Any) -> str:
    """Normalise une valeur scalaire en texte propre, '' si vide."""
    if v is None:
        return ""
    if isinstance(v, (datetime, date)):
        return v.strftime("%d/%m/%Y")
    return str(v).strip()


def _rel(inc, relation: str) -> str:
    """Valeurs d'une relation depuis inc.entites (multi-valué -> liste virgulée, dédup ordonnée)."""
    vus: list[str] = []
    for e in getattr(inc, "entites", []) or []:
        if getattr(e, "relation", None) == relation:
            val = _val(getattr(e, "valeur", None))
            if val and val not in vus:
                vus.append(val)
    return ", ".join(vus)


def _ligne_metadonnees(inc) -> str:
    """Ligne 2 : VALEURS SEULES séparées par ' | ', dans l'ordre, en sautant les vides."""
    pieces = [
        _rel(inc, _REL_TYPE),
        _val(getattr(inc, "type_evenement_autre", None)),
        _rel(inc, _REL_LIEU),
        _val(getattr(inc, "precisions_lieu", None)),
        _val(getattr(inc, "date_evenement", None)),
        _val(getattr(inc, "severite", None)),
        _val(getattr(inc, "classification", None)),
        _rel(inc, _REL_PHASE),
        _rel(inc, _REL_COMPAGNIE),
        _rel(inc, _REL_AERONEF),
        _rel(inc, _REL_UNITE),
        _rel(inc, _REL_NOTIFIANT),
        _val(getattr(inc, "condition_lumineuse", None)),
    ]
    return " | ".join(p for p in pieces if p)


def _ligne_facteurs(inc) -> str:
    """'Facteurs : ...' — libellés des axes cochés (facteur_* == True), ordre 6M. '' si aucun."""
    coches = [lib for flag, _txt, lib in _AXES if getattr(inc, flag, None) is True]
    return f"Facteurs : {', '.join(coches)}" if coches else ""


def _lignes_narratif(inc, titres_actions: Optional[list[str]]) -> list[str]:
    """Blocs narratifs, une ligne chacun, en sautant les vides."""
    lignes: list[str] = []

    def ajout(prefixe: str, valeur: str) -> None:
        v = _val(valeur)
        if v:
            lignes.append(f"{prefixe} : {v}")

    ajout("Description", getattr(inc, "detail", None))
    ajout("Analyse à chaud", getattr(inc, "premiere_analyse_terrain", None))

    causes = [
        f"{lib} — {_val(getattr(inc, txt, None))}"
        for _flag, txt, lib in _AXES
        if _val(getattr(inc, txt, None))
    ]
    if causes:
        lignes.append("Causes : " + " ; ".join(causes))

    ajout("Action immédiate", getattr(inc, "action_corrective", None))

    if titres_actions:
        lignes.append("Actions engagées : " + " ; ".join(titres_actions))

    ajout("Vérification", getattr(inc, "detail_verification", None))
    return lignes


def _decouper(narratif: list[str], prefixe: str, budget: int) -> list[list[str]]:
    """Répartit les lignes de narratif en segments dont (prefixe + segment) tient dans le budget.

    Une ligne seule plus longue que le budget est coupée durement sur des espaces.
    """
    segments: list[list[str]] = []
    courant: list[str] = []
    taille = len(prefixe)

    def pousser() -> None:
        nonlocal courant, taille
        if courant:
            segments.append(courant)
            courant, taille = [], len(prefixe)

    for ligne in narratif:
        # ligne trop longue à elle seule -> découpe dure
        morceaux = [ligne]
        while len(morceaux[-1]) > budget - len(prefixe):
            tete = morceaux[-1]
            coupe = tete.rfind(" ", 0, budget - len(prefixe))
            if coupe <= 0:
                coupe = budget - len(prefixe)
            morceaux[-1:] = [tete[:coupe].rstrip(), tete[coupe:].lstrip()]
        for m in morceaux:
            if courant and taille + 1 + len(m) > budget:
                pousser()
            courant.append(m)
            taille += (1 if len(courant) > 1 else 0) + len(m)
    pousser()
    return segments


def _texte_causes(inc) -> str:
    """Texte causal SEUL (pour un chunk dédié = vecteur par-champ retrouvé). '' si aucun."""
    causes = [f"{lib} — {_val(getattr(inc, txt, None))}"
              for _f, txt, lib in _AXES if _val(getattr(inc, txt, None))]
    return "Causes : " + " ; ".join(causes) if causes else ""


def _texte_actions(inc, titres_actions: Optional[list[str]]) -> str:
    """Texte d'action SEUL (action immédiate + actions engagées). '' si aucun."""
    parts = []
    ac = _val(getattr(inc, "action_corrective", None))
    if ac:
        parts.append(f"Action immédiate : {ac}")
    if titres_actions:
        parts.append("Actions engagées : " + " ; ".join(titres_actions))
    return "\n".join(parts)


def construire_chunks(inc, titres_actions: Optional[list[str]] = None) -> list[tuple[str, str]]:
    """Construit le(s) chunk(s) d'une fiche.

    Retourne une liste de (field_canonical, texte) :
      - 'fiche'         : chunk principal (identité + métadonnées + facteurs + narratif) ;
      - 'narratif_long' : chunk(s) supplémentaire(s) si le document dépasse SEUIL_DECOUPE ;
      - 'cause'/'action': chunks DÉDIÉS (design hybride) — rendent au champ cause/action son
                          vecteur propre, que la fusion diluait (récupère la récup par-champ des
                          voies synthèse/recommandation) sans perdre le gain fusion du chunk 'fiche'.
    Fiche trop maigre (< PLANCHER) -> pas de chunk 'fiche' (mais cause/action restent possibles).
    """
    numero_fe = _val(getattr(inc, "numero_fe", None))
    titre = _val(getattr(inc, "titre", None))
    identite = f"Fiche {numero_fe} — {titre}" if titre else f"Fiche {numero_fe}"

    meta = _ligne_metadonnees(inc)
    facteurs = _ligne_facteurs(inc)
    entete = [identite] + [l for l in (meta, facteurs) if l]

    narratif = _lignes_narratif(inc, titres_actions)
    document = "\n".join(entete + narratif)

    chunks: list[tuple[str, str]] = []
    if len(document) >= PLANCHER:
        if len(document) <= SEUIL_DECOUPE:
            chunks.append(("fiche", document))
        else:
            # Découpe secondaire : chaque chunk overflow porte la ligne de métadonnées en préfixe.
            prefixe = meta or identite
            for i, seg in enumerate(_decouper(narratif, prefixe + "\n", SEUIL_DECOUPE)):
                if i == 0:
                    texte = "\n".join(entete + seg)
                else:
                    texte = "\n".join(([prefixe] if prefixe else []) + seg)
                chunks.append(("fiche" if i == 0 else "narratif_long", texte))

    # Chunks dédiés cause / action (vecteur par-champ retrouvé)
    ct = _texte_causes(inc)
    if ct:
        chunks.append(("cause", ct))
    at = _texte_actions(inc, titres_actions)
    if at:
        chunks.append(("action", at))
    return chunks
