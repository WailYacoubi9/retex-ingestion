#!/usr/bin/env python3
"""
Évaluation DE BOUT EN BOUT — la réponse rédigée, pas seulement la récupération.

Trois couches de notation, du plus sûr au plus subjectif :

  1. DÉTERMINISTE (aucun LLM, aucune ambiguïté)
       citations valides   les FNE cités existent-ils dans le contexte fourni ?
       chiffres inventés   un décompte est-il avancé sans support ?
       abstention          la réponse refuse-t-elle quand elle le doit ?

  2. FAITS ATTENDUS (appariement souple)
       les faits obligatoires du golden apparaissent-ils dans la réponse ?

  3. JUGE LLM (grille binaire, un critère à la fois)
       ancrage, pertinence, absence d'invention, honnêteté sur le plafond

La couche 1 seule donne déjà un signal exploitable et ne coûte rien.

    python evaluer_e2e.py --golden golden_e2e.jsonl --api http://localhost:8000 \
                          --out e2e_baseline.json --tag baseline
    python evaluer_e2e.py --golden golden_e2e.jsonl --api ... --juge   # + couche 3
"""
from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

TIMEOUT = 240
FNE_RE = re.compile(r"FNE[\s/A-Z-]*\d{2,4}[/A-Z]*\d{3,4}", re.I)
REFUS_RE = re.compile(
    r"je ne (peux|dispose|suis pas en mesure)|pas d'information|non disponible|"
    r"non renseign|ne permet pas|aucune donnée|impossible de|n'est pas trac|"
    r"ne figure pas|pas en mesure|aucune information", re.I)
NOMBRE_RE = re.compile(r"\b(\d[\d\s\u202f]{0,9})\s*(?:fiches?|incidents?|événements?|evenements?|cas)\b", re.I)


def nz(t):
    t = "".join(c for c in unicodedata.normalize("NFD", str(t or "").lower())
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t).strip()


# ------------------------------------------------------------------ appel API

def interroger(api, question, top_k):
    t0 = time.time()
    try:
        r = requests.post(f"{api}/auto", json={"question": question, "top_k": top_k},
                          timeout=TIMEOUT)
        r.raise_for_status()
        d = r.json()
    except Exception as e:                                        # noqa: BLE001
        return {"erreur": str(e), "duree": time.time() - t0}
    diag = d.get("diagnostics") or {}
    contexte = []
    for src in (diag.get("incidents"), diag.get("rows"), diag.get("sources"), d.get("sources")):
        if isinstance(src, list):
            for it in src:
                if isinstance(it, dict):
                    v = it.get("numero_fe") or it.get("fe") or it.get("numero")
                    if v:
                        contexte.append(str(v))
                elif isinstance(it, str) and FNE_RE.match(it):
                    contexte.append(it)
    return {"answer": d.get("answer", ""), "voie": d.get("voie_choisie"),
            "contexte_fne": list(dict.fromkeys(contexte)), "brut": diag,
            "duree": time.time() - t0}


# ------------------------------------------------- couche 1 : déterministe

def couche_deterministe(q, rep):
    txt = rep.get("answer", "")
    att = q["attendu_generation"]
    ctx = {nz(x) for x in rep.get("contexte_fne", [])}
    cites = [x for x in FNE_RE.findall(txt)]
    res = {}

    # citations hors contexte = hallucination caractérisée
    hors = [c for c in cites if nz(c) not in ctx] if ctx else []
    res["citations_totales"] = len(cites)
    res["citations_hors_contexte"] = len(hors)
    res["exemples_hors_contexte"] = hors[:3]
    res["ok_citations"] = (len(hors) == 0)

    # abstention
    abstenu = bool(REFUS_RE.search(txt)) or (rep.get("voie") or "").lower() == "abstention"
    doit = att["type_reponse"] == "abstention"
    res["a_abstenu"] = abstenu
    res["ok_abstention"] = (abstenu == doit)

    # chiffres avancés comme décomptes
    chiffres = [int(re.sub(r"\D", "", m)) for m in NOMBRE_RE.findall(txt)]
    res["chiffres_annonces"] = chiffres
    if doit:
        res["ok_pas_de_chiffre"] = (len(chiffres) == 0)
    else:
        # un décompte supérieur au nombre de fiches vues est un chiffre fabriqué
        vu = len(rep.get("contexte_fne", [])) or 999
        res["ok_pas_de_chiffre"] = all(c <= max(vu, 50) for c in chiffres)

    # longueur : une réponse vide ou un pavé sont deux symptômes
    res["longueur"] = len(txt)
    res["ok_longueur"] = 80 <= len(txt) <= 4000
    return res


# ------------------------------------------------- couche 2 : faits attendus

def couche_faits(q, rep):
    txt = nz(rep.get("answer", ""))
    faits = q["attendu_generation"]["faits_obligatoires"]
    trouves, details = 0, []
    for f in faits:
        v = f["valeur"]
        if isinstance(v, list):                     # exemples de cause/action
            ok = any(_recouvrement(nz(x), txt) >= 0.35 for x in v)
        elif f["type"] == "periode":
            a, b = str(v).split("-")
            ok = a in txt or b in txt
        else:
            ok = _recouvrement(nz(str(v)), txt) >= 0.6
        trouves += ok
        details.append({"type": f["type"], "present": ok})
    return {"faits_attendus": len(faits), "faits_presents": trouves,
            "taux_faits": round(trouves / len(faits), 2) if faits else None,
            "detail": details}


def _recouvrement(besoin, texte):
    """Part des mots significatifs de `besoin` présents dans `texte`."""
    mots = [m for m in re.findall(r"[a-z0-9]{3,}", besoin)]
    if not mots:
        return 0.0
    return sum(1 for m in mots if m in texte) / len(mots)


# ------------------------------------------------- couche 3 : juge LLM

PROMPT_JUGE = """Tu évalues UNE réponse d'assistant, sur UN critère à la fois.

QUESTION POSÉE
{question}

CONTEXTE FOURNI À L'ASSISTANT (extraits des fiches)
{contexte}

RÉPONSE DE L'ASSISTANT
{reponse}

CRITÈRE À VÉRIFIER
{critere} : {verification}

Réponds UNIQUEMENT par un objet JSON :
{{"verdict": "OK" ou "KO", "justification": "une phrase courte et factuelle"}}

Sois strict : en cas de doute, KO. Ne juge QUE le critère demandé."""


def couche_juge(q, rep, ollama, modele):
    ctx = "\n".join(f"- {x}" for x in rep.get("contexte_fne", [])[:20]) or "(non disponible)"
    out = []
    for c in q["criteres_juge"]:
        p = PROMPT_JUGE.format(question=q["question"], contexte=ctx,
                               reponse=rep.get("answer", "")[:3000],
                               critere=c["critere"], verification=c["verification"])
        try:
            r = requests.post(f"{ollama}/api/generate",
                              json={"model": modele, "prompt": p, "stream": False,
                                    "options": {"temperature": 0}}, timeout=120)
            raw = r.json().get("response", "")
            m = re.search(r"\{.*\}", raw, re.S)
            d = json.loads(m.group(0)) if m else {"verdict": "KO", "justification": "illisible"}
        except Exception as e:                                    # noqa: BLE001
            d = {"verdict": "ERREUR", "justification": str(e)[:80]}
        out.append({"critere": c["critere"], **d})
    ok = sum(1 for x in out if x["verdict"] == "OK")
    return {"criteres": out, "score_juge": round(ok / len(out), 2) if out else None}


# ------------------------------------------------------------------ exécution

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", type=Path, required=True)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--tag", default="")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--juge", action="store_true", help="active la couche 3 (LLM)")
    ap.add_argument("--ollama", default="http://localhost:11434")
    ap.add_argument("--modele-juge", default="qwen2.5:14b")
    a = ap.parse_args()

    Q = [json.loads(l) for l in a.golden.read_text(encoding="utf-8").splitlines() if l.strip()]
    res, t0 = [], time.time()
    for i, q in enumerate(Q, 1):
        print(f"  [{i:2d}/{len(Q)}] {q['voie']:10s} {q['question'][:52]:54s}", end="", flush=True)
        rep = interroger(a.api, q["question"], a.top_k)
        if rep.get("erreur"):
            print(f"  ERREUR {rep['erreur'][:30]}")
            res.append({**{k: q[k] for k in ("id", "question", "voie")}, "erreur": rep["erreur"]})
            continue
        det = couche_deterministe(q, rep)
        fai = couche_faits(q, rep)
        jug = couche_juge(q, rep, a.ollama, a.modele_juge) if a.juge else None
        ligne = {**{k: q[k] for k in ("id", "question", "voie")},
                 "voie_obtenue": rep.get("voie"),
                 "deterministe": det, "faits": fai, "juge": jug,
                 "n_contexte": len(rep.get("contexte_fne", [])),
                 "duree_s": round(rep["duree"], 1),
                 "extrait": rep.get("answer", "")[:300]}
        res.append(ligne)
        flags = "".join([" " if det["ok_citations"] else "C",
                         " " if det["ok_abstention"] else "A",
                         " " if det["ok_pas_de_chiffre"] else "N"])
        print(f"  faits {fai['taux_faits']}  [{flags}]"
              + (f"  juge {jug['score_juge']}" if jug else ""))

    rap = {"tag": a.tag or a.out.stem,
           "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "api": a.api, "top_k": a.top_k, "juge_actif": a.juge,
           "duree_s": round(time.time() - t0, 1), "resultats": res}
    a.out.write_text(json.dumps(rap, ensure_ascii=False, indent=1), encoding="utf-8")

    valides = [r for r in res if "deterministe" in r]
    print("\n" + "=" * 70)
    print("COUCHE 1 — déterministe (aucune ambiguïté)")
    for lib, k in (("citations toutes valides", "ok_citations"),
                   ("abstention correcte", "ok_abstention"),
                   ("aucun chiffre fabriqué", "ok_pas_de_chiffre"),
                   ("longueur raisonnable", "ok_longueur")):
        n = sum(1 for r in valides if r["deterministe"][k])
        print(f"  {lib:28s} {n:3d}/{len(valides)}  {100*n/len(valides):5.1f}%")
    hal = sum(r["deterministe"]["citations_hors_contexte"] for r in valides)
    print(f"  {'citations hallucinées':28s} {hal:3d} au total")

    print("\nCOUCHE 2 — faits attendus")
    par = defaultdict(list)
    for r in valides:
        if r["faits"]["taux_faits"] is not None:
            par[r["voie"]].append(r["faits"]["taux_faits"])
    for v, L in par.items():
        print(f"  {v:12s} {sum(L)/len(L):.2f}  ({len(L)} questions)")

    if a.juge:
        print("\nCOUCHE 3 — juge LLM")
        crit = defaultdict(lambda: [0, 0])
        for r in valides:
            if r["juge"]:
                for c in r["juge"]["criteres"]:
                    crit[c["critere"]][1] += 1
                    crit[c["critere"]][0] += (c["verdict"] == "OK")
        for c, (ok, tot) in sorted(crit.items()):
            print(f"  {c:16s} {ok:3d}/{tot:3d}  {100*ok/tot:5.1f}%")

    print(f"\ndurée {rap['duree_s']:.0f}s  ->  {a.out}")


if __name__ == "__main__":
    main()
