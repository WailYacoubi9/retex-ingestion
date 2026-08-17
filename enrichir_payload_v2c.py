#!/usr/bin/env python3
"""Ajoute les champs structurés au payload de incident_chunks_v2c (test isolé).

AUCUN ré-embedding : on ne touche qu'au payload (set_payload). La production
(`incident_chunks`) n'est jamais modifiée.

Champs ajoutés : type_evenement · annee · lieu · piste · poste · compagnie
"""
import json, re, unicodedata, urllib.request, time
from collections import defaultdict

QD = "http://172.16.6.10:6333"
COLL = "incident_chunks_v2c"
SRC = "/home/yie0070/retex-split/retex-ingestion/data/samples/incidents_avec_actions.json"
CHAMPS = ["type_evenement", "annee", "lieu", "piste", "poste", "compagnie"]


def req(method, path, body=None):
    r = urllib.request.Request(QD + path,
                               data=json.dumps(body).encode() if body is not None else None,
                               headers={"Content-Type": "application/json"}, method=method)
    return json.load(urllib.request.urlopen(r, timeout=120))


def nz(s):
    s = "".join(c for c in unicodedata.normalize("NFD", str(s or "")) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


_PISTE = re.compile(r"\b(0?[1-9]|[12][0-9]|3[0-6])\s?([LRC])\b", re.I)
_POSTE = re.compile(r"\b([A-KM-Z])\s?(\d{1,3})\b")   # évite L seul (confusion piste)


def piste_de(r):
    for src in (r.get("précisions sur le lieu (ECC)"), r.get("titre")):
        m = _PISTE.search(nz(src).upper())
        if m:
            return f"{int(m.group(1)):02d}{m.group(2).upper()}"
    return None


def poste_de(r):
    t = nz(r.get("précisions sur le lieu (ECC)")).upper()
    if _PISTE.search(t):
        return None                       # c'est une piste, pas un poste
    m = _POSTE.search(t)
    return f"{m.group(1)}{m.group(2)}" if m else None


def main():
    D = json.load(open(SRC, encoding="utf-8"))
    meta = {}
    for r in D:
        fe = r.get("Num F.E.")
        if not fe:
            continue
        an = re.search(r"\b(19|20)\d\d\b", str(r.get("date de l'évènement (ECC)") or ""))
        meta[fe] = {
            "type_evenement": nz(r.get("type d'événement (ECC)")) or None,
            "annee": an.group(0) if an else None,
            "lieu": nz(r.get("lieu de l'évènement (ECC)")) or None,
            "piste": piste_de(r),
            "poste": poste_de(r),
            "compagnie": (nz(r.get("la compagnie (ECC)")) or "").upper() or None,
        }
    rempli = {c: sum(1 for v in meta.values() if v[c]) for c in CHAMPS}
    print("champs dérivés (sur 9 191 fiches) :")
    for c in CHAMPS:
        print(f"   {c:16} {rempli[c]:5} fiches ({rempli[c]/len(meta):5.1%})")

    # id des points par fiche
    print("\nlecture des points…", flush=True)
    par_fe = defaultdict(list)
    nxt = None
    while True:
        b = {"limit": 4000, "with_payload": ["numero_fe"], "with_vector": False}
        if nxt is not None:
            b["offset"] = nxt
        r = req("POST", f"/collections/{COLL}/points/scroll", b)["result"]
        for p in r["points"]:
            fe = (p.get("payload") or {}).get("numero_fe")
            if fe:
                par_fe[fe].append(p["id"])
        nxt = r.get("next_page_offset")
        if nxt is None:
            break
    print(f"   {sum(len(v) for v in par_fe.values())} points / {len(par_fe)} fiches")

    # regroupe les fiches partageant EXACTEMENT le même payload -> 1 appel par groupe
    groupes = defaultdict(list)
    for fe, ids in par_fe.items():
        m = meta.get(fe)
        if not m:
            continue
        cle = tuple(m[c] for c in CHAMPS)
        groupes[cle].extend(ids)
    print(f"\n{len(groupes)} combinaisons distinctes -> autant d'appels set_payload", flush=True)

    t0 = time.time()
    for i, (cle, ids) in enumerate(groupes.items(), 1):
        payload = {c: v for c, v in zip(CHAMPS, cle) if v is not None}
        if not payload:
            continue
        req("POST", f"/collections/{COLL}/points/payload?wait=false",
            {"payload": payload, "points": ids})
        if i % 500 == 0:
            print(f"   {i}/{len(groupes)}  ({time.time()-t0:.0f}s)", flush=True)
    print(f"payload écrit en {time.time()-t0:.0f}s")

    # index pour que le filtrage soit rapide
    print("\ncréation des index payload…", flush=True)
    for c in CHAMPS:
        try:
            req("PUT", f"/collections/{COLL}/index?wait=true",
                {"field_name": c, "field_schema": "keyword"})
            print(f"   index {c} OK")
        except Exception as e:
            print(f"   index {c} : {e}")

    # contrôle
    print("\ncontrôle :")
    for f, v in (("type_evenement", "Collision aviaire"), ("annee", "2010"), ("piste", "36L")):
        n = req("POST", f"/collections/{COLL}/points/count",
                {"exact": True, "filter": {"must": [{"key": f, "match": {"value": v}}]}})["result"]["count"]
        print(f"   {f}={v!r} -> {n} chunks")


if __name__ == "__main__":
    main()
