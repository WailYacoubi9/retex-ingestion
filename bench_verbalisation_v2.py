#!/usr/bin/env python3
"""
Banc v2 — décide À LA FOIS la structure du chunk et son contenu.

Ce que le banc v1 n'avait pas mesuré : le passage per-champ -> fusionné.
C'est pourtant de là que vient l'essentiel du gain attendu de D1 (fin des
titres jumeaux, doublons 29,7 % -> 0 %). Le bras A0 comble ce trou.

    pip install requests numpy
    python bench_verbalisation_v2.py --input incidents_avec_actions.json

Cinq variantes :
    A0  chunks PAR CHAMP, comme l'ingestion actuelle (min_length en caractères),
        rappel calculé au niveau FICHE après déduplication      <- l'état actuel
    A   narratif fusionné, un seul vecteur par fiche             <- effet FUSION
    B   A + métadonnées ÉTIQUETÉES  ("Type: Collision aviaire")
    C   A + métadonnées SANS étiquettes ("Collision aviaire")
    D   A + métadonnées SANS étiquettes, filtrées par ENTROPIE   <- coupe principielle

Trois mesures, avec leur fiabilité :
    rappel@10       ~45 requêtes  -> IC 95 % par bootstrap
    séparation      ~45 requêtes  -> IC 95 % par bootstrap
    homogénéisation 5 000 paires  -> mesure solide, c'est elle qui tranche B vs C

Décision : le rappel choisit le NIVEAU, l'homogénéisation départage à rappel égal.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pickle
import random
import re
import sys
from collections import Counter, defaultdict

import numpy as np
import requests

SEED = 20260804
random.seed(SEED)

OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("EMBED_MODEL", "bge-m3")
CACHE = "bench_embeddings_v2.pkl"

_cache: dict[str, list[float]] = {}


def embed(text: str) -> np.ndarray:
    if text in _cache:
        return np.array(_cache[text], dtype=np.float32)
    for path, key in (("/api/embeddings", "prompt"), ("/api/embed", "input")):
        try:
            r = requests.post(f"{OLLAMA}{path}", json={"model": MODEL, key: text}, timeout=180)
            if r.status_code != 200:
                continue
            d = r.json()
            v = d.get("embedding") or (d.get("embeddings") or [None])[0]
            if v:
                _cache[text] = v
                return np.array(v, dtype=np.float32)
        except requests.RequestException:
            continue
    sys.exit(f"[!] Embedding impossible sur {OLLAMA} (modèle « {MODEL} »).")


def clean(v):
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s if s and s.lower() not in {"0", "-", "n/a", "na", "ras", "nil"} else None


# ----------------------------------------------------------------- métadonnées

META = [
    ("Type", "type d'événement (ECC)"),
    ("Précision", "Type d'événement (autre)"),
    ("Lieu", "lieu de l'évènement (ECC)"),
    ("Point", "précisions sur le lieu (ECC)"),
    ("Date", "date de l'évènement (ECC)"),
    ("Gravité", "classification des risques (ECC)"),
    ("Classification", "classification événement (ECC)"),
    ("Phase", "phase de vol (ECC)"),
    ("Compagnie", "la compagnie (ECC)"),
    ("Aéronef", "type d'aéronef (ECC)"),
    ("Unité", "Unité d'application *"),
    ("Notifiant", "Notifiant"),
    ("Conditions", "Lors de l'évènement, il faisait"),
    ("Aérodrome", "nom de l'aérodrome (ECC)"),
]
AXES_6M = [("Main d'œuvre", "Main d’œuvre"), ("Méthodes", "Méthodes"),
           ("Machines", "Machines (équipement)"), ("Matières", "Matières premières"),
           ("Milieu", "Milieu"), ("Management", "Management")]
CAUSES = [("Main d'œuvre", "desc cause 1"), ("Méthodes", "desc cause 2"),
          ("Machines", "desc cause 3"), ("Matières", "desc cause 4"),
          ("Milieu", "desc cause 5"), ("Management", "desc cause 6")]


def entropies(D, seuil=0.5):
    """H normalisée de chaque métadonnée, sur TOUT le corpus. Sélectionne H > seuil."""
    keep, table = [], []
    for lib, k in META:
        vals = []
        for r in D:
            v = clean(r.get(k))
            if v:
                vals += [x.strip() for x in v.split("|") if x.strip()]
        if not vals:
            table.append((lib, 0, 0.0))
            continue
        c = Counter(vals)
        tot = sum(c.values())
        H = -sum((n / tot) * math.log(n / tot) for n in c.values())
        Hn = H / math.log(len(c)) if len(c) > 1 else 0.0
        table.append((lib, len(c), Hn))
        if Hn > seuil:
            keep.append((lib, k))
    return keep, table


# -------------------------------------------------------------------- variantes

def narratif(r) -> str:
    p = []
    t = clean(r.get("titre"))
    if t:
        p.append(t)
    for pre, k in (("", "Description de l'événement et de son contexte"),
                   ("Analyse : ", "Analyse à chaud"),
                   ("Action immédiate : ", "Action corrective immédiate"),
                   ("Vérification : ", "détail de la vérification")):
        v = clean(r.get(k))
        if v:
            p.append(pre + v)
    cz = [f"{lib} — {clean(r.get(k))}" for lib, k in CAUSES if clean(r.get(k))]
    if cz:
        p.append("Causes : " + " ; ".join(cz))
    acts = [clean(a.get("titre de l'action"))
            for key in ("actions_correctives", "actions_preventives", "actions_curatives")
            for a in (r.get(key) or []) if clean(a.get("titre de l'action"))]
    if acts:
        p.append("Actions : " + " ; ".join(acts))
    return "\n".join(p)


def meta_parts(r, champs) -> list[tuple[str, str]]:
    out = [(lib, clean(r.get(k))) for lib, k in champs if clean(r.get(k))]
    ax = [lib for lib, k in AXES_6M if clean(r.get(k))]
    if ax:
        out.append(("Facteurs", ", ".join(ax)))
    return out


# --- A0 : reproduction EXACTE du découpage actuel (models_incident_securite_v2)
CHAMPS_A0 = [("titre", "titre", 5),
             ("detail", "Description de l'événement et de son contexte", 20),
             ("action_corrective", "Action corrective immédiate", 20),
             ("analyse_chaud", "Analyse à chaud", 20),
             ("detail_verification", "détail de la vérification", 20),
             ("desc_cause_1", "desc cause 1", 15),
             ("desc_cause_3", "desc cause 3", 15),
             ("desc_cause_5", "desc cause 5", 15)]
VIDES = {"", "0", "non", "n/a", "na", "néant", "neant", "false", "sans objet", "ras"}


def chunks_a0(r) -> list[str]:
    out = []
    for canon, lab, ml in CHAMPS_A0:
        raw = r.get(lab)
        if canon in ("action_corrective", "analyse_chaud", "detail_verification"):
            if (str(raw).strip().lower() if raw is not None else "") in VIDES:
                continue
        v = clean(raw)
        if v and len(v) >= ml:          # min_length en CARACTÈRES, comme en prod
            out.append(v)
    return out


def texte(r, var, champs_d):
    n = narratif(r)
    if var == "A":
        return n
    m = meta_parts(r, META if var in ("B", "C") else champs_d)
    if var == "B":
        return (" | ".join(f"{lib}: {v}" for lib, v in m) + "\n" + n).strip()
    return (" | ".join(v for _, v in m) + "\n" + n).strip()


# --------------------------------------------------------------------- requêtes

CIBLES = {
    "FOD": ["débris trouvé sur la piste", "objet étranger sur l'aire de trafic",
            "morceau de métal ramassé sur le taxiway", "présence de FOD au parking",
            "boulon retrouvé au sol", "corps étranger sur l'aire"],
    "Collision aviaire": ["choc avec un oiseau au décollage", "impact aviaire sur un appareil",
                          "un volatile a été percuté", "trace de sang sur le fuselage après impact",
                          "péril animalier lors de l'atterrissage", "birdstrike signalé par l'équipage"],
    "Quasi-collision impliquant un aéronef avec un véhicule ou un piéton": [
        "un véhicule est passé trop près d'un avion", "risque de collision engin-aéronef",
        "un agent a traversé devant un appareil en roulage",
        "distance de sécurité non respectée entre un engin et un avion",
        "véhicule coupant la trajectoire d'un aéronef"],
    "Mauvaise utilisation des matériels de piste (stationnement)": [
        "engin de piste mal stationné", "matériel positionné de façon non conforme",
        "GSE laissé hors de sa zone", "équipement stationné dans la zone d'évolution",
        "matériel non rangé après opération"],
    "Dysfonctionnement du SSLIA": ["panne d'un véhicule du service incendie",
                                   "problème sur les moyens de secours",
                                   "baisse du niveau de protection incendie",
                                   "indisponibilité d'un engin des pompiers"],
    "Présence indésirable sur une aire": ["personne non autorisée sur l'aire",
                                          "animal présent sur l'aire de manœuvre",
                                          "intrusion dans une zone réservée",
                                          "piéton non habilité côté piste"],
    "Problème avitaillement": ["fuite de carburant pendant l'avitaillement",
                               "incident lors du remplissage en kérosène",
                               "débordement de carburant au sol",
                               "camion avitailleur mal positionné"],
    "Défaillance du balisage ou de l'éclairage": ["feux de piste hors service",
                                                  "défaut d'éclairage sur l'aire",
                                                  "balisage lumineux défaillant de nuit",
                                                  "panne des feux d'axe"],
    "Repoussage ou tractage non conformes": ["repoussage effectué sans autorisation",
                                             "tractage non conforme d'un appareil",
                                             "push-back mal exécuté"],
    "Collision animale": ["choc avec un animal au sol", "lièvre percuté sur la piste"],
}


def echantillon(D, par_type, distracteurs):
    par = defaultdict(list)
    for i, r in enumerate(D):
        t = (clean(r.get("type d'événement (ECC)")) or "").split("|")[0].strip()
        if narratif(r):
            par[t].append(i)
    idx, cible = [], {}
    for t in CIBLES:
        pool = par.get(t, [])
        if len(pool) < 5:
            print(f"[!] type « {t[:45]} » trop rare ({len(pool)}), ignoré")
            continue
        s = random.sample(pool, min(par_type, len(pool)))
        cible[t] = set(s)
        idx += s
    autres = [i for t, v in par.items() if t not in CIBLES for i in v]
    idx += random.sample(autres, min(distracteurs, len(autres)))
    return sorted(set(idx)), cible


# --------------------------------------------------------------------- mesures

def boot(vals, n=4000):
    """IC 95 % par bootstrap — pour ne plus arbitrer 0,5 pt à l'œil."""
    a = np.array(vals, dtype=float)
    m = np.array([np.mean(np.random.choice(a, len(a), replace=True)) for _ in range(n)])
    return float(a.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def boot_apparie(x, y, n=4000):
    """IC 95 % de la différence x-y APPARIÉE (mêmes requêtes) — bien plus puissant
    que comparer deux IC indépendants, qui conclut « équivalent » à tort."""
    d = np.array(x, dtype=float) - np.array(y, dtype=float)
    m = np.array([np.mean(np.random.choice(d, len(d), replace=True)) for _ in range(n)])
    return float(d.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def mesure_fusion(idx, cible, vecs, k=10):
    """Variantes A/B/C/D : un vecteur par fiche."""
    pos = {i: n for n, i in enumerate(idx)}
    M = np.stack([vecs[i] for i in idx])
    M /= np.linalg.norm(M, axis=1, keepdims=True) + 1e-12
    rap, sep = [], []
    for t, paras in CIBLES.items():
        if t not in cible:
            continue
        tgt = {pos[i] for i in cible[t]}
        hors = [j for j in range(len(idx)) if j not in tgt]
        for p in paras:
            q = embed(p)
            q /= np.linalg.norm(q) + 1e-12
            s = M @ q
            top = np.argsort(-s)[:k]
            rap.append(len(set(top.tolist()) & tgt) / min(k, len(tgt)))
            sep.append(float(np.mean(s[list(tgt)])) - float(np.mean(s[hors])))
    return rap, sep, homogeneite(M)


def mesure_a0(idx, cible, vecs_ch, k=10):
    """A0 : plusieurs chunks par fiche, score fiche = MAX de ses chunks (dédup)."""
    flat, owner = [], []
    for i in idx:
        for v in vecs_ch[i]:
            flat.append(v)
            owner.append(i)
    M = np.stack(flat)
    M /= np.linalg.norm(M, axis=1, keepdims=True) + 1e-12
    owner = np.array(owner)
    rap, sep = [], []
    for t, paras in CIBLES.items():
        if t not in cible:
            continue
        tgt = cible[t]
        for p in paras:
            q = embed(p)
            q /= np.linalg.norm(q) + 1e-12
            s = M @ q
            best: dict[int, float] = {}
            for j, sc in enumerate(s):          # dédup au niveau fiche
                f = int(owner[j])
                if sc > best.get(f, -2):
                    best[f] = float(sc)
                    
            ordre = sorted(best, key=lambda f: -best[f])
            rap.append(len(set(ordre[:k]) & tgt) / min(k, len(tgt)))
            dedans = [best[f] for f in best if f in tgt]
            dehors = [best[f] for f in best if f not in tgt]
            sep.append(float(np.mean(dedans)) - float(np.mean(dehors)))
    return rap, sep, homogeneite(M)


def homogeneite(M, n=5000):
    a = np.random.randint(0, len(M), n)
    b = np.random.randint(0, len(M), n)
    m = a != b
    return float(np.mean(np.sum(M[a[m]] * M[b[m]], axis=1)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--par-type", type=int, default=35)
    ap.add_argument("--distracteurs", type=int, default=150)
    ap.add_argument("--seuil-entropie", type=float, default=0.5)
    ap.add_argument("--out", default="bench_resultats.json")
    a = ap.parse_args()

    if os.path.exists(CACHE):
        _cache.update(pickle.load(open(CACHE, "rb")))
        print(f"[cache] {len(_cache)} embeddings rechargés")

    D = json.load(open(a.input, encoding="utf-8"))
    champs_d, table = entropies(D, a.seuil_entropie)

    print(f"\n=== Entropie des métadonnées (seuil variante D : H > {a.seuil_entropie}) ===")
    for lib, card, Hn in sorted(table, key=lambda x: -x[2]):
        print(f"  {lib:16s} card={card:5d}  H={Hn:.2f}  {'RETENU' if Hn > a.seuil_entropie else '—'}")
    print(f"  -> variante D : {len(champs_d)} métadonnées sur {len(META)}\n")

    idx, cible = echantillon(D, a.par_type, a.distracteurs)
    nq = sum(len(v) for t, v in CIBLES.items() if t in cible)
    print(f"échantillon : {len(idx)} fiches | {len(cible)} types | "
          f"{sum(len(v) for v in cible.values())} pertinentes | {nq} requêtes\n")

    res = {}

    vch = {}
    tot = 0
    for i in idx:
        vch[i] = [embed(c) for c in chunks_a0(D[i])] or [embed(narratif(D[i]))]
        tot += len(vch[i])
    print(f"  [A0] {tot} chunks pour {len(idx)} fiches ({tot/len(idx):.2f}/fiche)")
    res["A0"] = mesure_a0(idx, cible, vch)
    pickle.dump(_cache, open(CACHE, "wb"))

    for var in ("A", "B", "C", "D"):
        vecs = {}
        for n, i in enumerate(idx, 1):
            vecs[i] = embed(texte(D[i], var, champs_d))
            if n % 60 == 0:
                print(f"  [{var}] {n}/{len(idx)}", end="\r")
        res[var] = mesure_fusion(idx, cible, vecs)
        pickle.dump(_cache, open(CACHE, "wb"))
        print(f"  [{var}] terminé            ")

    LIB = {"A0": "A0 · chunks par champ (ACTUEL)", "A": "A  · narratif fusionné",
           "B": "B  · + métadonnées étiquetées", "C": "C  · + métadonnées sans étiquettes",
           "D": f"D  · + métadonnées H>{a.seuil_entropie} ({len(champs_d)})"}
    print("\n" + "=" * 84)
    print(f"{'variante':34s} {'rappel@10 [IC95]':>26s} {'séparation':>12s} {'homogén.':>9s}")
    print("-" * 84)
    out = {}
    for v in ("A0", "A", "B", "C", "D"):
        rap, sep, homo = res[v]
        rm, rlo, rhi = boot(rap)
        sm, _, _ = boot(sep)
        print(f"{LIB[v]:34s} {100*rm:8.1f}% [{100*rlo:5.1f};{100*rhi:5.1f}] "
              f"{sm:12.3f} {homo:9.3f}")
        out[v] = {"rappel": 100 * rm, "ic95": [100 * rlo, 100 * rhi],
                  "separation": sm, "homogeneite": homo}
    print("=" * 84)

    rA0, rA, rC = out["A0"]["rappel"], out["A"]["rappel"], out["C"]["rappel"]
    print("\n--- DÉCOMPOSITION DU GAIN ---")
    print(f"  effet FUSION      (A0 -> A) : {rA - rA0:+6.1f} pt   "
          f"[non mesuré dans le banc v1]")
    print(f"  effet MÉTADONNÉES (A  -> C) : {rC - rA:+6.1f} pt")
    print(f"  TOTAL             (A0 -> C) : {rC - rA0:+6.1f} pt")

    print("\n--- DÉCISION (test apparié, mêmes requêtes) ---")
    raps = {v: res[v][0] for v in ("A", "B", "C", "D")}
    best = max(raps, key=lambda v: np.mean(raps[v]))
    equiv = [best]
    for v in raps:
        if v == best:
            continue
        d, lo, hi = boot_apparie(raps[best], raps[v])
        verdict = "équivalent" if lo <= 0 <= hi else "INFÉRIEUR"
        print(f"  {best} − {v} : {100*d:+5.1f} pt  IC95 [{100*lo:+5.1f};{100*hi:+5.1f}]  {verdict}")
        if lo <= 0 <= hi:
            equiv.append(v)
    choix = min(equiv, key=lambda v: out[v]["homogeneite"])
    print(f"\n  meilleur rappel : {best} ({out[best]['rappel']:.1f} %)")
    print(f"  équivalents     : {', '.join(sorted(equiv))}")
    print(f"  -> RETENU : {choix}  (homogénéisation la plus basse parmi les équivalents : "
          f"{out[choix]['homogeneite']:.3f})")
    dF, loF, hiF = boot_apparie(res["A"][0], res["A0"][0])
    print(f"\n  effet FUSION apparié (A − A0) : {100*dF:+5.1f} pt "
          f"IC95 [{100*loF:+5.1f};{100*hiF:+5.1f}]"
          f"{'  -> significatif' if loF > 0 else '  -> NON significatif sur le rappel'}")
    if loF <= 0:
        print("     (la fusion reste justifiée par la fin des doublons et le pré-filtrage,")
        print("      qui ne se mesurent pas sur le rappel de ce banc)")

    json.dump({"seed": SEED, "modele": MODEL, "n_fiches": len(idx), "n_requetes": nq,
               "seuil_entropie": a.seuil_entropie,
               "metadonnees_D": [l for l, _ in champs_d],
               "resultats": out, "choix": choix},
              open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nrésultats -> {a.out}")


if __name__ == "__main__":
    main()