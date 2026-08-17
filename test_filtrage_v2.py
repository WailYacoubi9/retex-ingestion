#!/usr/bin/env python3
"""Gain du filtrage structuré — version NON CIRCULAIRE.

Règle : un cas n'est retenu que si le filtre est un SUR-ENSEMBLE STRICT du golden.
  - filtre == golden  -> tautologique, rejeté (toute fiche filtrée est bonne par construction)
  - golden ⊄ filtre   -> filtre incomplet, rejeté (il exclurait des fiches pertinentes)
  - golden ⊊ filtre   -> retenu : le filtre réduit l'espace, le classement doit encore trancher

On mesure ainsi ce que le classement sémantique apporte À L'INTÉRIEUR d'un espace réduit.
"""
import json, urllib.request, statistics, re, unicodedata

QD, OL, SM = "http://172.16.6.10:6333", "http://172.16.6.10:11434", "incident_securite_v2"
COLL = "incident_chunks_v2c"
OUT = "/home/yie0070/retex-split/retex-ingestion/resultats_filtrage.md"


def post(u, b):
    r = urllib.request.Request(u, data=json.dumps(b).encode(),
                               headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(r, timeout=120))


def emb(q): return post(f"{OL}/api/embed", {"model": "bge-m3", "input": q})["embeddings"][0]
def nz(s):
    s = "".join(c for c in unicodedata.normalize("NFD", str(s or "").lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def fiches_du_filtre(filt):
    out, nxt = set(), None
    while True:
        b = {"limit": 4000, "with_payload": ["numero_fe"], "with_vector": False,
             "filter": {"must": [{"key": "source_module", "match": {"value": SM}}] + filt}}
        if nxt is not None: b["offset"] = nxt
        r = post(f"{QD}/collections/{COLL}/points/scroll", b)["result"]
        for p in r["points"]: out.add((p.get("payload") or {}).get("numero_fe"))
        nxt = r.get("next_page_offset")
        if nxt is None: break
    return out


def cherche(v, k, extra=None, fetch=500):
    must = [{"key": "source_module", "match": {"value": SM}}] + (extra or [])
    r = post(f"{QD}/collections/{COLL}/points/query",
             {"query": v, "limit": fetch, "with_payload": ["numero_fe"],
              "filter": {"must": must, "must_not": [{"key": "is_test_data", "match": {"value": True}}]}})["result"]["points"]
    out, vus = [], set()
    for p in r:
        fe = (p.get("payload") or {}).get("numero_fe")
        if fe and fe not in vus:
            vus.add(fe); out.append(fe)
        if len(out) >= k: break
    return out


# filtres candidats, déduits du LIBELLÉ de la question (ce qu'un routeur pourrait extraire)
def candidats(q):
    n = nz(q); c = []
    for a in re.findall(r"\b(20[0-2][0-9])\b", n):
        c.append(("annee=" + a, [{"key": "annee", "match": {"value": a}}]))
    if "2024 ou 2025" in n:
        c.append(("annee∈{2024,2025}", [{"key": "annee", "match": {"any": ["2024", "2025"]}}]))
    for mot, val in (("collision aviaire", "Collision aviaire"), ("fod", "FOD"),
                     ("sslia", "Dysfonctionnement du SSLIA"),
                     ("incendie", "Dysfonctionnement du SSLIA"),
                     ("quasi-collision", "Quasi-collision impliquant un aéronef avec un véhicule ou un piéton"),
                     ("avitaillement", "Problème avitaillement"),
                     ("balisage", "Défaillance du balisage ou de l'éclairage"),
                     ("repoussage", "Repoussage ou tractage non conformes")):
        if mot in n:
            c.append((f"type={val[:22]}", [{"key": "type_evenement", "match": {"value": val}}]))
    m = re.search(r"poste ([a-z])\s?(\d{1,3})", n)
    if m: c.append((f"poste={m.group(1).upper()}{m.group(2)}",
                    [{"key": "poste", "match": {"value": f"{m.group(1).upper()}{m.group(2)}"}}]))
    return c


def main():
    G = [json.loads(l) for l in open("/home/yie0070/retex-split/retex-ingestion/golden_voies.jsonl", encoding="utf-8")]
    tot = post(f"{QD}/collections/{COLL}/points/count", {"exact": True})["result"]["count"]
    retenus, rejets = [], []
    for g in G:
        rel = set(g["fne_attendus"])
        for nom, filt in candidats(g["question"]):
            F = fiches_du_filtre(filt)
            if F == rel:
                rejets.append((g["question"], nom, "TAUTOLOGIQUE — filtre == golden")); continue
            if not rel <= F:
                rejets.append((g["question"], nom, f"incomplet — {len(rel-F)} pertinentes exclues")); continue
            retenus.append((g, nom, filt, len(F)))
            break                      # un filtre valide par question suffit
    print(f"{len(retenus)} cas valides · {len(rejets)} rejetés\n")

    L = ["# Filtrage structuré avant classement — mesure du gain\n",
         "*Filtre payload exact **puis** classement dense, comparé au dense seul sur tout le corpus.*\n",
         "## Protocole — comment la circularité est évitée\n",
         "Un cas n'est retenu que si le filtre est un **sur-ensemble strict** de la vérité terrain :\n",
         "- filtre **==** golden → **rejeté** (tautologique : toute fiche filtrée est bonne par construction) ;\n",
         "- golden **⊄** filtre → **rejeté** (le filtre exclurait des fiches pertinentes) ;\n",
         "- golden **⊊** filtre → **retenu** : le filtre réduit l'espace, le classement sémantique doit encore trancher dedans.\n",
         f"\n**{len(retenus)} cas retenus · {len(rejets)} rejetés.**\n",
         "\n| Question | filtre | espace | ×golden | préc@10 sans | **avec** | Δ |",
         "|---|---|---:|---:|---:|---:|---:|"]
    a_l, b_l = [], []
    for g, nom, filt, nf in retenus:
        rel, k = set(g["fne_attendus"]), g["k"]
        v = emb(g["question"])
        a = len([f for f in cherche(v, k) if f in rel]) / k
        b = len([f for f in cherche(v, k, filt) if f in rel]) / k
        a_l.append(a); b_l.append(b)
        L.append(f"| {g['question'][:46]} | `{nom}` | {nf} | ×{nf/g['n_pertinents']:.0f} | "
                 f"{a:.0%} | **{b:.0%}** | {b-a:+.0%} |")
        print(f"  {g['question'][:46]:46} {nom:24} {a:.0%} -> {b:.0%}  ({b-a:+.0%})", flush=True)
    m = statistics.mean
    L.append(f"| **MOYENNE** ({len(retenus)} cas) | | | | **{m(a_l):.0%}** | **{m(b_l):.0%}** | **{m(b_l)-m(a_l):+.0%}** |")
    L.append("\n## Cas rejetés (et pourquoi)\n")
    L.append("| Question | filtre | motif |"); L.append("|---|---|---|")
    for q, nom, why in rejets[:12]:
        L.append(f"| {q[:44]} | `{nom}` | {why} |")
    L.append("\n## Portée réelle\n")
    L.append("Sur **269 questions distinctes réellement posées** par les utilisateurs du pilote "
             "(`interactions.jsonl`, 1 065 requêtes), **82 (30 %)** portent une contrainte "
             "structurée extractible :\n")
    L.append("| contrainte | questions | part |"); L.append("|---|---:|---:|")
    for k_, v_, p_ in (("type d'événement", 39, "14,5 %"), ("année", 32, "11,9 %"), ("lieu", 18, "6,7 %"),
                       ("compagnie", 8, "3,0 %"), ("piste", 4, "1,5 %"), ("poste", 2, "0,7 %")):
        L.append(f"| {k_} | {v_} | {p_} |")
    L.append("\nLe gain ne s'applique donc qu'à **environ un tiers** des questions réelles — "
             "une minorité substantielle, ni un cas particulier ni la majorité.\n")
    L.append("\n## Réserves\n")
    L.append("1. **Le filtre est fourni ici**, déduit du libellé. On mesure le **plafond** : "
             "ce qu'on obtiendrait si le routeur extrayait correctement la contrainte.\n")
    L.append("2. **Le risque est asymétrique.** Un filtre mal extrait est pire que pas de filtre : "
             "filtrer sur 2024 quand l'utilisateur demandait 2025 garantit **zéro** bonne réponse. "
             "L'extraction devra être mesurée séparément, et l'abstention préférée au filtre douteux.\n")
    L.append("3. **Petit échantillon** — le nombre de cas non circulaires reste faible.\n")
    L.append("\n## Ce que le mécanisme explique\n")
    L.append("Les **207 fiches au titre identique « collision aviaire »** produisent des vecteurs "
             "identiques (cosinus 1,000) et donc un ordre **arbitraire**. Le filtrage ne corrige pas "
             "ce défaut — il le rend **inoffensif** : dans un sous-ensemble de quelques dizaines de "
             "fiches déjà toutes conformes à la contrainte, l'ordre entre elles ne coûte plus rien.\n")
    open(OUT, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"\nMOYENNE ({len(retenus)} cas non circulaires) : {m(a_l):.0%} -> {m(b_l):.0%}  ({m(b_l)-m(a_l):+.0%})")
    print(f"écrit : {OUT}")


if __name__ == "__main__":
    main()
