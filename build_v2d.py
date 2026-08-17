#!/usr/bin/env python3
"""Construit incident_chunks_v2d — SÉPARATION STRICTE.

v2c : le chunk `fiche` contient TOUT (situation + causes + actions), et les chunks
      `cause`/`action` DUPLIQUENT cette information.
v2d : le chunk `fiche` ne contient que la SITUATION (identité + métadonnées + facteurs
      + description + analyse à chaud + vérification). Causes et actions vivent
      UNIQUEMENT dans leurs chunks dédiés.

Une seule variable change par rapport à v2c. Économie : les chunks cause/action/
narratif_long de v2c sont RECOPIÉS AVEC LEURS VECTEURS (leur texte est inchangé) ;
seuls les 9 191 chunks `fiche` sont ré-embeddés.
"""
import sys, json, time, urllib.request
sys.path.insert(0, "/home/yie0070/retex-split/retex-ingestion")

QD = "http://172.16.6.10:6333"
OL = "http://172.16.6.10:11434"
SRC_COLL, DST_COLL = "incident_chunks_v2c", "incident_chunks_v2d"
SRC = "/home/yie0070/retex-split/retex-ingestion/data/samples/incidents_avec_actions.json"
CFG = "/home/yie0070/retex-split/retex-ingestion/config/schemas/incident_securite_v2b.schema.yaml"

from extractor_incident_securite_v2 import extraire, titres_actions_du_payload, charger_schema
import document_enrichi as de
from clients import OllamaClient


def rest(path, body=None, method="POST"):
    r = urllib.request.Request(QD + path,
                               data=json.dumps(body).encode() if body is not None else None,
                               headers={"Content-Type": "application/json"}, method=method)
    return json.load(urllib.request.urlopen(r, timeout=180))


def lignes_situation(inc):
    """Narratif SANS les causes ni les actions — c'est la seule différence avec v2c."""
    lignes = []
    for prefixe, attr in (("Description", "detail"),
                          ("Analyse à chaud", "premiere_analyse_terrain"),
                          ("Vérification", "detail_verification")):
        v = de._val(getattr(inc, attr, None))
        if v:
            lignes.append(f"{prefixe} : {v}")
    return lignes


def texte_fiche(inc):
    numero = de._val(getattr(inc, "numero_fe", None))
    titre = de._val(getattr(inc, "titre", None))
    identite = f"Fiche {numero} — {titre}" if titre else f"Fiche {numero}"
    meta, fact = de._ligne_metadonnees(inc), de._ligne_facteurs(inc)
    return "\n".join([identite] + [l for l in (meta, fact) if l] + lignes_situation(inc))


def main():
    # 1. collection vierge, même config que v2c
    cfg = rest(f"/collections/{SRC_COLL}", method="GET")["result"]["config"]["params"]["vectors"]
    try:
        rest(f"/collections/{DST_COLL}", method="DELETE")
    except Exception:
        pass
    rest(f"/collections/{DST_COLL}", {"vectors": cfg}, method="PUT")
    for f in ("incident_id", "field_canonical", "source_module", "is_test_data", "numero_fe"):
        rest(f"/collections/{DST_COLL}/index?wait=true",
             {"field_name": f, "field_schema": "keyword"}, method="PUT")
    print(f"collection {DST_COLL} créée ({cfg})", flush=True)

    # 2. recopie des chunks cause/action/narratif_long AVEC leurs vecteurs (aucun GPU)
    t0, n = time.time(), 0
    nxt = None
    while True:
        b = {"limit": 512, "with_payload": True, "with_vector": True,
             "filter": {"must": [{"key": "field_canonical",
                                  "match": {"any": ["cause", "action", "narratif_long"]}}]}}
        if nxt is not None:
            b["offset"] = nxt
        r = rest(f"/collections/{SRC_COLL}/points/scroll", b)["result"]
        pts = [{"id": p["id"], "vector": p["vector"], "payload": p["payload"]} for p in r["points"]]
        if pts:
            rest(f"/collections/{DST_COLL}/points?wait=true", {"points": pts}, method="PUT")
            n += len(pts)
        nxt = r.get("next_page_offset")
        if nxt is None:
            break
    print(f"recopiés sans ré-embedding : {n} chunks cause/action/narratif ({time.time()-t0:.0f}s)", flush=True)

    # 3. ré-embedding des seuls chunks `fiche`, version SITUATION PURE
    schema = charger_schema(CFG)
    D = json.load(open(SRC, encoding="utf-8"))
    ol = OllamaClient(url=OL)
    buf, nf, t0 = [], 0, time.time()

    def flush():
        nonlocal buf
        if buf:
            rest(f"/collections/{DST_COLL}/points?wait=true", {"points": buf}, method="PUT")
            buf = []

    import uuid
    from loader_incident_securite_v2 import _QDRANT_NAMESPACE
    for i, p in enumerate(D, 1):
        inc = extraire(p, schema)
        if inc is None:
            continue
        t = texte_fiche(inc)
        if len(t) < de.PLANCHER:
            continue
        pid = str(uuid.uuid5(_QDRANT_NAMESPACE, f"{inc.incident_id}:fiche:0"))
        buf.append({"id": pid, "vector": ol.embed(t),
                    "payload": {"incident_id": inc.incident_id, "numero_fe": inc.numero_fe,
                                "source_module": inc.source_module, "field_canonical": "fiche",
                                "texte": t, "severite": inc.severite,
                                "is_test_data": inc.is_test_data}})
        nf += 1
        if len(buf) >= 256:
            flush()
        if nf % 500 == 0:
            reste = (len(D) - i) * (time.time() - t0) / nf
            print(f"   {nf} fiches ({time.time()-t0:.0f}s, reste ~{reste/60:.0f} min)", flush=True)
    flush()
    print(f"\n{nf} chunks fiche ré-embeddés en {(time.time()-t0)/60:.0f} min", flush=True)

    for f in (None, "fiche", "cause", "action", "narratif_long"):
        b = {"exact": True}
        if f:
            b["filter"] = {"must": [{"key": "field_canonical", "match": {"value": f}}]}
        c = rest(f"/collections/{DST_COLL}/points/count", b)["result"]["count"]
        print(f"   {f or 'TOTAL':14} {c}")


if __name__ == "__main__":
    main()
