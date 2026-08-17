#!/usr/bin/env python3
"""Écrit les champs de lieu normalisés dans les payloads v2b et v2c.

AUCUN ré-embedding : uniquement `set_payload`, qui est additif. Les vecteurs ne sont pas
touchés, aucune collection n'est recréée — c'est ce qui rend l'opération sûre (la création
de collection est ce qui avait fait sauter la limite de descripteurs de Qdrant).

La collection de PRODUCTION `incident_chunks` n'est jamais modifiée.

Champs écrits (cf. normalisation_lieu.py, défauts D19/D20/D21) :
  aerodrome · aerodrome_code · piste · piste_saisie · piste_renommee · poste · zone · lieu_anomalie

`piste` porte le désignateur ACTUEL (35L), `piste_saisie` la valeur d'origine (36L) : c'est ce
couple qui permet de compter juste ET de dire à l'utilisateur que 468 des 798 fiches de la 35L
ont été saisies sous son ancien nom.

  --dry-run   n'écrit rien, affiche ce qui serait fait
"""
import json
import sys
import time
import urllib.request
from collections import defaultdict

sys.path.insert(0, "/home/yie0070/retex-split/retex-ingestion")
from normalisation_lieu import normaliser_lieu  # noqa: E402

QD = "http://172.16.6.10:6333"
COLLECTIONS = ["incident_chunks_v2b", "incident_chunks_v2c"]
PRODUCTION = "incident_chunks"          # jamais ciblée — garde-fou explicite
SRC = "/home/yie0070/retex-split/retex-ingestion/data/samples/incidents_avec_actions.json"
CHAMP_AD = "nom de l'aérodrome (ECC)"
CHAMP_LIEU = "précisions sur le lieu (ECC)"

# Indexés : ceux sur lesquels on filtrera. `piste_saisie` et `lieu_anomalie` sont des champs
# de TRACE, lus mais jamais filtrés — les indexer coûterait sans rien rapporter.
A_INDEXER = ["aerodrome", "aerodrome_code", "piste", "poste", "zone"]


def req(method, path, body=None, timeout=180):
    r = urllib.request.Request(
        QD + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"}, method=method)
    return json.load(urllib.request.urlopen(r, timeout=timeout))


def champs_par_fiche():
    """{numero_fe: {champ: valeur}} — seuls les champs non vides sont écrits."""
    out = {}
    for r in json.load(open(SRC, encoding="utf-8")):
        fe = str(r.get("Num F.E.") or "").strip()
        if not fe:
            continue
        n = normaliser_lieu(r.get(CHAMP_LIEU), r.get(CHAMP_AD))
        n.pop("piste_renommee") if n.get("piste_renommee") is False else None
        out[fe] = {k: v for k, v in n.items() if v not in (None, "", False)}
    return out


def main():
    sec = "--dry-run" in sys.argv
    par_fiche = champs_par_fiche()

    # On regroupe les fiches partageant exactement le même jeu de valeurs : un set_payload
    # par groupe au lieu d'un par fiche (9 191 appels -> quelques milliers).
    groupes = defaultdict(list)
    for fe, ch in par_fiche.items():
        if ch:
            groupes[json.dumps(ch, sort_keys=True, ensure_ascii=False)].append(fe)

    # Pour chaque clé gérée, les fiches qui ne doivent PAS la porter.
    gerees = ["aerodrome", "aerodrome_code", "piste", "piste_saisie", "piste_renommee",
              "piste_nb_bandes", "poste", "zone", "lieu_anomalie"]
    absents = {c: [fe for fe, ch in par_fiche.items() if c not in ch] for c in gerees}

    print(f"{len(par_fiche)} fiches · {len(groupes)} combinaisons distinctes")
    stats = defaultdict(int)
    for ch in par_fiche.values():
        for k in ch:
            stats[k] += 1
    for k in sorted(stats):
        print(f"  {k:16} {stats[k]:5d} fiches")

    if sec:
        print("\n--dry-run : rien n'a été écrit.")
        ex = sorted(groupes.items(), key=lambda x: -len(x[1]))[:3]
        for payload, fes in ex:
            print(f"  {len(fes):5d} fiches <- {payload[:110]}")
        return

    for coll in COLLECTIONS:
        assert coll != PRODUCTION, "refus d'écrire dans la collection de production"
        t0 = time.time()
        print(f"\n=== {coll} ===", flush=True)
        for i, (payload, fes) in enumerate(groupes.items(), 1):
            req("POST", f"/collections/{coll}/points/payload?wait=false",
                {"payload": json.loads(payload),
                 "filter": {"must": [{"key": "numero_fe", "match": {"any": fes}}]}})
            if i % 500 == 0:
                print(f"  {i}/{len(groupes)} groupes · {time.time()-t0:.0f}s", flush=True)
        print(f"  {len(groupes)} groupes écrits en {time.time()-t0:.0f}s", flush=True)

        # set_payload n'efface rien : sans ce passage, une fiche qui PERD une clé (piste
        # devenue chaîne -> liste, ou retirée parce qu'anomalie) garderait indéfiniment son
        # ancienne valeur, et les comptages mélangeraient deux générations de données.
        for champ, fes in absents.items():
            if not fes:
                continue
            req("POST", f"/collections/{coll}/points/payload/delete?wait=false",
                {"keys": [champ],
                 "filter": {"must": [{"key": "numero_fe", "match": {"any": fes}}]}})
            print(f"  purge {champ} sur {len(fes)} fiches")

        for champ in A_INDEXER:
            try:
                # PUT, pas POST : l'endpoint d'index renvoie 404 en POST.
                req("PUT", f"/collections/{coll}/index?wait=true",
                    {"field_name": champ, "field_schema": "keyword"})
                print(f"  index {champ} OK")
            except Exception as e:
                print(f"  index {champ} : {str(e)[:70]}")

    print("\n=== vérification ===")
    for coll in COLLECTIONS:
        for f, v in (("aerodrome_code", "LFLL"), ("aerodrome_code", "LFLY"),
                     ("aerodrome", "Lyon Saint Exupéry"), ("aerodrome", "Lyon Bron"),
                     ("aerodrome", "Lyon Saint-Exupéry"),   # doit valoir 0 : orthographe abandonnée
                     ("piste", "35L"), ("piste", "17R")):
            n = req("POST", f"/collections/{coll}/points/count",
                    {"filter": {"must": [{"key": f, "match": {"value": v}}]}, "exact": True})
            print(f"  {coll:24} {f}={v:20} -> {n['result']['count']} chunks")


if __name__ == "__main__":
    main()
