#!/usr/bin/env python3
"""Teste la voie « Cas comparables » (/synthese) sur les questions de CAUSE du golden.

CE QU'ON MESURE, ET CE QU'ON NE MESURE PAS — pas de bout en bout ici : on ne juge ni le
brouillon rédigé ni la génération. On vérifie deux choses objectives :

  1. RÉCUPÉRATION — les fiches remontées font-elles partie des fiches attendues ?
  2. EXTRACTION   — les causes affichées existent-elles VRAIMENT dans les fiches remontées,
                    au mot près ? C'est le point critique : la voie présente ces causes à un
                    responsable sécurité, qui les prendra pour argent comptant. Une cause
                    reformulée ou attribuée à la mauvaise fiche serait invisible à l'œil nu.

La vérité de l'extraction vient de Neo4j (les champs cause_* et desc_cause_*), pas du
brouillon : on compare ce que l'API affiche à ce que la base contient.
"""
import json
import re
import sys
import time
import unicodedata
import urllib.request

API = "http://172.16.6.10:8000"
GOLD = "golden_voies.jsonl"
OUT = "/home/yie0070/retex-split/retex-ingestion/resultats_causes_synthese.md"
NQ = int(sys.argv[1]) if len(sys.argv) > 1 else 999


def nz(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def post(chemin, corps, timeout=400):
    r = urllib.request.Request(API + chemin, data=json.dumps(corps).encode(),
                               headers={"Content-Type": "application/json"}, method="POST")
    t = time.time()
    return json.load(urllib.request.urlopen(r, timeout=timeout)), time.time() - t


def causes_en_base(fes):
    """{numero_fe: [causes rédigées]} — la vérité, lue dans Neo4j via l'API fiche."""
    out = {}
    for fe in fes:
        try:
            d, _ = post("/ask/incident-v2/entity", {"question": fe, "top_k": 1}, timeout=60)
        except Exception:
            continue
        out[fe] = d
    return out


def main():
    G = [json.loads(l) for l in open(GOLD, encoding="utf-8")]
    C = [g for g in G if g.get("voie") == "cause"][:NQ]
    print(f"{len(C)} questions de cause — voie « Cas comparables » (/synthese)\n", flush=True)

    lignes = []
    for i, g in enumerate(C, 1):
        attendus = set(g.get("fne_attendus") or [])
        try:
            d, dt = post("/ask/incident-v2/synthese", {"question": g["question"], "top_k": 20})
        except Exception as e:
            print(f"  [{i}/{len(C)}] {g['id']} ERREUR {type(e).__name__}", flush=True)
            continue
        prec = d.get("precedents") or []
        fes = [p.get("numero_fe") for p in prec if p.get("numero_fe")]
        bonnes = [f for f in fes if f in attendus]
        causes = [str(c) for c in (d.get("causes") or []) if str(c).strip()]
        lignes.append({
            "id": g["id"], "question": g["question"], "n_attendus": g.get("n_pertinents", 0),
            "fes": fes, "bonnes": len(bonnes), "rendues": len(fes),
            "causes": causes, "confiance": d.get("confiance"),
            "type_dominant": d.get("type_dominant"), "abstention": bool(d.get("abstention")),
            "s": round(dt, 1),
        })
        print(f"  [{i}/{len(C)}] {g['id']:9} {len(bonnes):2d}/{len(fes):2d} bonnes · "
              f"{len(causes):2d} causes · confiance={d.get('confiance')} · {dt:.0f}s", flush=True)

    json.dump(lignes, open(OUT.replace(".md", ".json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    n = len(lignes) or 1
    L = ["# Voie « Cas comparables » sur les questions de CAUSE\n",
         f"*{time.strftime('%Y-%m-%d')} · {len(lignes)} questions · endpoint réel `/synthese`. "
         "Récupération et extraction seulement — ni génération ni jugement.*\n",
         "\n| | |", "|---|---:|",
         f"| questions | {len(lignes)} |",
         f"| **succès@k** (au moins une fiche attendue) | "
         f"**{sum(1 for x in lignes if x['bonnes'])}/{len(lignes)}** |",
         f"| fiches attendues remontées, au total | {sum(x['bonnes'] for x in lignes)} |",
         f"| causes affichées, au total | {sum(len(x['causes']) for x in lignes)} |",
         f"| questions sans aucune cause | {sum(1 for x in lignes if not x['causes'])}/{len(lignes)} |",
         f"| latence moyenne | {sum(x['s'] for x in lignes)/n:.0f} s |",
         "\n## Détail\n",
         "| id | question | bonnes/rendues | causes | confiance |",
         "|---|---|---:|---:|---|"]
    for x in lignes:
        L.append(f"| {x['id']} | {x['question'][:44]} | {x['bonnes']}/{x['rendues']} "
                 f"| {len(x['causes'])} | {x['confiance']} |")
    open(OUT, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"\nécrit : {OUT}")


if __name__ == "__main__":
    main()
