#!/usr/bin/env python3
"""Teste « quelles races d'oiseaux sont les plus concernées » sur les 4 voies × 3 collections,
en utilisant la VÉRITÉ TERRAIN d'extraction des espèces (fiches_especes.json).

Deux niveaux d'évaluation :
  1. RÉCUPÉRATION : les fiches rendues portent-elles une espèce identifiée ?
  2. RÉPONSE      : la distribution des espèces dans l'échantillon rendu conduit-elle
                    à la BONNE conclusion (classement réel) ?
"""
import json, urllib.request, urllib.parse
from collections import Counter

ESP = "/home/yie0070/Téléchargements/fiches_especes.json"
OUT = "/home/yie0070/retex-split/retex-ingestion/resultats_especes_voies.md"
Q = "Quelles sont les races d'oiseaux les plus concernées par les collisions aviaires"
COLLS = [("incident_chunks", "Ancien"), ("incident_chunks_v2b", "Enrichi"), ("incident_chunks_v2c", "Hybride")]
MODES = ["dense", "recherche", "reco", "causes"]
K = 10

D = json.load(open(ESP, encoding="utf-8"))
FE2ESP = {d["numero_fe"]: d["especes"] for d in D if d.get("numero_fe")}

# Vérité terrain : distribution réelle (une fiche compte une fois par espèce citée,
# mais on retient l'espèce PRINCIPALE = la première, pour ne pas gonfler les doublons
# 'Faucon crécerelle' + 'Faucon (autre)' qui désignent le même oiseau).
vrai = Counter(e[0] for e in FE2ESP.values() if e)
TOTAL = sum(vrai.values())
CLASSEMENT = [e for e, _ in vrai.most_common()]


def api(mode):
    u = f"http://localhost:8600/api/search?q={urllib.parse.quote(Q)}&mode={mode}&k={K}"
    return json.load(urllib.request.urlopen(u, timeout=180))


def main():
    L = ["# « Quelles races d'oiseaux sont les plus concernées ? » — test sur les 4 voies\n",
         f"*Vérité terrain : extraction des espèces sur **{len(FE2ESP)} fiches** "
         f"(84 % des collisions aviaires).*\n",
         "## Vérité terrain — le classement réel\n",
         "| rang | espèce | fiches | part |", "|---:|---|---:|---:|"]
    for i, (e, n) in enumerate(vrai.most_common(9), 1):
        L.append(f"| {i} | {e} | {n} | {n/TOTAL:.1%} |")

    L.append("\n## Ce que chaque voie récupère, et ce que l'assistant conclurait\n")
    L.append("| Voie | Collection | fiches rendues | avec espèce | espèces vues | conclusion #1 | juste ? |")
    L.append("|---|---|---:|---:|---|---|:-:|")
    detail = []
    for mode in MODES:
        try:
            d = api(mode)
        except Exception as e:
            print(f"  {mode}: ERREUR {e}", flush=True)
            continue
        for coll, lab in COLLS:
            r = d.get(coll, {})
            if r.get("abstention"):
                L.append(f"| {mode} | {lab} | — | — | *abstention* | — | — |")
                continue
            fes = [x["fe"] for x in r.get("res", [])][:K]
            c = Counter()
            for fe in fes:
                sp = FE2ESP.get(fe) or []
                if sp:
                    c[sp[0]] += 1
            top = c.most_common(1)[0][0] if c else "—"
            juste = "✅" if top == CLASSEMENT[0] else "❌"
            vues = ", ".join(f"{e}×{n}" for e, n in c.most_common(3)) or "aucune"
            L.append(f"| {mode} | {lab} | {len(fes)} | {sum(c.values())} | {vues} | {top} | {juste} |")
            detail.append((mode, lab, fes, c))
            print(f"  {mode:10} {lab:8} {sum(c.values())}/{len(fes)} avec espèce · #1={top} {juste}", flush=True)

    # Le top-3 est-il jamais correct ?
    L.append("\n## Le classement (top 3) est-il retrouvé ?\n")
    L.append(f"Vrai top 3 : **{' > '.join(CLASSEMENT[:3])}**\n")
    L.append("| Voie | Collection | top 3 de l'échantillon | identique ? |")
    L.append("|---|---|---|:-:|")
    for mode, lab, fes, c in detail:
        t3 = [e for e, _ in c.most_common(3)]
        L.append(f"| {mode} | {lab} | {' > '.join(t3) if t3 else '—'} | "
                 f"{'✅' if t3 == CLASSEMENT[:3] else '❌'} |")

    L.append("\n## Lecture\n")
    L.append(f"- L'espèce n°1 (**{CLASSEMENT[0]}, {vrai[CLASSEMENT[0]]/TOTAL:.0%}**) est si dominante "
             "qu'elle ressort de presque n'importe quel échantillon : la réponse « juste » l'est "
             "**par écrasement statistique**, pas parce que le système a compté.\n")
    L.append(f"- Le **classement**, lui, demande de distinguer des espèces à 8 %, 8 % et 4 % "
             f"({', '.join(CLASSEMENT[1:4])}) : impossible sur {K} fiches tirées de "
             f"{TOTAL} — c'est une question d'**agrégation**, pas de recherche.\n")
    open(OUT, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"\nécrit : {OUT}")


if __name__ == "__main__":
    main()
