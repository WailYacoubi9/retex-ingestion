"""Normalisation des lieux : aérodrome, piste, poste, zone — SANS perdre la valeur saisie.

POURQUOI — deux constats du journal des défauts :

  D19  Lyon Saint-Exupéry a renuméroté ses pistes en AIRAC 1610 (octobre 2016), la déclinaison
       magnétique ayant dérivé vers l'ouest : 18L->17L, 18R->17R, 36L->35L, 36R->35R. La même
       piste physique porte donc deux noms selon l'époque, et une question « incidents sur la
       35L » ne répond aujourd'hui que sur 41 % de l'historique réel.

  D21  Le corpus couvre DEUX aérodromes aux référentiels incompatibles : Lyon Saint-Exupéry
       (8 700 fiches, pistes 17L/35R et 17R/35L) et Lyon Bron (491 fiches, piste unique 16/34,
       sans suffixe L/R). Un même code désigne deux endroits selon la plateforme — `A3` est une
       bretelle à Bron, une aire fermée à Saint-Exupéry.

PRINCIPE — on normalise pour retrouver, on conserve pour dire la vérité.

`piste` porte le désignateur ACTUEL : c'est lui qui sert à filtrer et à agréger.
`piste_saisie` porte la valeur d'origine, et `piste_renommee` dit si les deux diffèrent.
Un incident de 2010 s'est réellement produit sur « 36L » : écraser cette valeur serait réécrire
l'histoire. La réponse doit pouvoir dire « 798 incidents sur la 35L, dont 468 enregistrés sous son
ancien nom 36L avant la renumérotation d'octobre 2016 » — d'où `mention_renommage()` plus bas.

On ne DEVINE jamais : une valeur hors référentiel (`34L` à Saint-Exupéry) est signalée dans
`lieu_anomalie`, pas corrigée en douce vers la valeur la plus proche.
"""
import re
import unicodedata

# ── Aérodromes ────────────────────────────────────────────────────────────────────────
# Le LIBELLÉ est celui de la source, verbatim — Neo4j porte déjà `aerodrome` avec ces valeurs
# exactes (« Lyon Saint Exupéry », sans trait d'union). Écrire une orthographe « plus correcte »
# dans Qdrant ferait diverger les deux moteurs sur la même clé, et tout rapprochement
# Neo4j <-> Qdrant échouerait silencieusement.
# Le CODE OACI, lui, est non ambigu : c'est lui qu'on indexe et sur lequel on filtre.
AERODROMES = {
    "lyon saint exupery": ("Lyon Saint Exupéry", "LFLL"),
    "lyon saint-exupery": ("Lyon Saint Exupéry", "LFLL"),
    "lyon bron":          ("Lyon Bron", "LFLY"),
}

# Renumérotation AIRAC 1610 (octobre 2016) — Lyon Saint-Exupéry UNIQUEMENT.
RENOMMAGE_LFLL = {"18L": "17L", "18R": "17R", "36L": "35L", "36R": "35R"}
DATE_RENOMMAGE = "octobre 2016"
PISTES_LFLL = {"17L", "17R", "35L", "35R"}
PISTES_LFLY = {"16", "34"}          # piste unique 16/34 : aucun suffixe L/R n'est valide

# Lyon Saint-Exupéry a DEUX bandes, chacune désignée par ses deux seuils opposés :
#   bande A : 17R/35L — 4 000 m, décollages en priorité
#   bande B : 17L/35R — 2 670 m, atterrissages en priorité
# Le numéro d'un seuil est le cap magnétique divisé par 10 : deux seuils opposés diffèrent
# donc TOUJOURS de 18 (170° et 350°). Le suffixe L/R s'inverse quand on retourne le point de
# vue — la bande à gauche en venant du nord est à droite en venant du sud —, ce qui explique
# que le réciproque de « 17L » soit « 35R » et non « 35L ».
#
# D'où la distinction que le reste du code doit respecter :
#   « 17L/35R »  -> écart de 18  -> UNE bande, nommée par ses deux extrémités
#   « 36L/36R »  -> même numéro  -> DEUX bandes parallèles
# Le séparateur ne dit rien : les deux formes s'écrivent avec une barre oblique dans les données.
BANDES_LFLL = [{"17R", "35L"}, {"17L", "35R"}]

ZONES = {"MAN": "aire de manœuvre", "TRA": "aire de trafic", "AD": "aérodrome"}

_QFU = re.compile(r"^\s*0?(\d{2})\s*([LR])\b")
_QFU_TOUS = re.compile(r"\b0?(\d{2})\s*([LR])\b")    # tous les seuils cités dans la valeur
_QFU_NU = re.compile(r"^\s*0?(\d{2})\s*$")           # Bron : « 34 », « 16 »
# Bron, trois formes explicites SEULEMENT : la valeur entière (« 34 »), l'axe (« 16/34 »),
# ou un nombre précédé d'un mot de piste (« seuil 34 », « Piste 16 », « en finale 34 »).
_BRON_SEUIL = re.compile(r"^\s*(0?\d{2})\s*(?:/\s*(0?\d{2}))?\s*$"
                         r"|\b(?:PISTE|SEUIL|FINALE?|APPROCHE|QFU)\s*(0?\d{2})\b")
_ZONE = re.compile(r"[-\s]\s*(MAN|TRA)\b")
_POSTE = re.compile(r"^([A-Z])\s?(\d{1,3})$")


def _nz(s):
    s = unicodedata.normalize("NFD", str(s or "").strip().lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def aerodrome(valeur):
    """('Lyon Saint-Exupéry', 'LFLL') ou (None, None) si non reconnu."""
    return AERODROMES.get(_nz(valeur), (None, None))


def normaliser_lieu(precisions, nom_aerodrome):
    """Éclate `précisions sur le lieu (ECC)` en champs exploitables.

    Retourne un dict prêt à devenir un payload Qdrant / des propriétés Neo4j.
    `piste` est le désignateur ACTUEL, `piste_saisie` celui d'origine.
    """
    lib, code = aerodrome(nom_aerodrome)
    out = {"aerodrome": lib, "aerodrome_code": code,
           "piste": None, "piste_saisie": None, "piste_renommee": False,
           "piste_nb_bandes": None, "poste": None, "zone": None, "lieu_anomalie": None}

    brut = str(precisions or "").strip()
    if not brut:
        return out
    haut = brut.upper()

    z = _ZONE.search(haut)
    if z:
        out["zone"] = z.group(1)
    elif haut in ZONES:
        out["zone"] = haut

    # On collecte TOUS les désignateurs de la valeur, pas seulement celui de tête : « 17L/35R »
    # en contient deux, et n'en retenir qu'un perdait l'information.
    saisis = [f"{m.group(1).lstrip('0') or m.group(1)}{m.group(2)}"
              for m in _QFU_TOUS.finditer(haut)]
    if not saisis and code == "LFLY":
        # Bron désigne ses seuils sans suffixe : « 34 », « seuil 34 », mais aussi « 16/34 »,
        # sa bande unique nommée par ses deux extrémités — même forme d'axe qu'à Saint-Exupéry.
        # À Bron les seuils s'écrivent sans suffixe, donc un simple nombre à deux chiffres ne
        # suffit pas à en désigner un : « C/D 11 » et « 14 rue de catalogne » n'ont rien d'une
        # piste. On n'accepte que trois formes explicites.
        # findall renverrait des tuples (le motif a plusieurs groupes) : on aplatit.
        nombres = [g.lstrip("0") or g for m in _BRON_SEUIL.finditer(haut)
                   for g in m.groups() if g]
        saisis = [n for n in nombres if n in PISTES_LFLY]
        if nombres and not saisis:
            out["lieu_anomalie"] = (
                f"« {'/'.join(nombres)} » hors référentiel de Lyon Bron (piste unique 16/34)")
            return out

    if saisis:
        vus, ordre = set(), []
        for s in saisis:                       # dédoublonnage en gardant l'ordre de saisie
            if s not in vus:
                vus.add(s); ordre.append(s)
        out["piste_saisie"] = ordre

        if code == "LFLY":
            # Bron n'a qu'une bande (16/34) : un suffixe L/R y est toujours une erreur.
            nus = [s.rstrip("LR") for s in ordre]
            valides = [n for n in nus if n in PISTES_LFLY]
            if valides:
                out["piste"] = sorted(set(valides))
                out["piste_nb_bandes"] = 1     # Bron n'a qu'une bande, quoi qu'il arrive
                if any(s[-1] in "LR" for s in ordre):
                    out["lieu_anomalie"] = (
                        "suffixe L/R invalide à Lyon Bron : la plateforme n'a qu'une bande "
                        "(16/34), donc ni gauche ni droite")
            else:
                out["lieu_anomalie"] = (
                    f"« {'/'.join(ordre)} » hors référentiel de Lyon Bron (16/34)")
            return out

        actuels = [RENOMMAGE_LFLL.get(s, s) for s in ordre]
        hors = [s for s, a in zip(ordre, actuels) if a not in PISTES_LFLL]
        if hors:
            out["lieu_anomalie"] = (
                f"« {'/'.join(hors)} » hors référentiel de Lyon Saint-Exupéry "
                f"(17L/17R/35L/35R depuis {DATE_RENOMMAGE}, 18L/18R/36L/36R avant)")
            return out

        uniques = sorted(set(actuels))
        out["piste"] = uniques
        out["piste_renommee"] = any(a != s for s, a in zip(ordre, actuels))
        # LE point de la manœuvre : deux seuils opposés d'une même bande (écart de 18) ne
        # font qu'UNE piste ; deux seuils de même numéro font DEUX bandes parallèles.
        out["piste_nb_bandes"] = 1 if (len(uniques) <= 1 or set(uniques) in BANDES_LFLL) \
            else len({tuple(sorted(b)) for u in uniques for b in BANDES_LFLL if u in b})
        return out

    p = _POSTE.match(haut)
    if p and code == "LFLL":
        out["poste"] = haut
    return out


def mention_renommage(fiches, piste):
    """La phrase à afficher quand un comptage agrège les deux noms d'une même piste.

    C'est l'objet même de `piste_saisie` : sans cette mention, un total de 798 sur la 35L
    paraîtrait porter sur des fiches toutes nommées « 35L », alors que 468 d'entre elles
    disent « 36L ». Retourne None quand il n'y a rien à signaler.
    """
    anciens = {}
    for f in fiches:
        if f.get("piste_renommee") and f.get("piste_saisie"):
            anciens[f["piste_saisie"]] = anciens.get(f["piste_saisie"], 0) + 1
    if not anciens:
        return None
    detail = ", ".join(f"{n} sous « {nom} »" for nom, n in sorted(anciens.items()))
    return (f"Sur ces {len(fiches)} fiches, {sum(anciens.values())} ont été enregistrées sous "
            f"l'ancien nom de la piste ({detail}) : Lyon Saint-Exupéry a renuméroté ses pistes "
            f"en {DATE_RENOMMAGE}, et « {piste} » s'appelait alors « "
            f"{sorted(anciens)[0]} ». Il s'agit bien de la même piste physique.")


# ── Extraction depuis une QUESTION utilisateur ────────────────────────────────────────
_Q_QFU = re.compile(r"\b0?(\d{2})\s*([LR])\b")
# Deux motifs SÉPARÉS, et l'axe testé en premier. Réunis en une alternation, le moteur
# choisirait la correspondance la plus à GAUCHE : dans « piste 16/34 », « piste 16 » commence
# avant « 16/34 » et l'emporterait, ne rendant que le premier seuil.
_Q_BRON_AXE = re.compile(r"\b(16)\s*/\s*(34)\b")
_Q_BRON_SEUL = re.compile(r"\bpistes?\s+(16|34)\b", re.I)


def piste_de_question(question):
    """Les seuils de piste évoqués par une question, normalisés au nom ACTUEL.

    « incidents sur la 36L »   -> ['35L']   (l'ancien nom mène aux fiches actuelles)
    « la piste 17L/35R »       -> ['17L', '35R']   (un axe : les deux bouts d'une bande)
    « que s'est-il passé ? »   -> []

    On n'ÉLARGIT pas un seuil unique à son opposé : « la 35L » et « la 17R » sont les deux
    sens d'utilisation de la même bande, et l'utilisateur qui nomme un seuil désigne
    généralement ce sens-là. L'élargir en silence changerait sa question.
    """
    haut = str(question or "").upper()
    seuils, vus = [], set()
    for m in _Q_QFU.finditer(haut):
        s = f"{m.group(1).lstrip('0') or m.group(1)}{m.group(2)}"
        a = RENOMMAGE_LFLL.get(s, s)
        if a in PISTES_LFLL and a not in vus:
            vus.add(a); seuils.append(a)
    if not seuils:
        q = question or ""
        for m in list(_Q_BRON_AXE.finditer(q)) or list(_Q_BRON_SEUL.finditer(q)):
            for g in m.groups():
                if g and g not in vus:
                    vus.add(g); seuils.append(g)
    return seuils
