"""
Profilage des données incident_securite_v2.
Livrables :
  reports/profil_incident_v2.md         — rapport statistique complet
  reports/echantillon_anonymise_incident_v2.json — 6-8 fiches anonymisées
Usage : python scripts/profile_incident_v2.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import fields
from datetime import date, datetime, time
from pathlib import Path
from statistics import mean, median

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, QDRANT_URL
from clients import Neo4jClient
from extractor_incident_securite_v2 import charger_schema, extraire, verifier_coherence
from models_incident_securite_v2 import IncidentSecuriteV2Canonique

DEFAULT_INPUT = PROJECT_ROOT / "data" / "samples" / "incidents_securites.json"
DEFAULT_SCHEMA = PROJECT_ROOT / "config" / "schemas" / "incident_securite_v2.schema.yaml"
REPORTS_DIR = PROJECT_ROOT / "reports"

VALEURS_TRIVIALES = {"", "0", "-", "non", "n/a", "na", "néant", "neant",
                     "ras", "sans objet", "non applicable", "false", "null"}

CHAMPS_CATEGORIELS = [
    "etat", "etape", "statut_ecc", "severite", "classification",
    "processus", "condition_lumineuse", "type_fiche", "aerodrome",
    "organisations_informees", "categorie_id",
]
CHAMPS_TEXTUELS = [
    "titre", "detail", "action_corrective", "analyse_chaud",
    "desc_cause_1", "desc_cause_3", "desc_cause_5", "detail_verification",
    "resume_llm",
]
CHAMPS_DATES = ["date_creation", "date_evenement", "date_maj"]
CHAMPS_BOOLEENS = [
    "presence_blesses", "analyse_causes_faite", "traitement_termine",
    "est_significatif", "est_rex", "actions_efficaces",
]


# ─── chargement ───────────────────────────────────────────────────────────────

def charger_incidents() -> list[IncidentSecuriteV2Canonique]:
    schema = charger_schema(DEFAULT_SCHEMA)
    verifier_coherence(schema)
    raw = json.loads(DEFAULT_INPUT.read_text(encoding="utf-8"))
    payloads = raw if isinstance(raw, list) else raw.get("_embedded", {}).get("module", [])
    incidents, skipped = [], 0
    for p in payloads:
        inc = extraire(p, schema)
        if inc:
            incidents.append(inc)
        else:
            skipped += 1
    return incidents, skipped


# ─── helpers stats ────────────────────────────────────────────────────────────

def _is_trivial(v) -> bool:
    if v is None:
        return False
    return str(v).strip().lower() in VALEURS_TRIVIALES


def _rempli(incs, champ):
    return [i for i in incs if getattr(i, champ, None) is not None]


def _non_trivial_texte(incs, champ):
    return [i for i in incs
            if getattr(i, champ, None) is not None
            and not _is_trivial(getattr(i, champ))]


def _longueurs(incs, champ):
    return [len(str(getattr(i, champ, "") or "").strip())
            for i in incs if getattr(i, champ, None) is not None
            and not _is_trivial(getattr(i, champ))]


# ─── section A : remplissage global ──────────────────────────────────────────

def section_a(incs: list) -> list[dict]:
    n = len(incs)
    rows = []
    for f in fields(IncidentSecuriteV2Canonique):
        if f.name in ("entites", "incident_id", "source_module",
                      "last_indexed_at", "is_test_data", "llm_model"):
            continue
        vals = [getattr(i, f.name) for i in incs]
        non_null = sum(1 for v in vals if v is not None)
        # type
        if f.name in CHAMPS_TEXTUELS:
            t = "texte"
        elif f.name in CHAMPS_CATEGORIELS:
            t = "catégoriel"
        elif f.name in CHAMPS_DATES:
            t = "date"
        elif f.name in CHAMPS_BOOLEENS:
            t = "booléen"
        else:
            t = "autre"
        rows.append({"champ": f.name, "type": t, "rempli": non_null,
                     "pct": non_null / n * 100 if n else 0})
    return sorted(rows, key=lambda r: -r["pct"])


# ─── section B : champs textuels ─────────────────────────────────────────────

def section_b(incs: list) -> list[dict]:
    n = len(incs)
    min_lengths = IncidentSecuriteV2Canonique._CHAMPS_MIN_LENGTH
    embedding_champs = set(IncidentSecuriteV2Canonique.CHAMPS_EMBEDDING)
    rows = []
    for champ in CHAMPS_TEXTUELS:
        remplis = _rempli(incs, champ)
        trivials = sum(1 for i in remplis if _is_trivial(getattr(i, champ)))
        non_triv = [i for i in remplis if not _is_trivial(getattr(i, champ))]
        longueurs = _longueurs(incs, champ)
        med = int(median(longueurs)) if longueurs else 0
        avg = int(mean(longueurs)) if longueurs else 0
        if champ in embedding_champs:
            seuil = min_lengths.get(champ, 20)
            above = sum(1 for l in longueurs if l >= seuil)
            pct_embed = above / n * 100 if n else 0
        else:
            pct_embed = None
        rows.append({
            "champ": champ,
            "rempli_n": len(remplis),
            "rempli_pct": len(remplis) / n * 100 if n else 0,
            "trivial_n": trivials,
            "trivial_pct": trivials / n * 100 if n else 0,
            "med_len": med,
            "avg_len": avg,
            "pct_embed": pct_embed,
        })
    return rows


# ─── section C : champs catégoriels ──────────────────────────────────────────

def section_c(incs: list) -> dict[str, dict]:
    result = {}
    for champ in CHAMPS_CATEGORIELS:
        vals = [getattr(i, champ) for i in incs if getattr(i, champ) is not None]
        ctr = Counter(vals)
        result[champ] = {
            "total": len(vals),
            "distincts": len(ctr),
            "top8": ctr.most_common(8),
        }
    return result


# ─── section D : dates et booléens ───────────────────────────────────────────

def section_d(incs: list) -> dict:
    n = len(incs)
    dates = {}
    for champ in CHAMPS_DATES:
        vals = [getattr(i, champ) for i in incs if getattr(i, champ) is not None]
        if vals:
            try:
                dates[champ] = {
                    "n": len(vals), "pct": len(vals) / n * 100,
                    "min": str(min(vals))[:10], "max": str(max(vals))[:10],
                }
            except Exception:
                dates[champ] = {"n": len(vals), "pct": len(vals) / n * 100,
                                "min": "?", "max": "?"}
        else:
            dates[champ] = {"n": 0, "pct": 0, "min": "-", "max": "-"}

    bools = {}
    for champ in CHAMPS_BOOLEENS:
        vals = [getattr(i, champ) for i in incs]
        bools[champ] = {
            "true": sum(1 for v in vals if v is True),
            "false": sum(1 for v in vals if v is False),
            "none": sum(1 for v in vals if v is None),
        }
    return {"dates": dates, "bools": bools}


# ─── section E : relations Neo4j ─────────────────────────────────────────────

def section_e(incs: list) -> dict | str:
    n = len(incs)
    try:
        with Neo4jClient(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD) as neo4j:
            # Relations satellite
            rows = neo4j.run(
                "MATCH (i:IncidentSecu)-[r]->(sat) "
                "WITH i.incident_id AS iid, labels(sat)[0] AS lbl "
                "RETURN lbl, count(DISTINCT iid) AS n_incidents, "
                "       count(*) AS n_liens "
                "ORDER BY n_incidents DESC"
            )
            result = {"_relations": {}}
            for row in rows:
                lbl = row["lbl"]
                result["_relations"][lbl] = {
                    "incidents_avec": row["n_incidents"],
                    "pct": row["n_incidents"] / n * 100 if n else 0,
                    "moy_par_incident": round(row["n_liens"] / row["n_incidents"], 2)
                    if row["n_incidents"] else 0,
                }
            # Propriétés Neo4j absentes du fichier source
            props_rows = neo4j.run(
                "MATCH (i:IncidentSecu) "
                "RETURN count(i) AS total, "
                "       count(i.resume_llm) AS avec_resume_llm, "
                "       count(i.llm_model) AS avec_llm_model"
            )
            if props_rows:
                r = props_rows[0]
                result["_neo4j_props"] = {
                    "total": r["total"],
                    "resume_llm": r["avec_resume_llm"],
                    "resume_llm_pct": round(r["avec_resume_llm"] / r["total"] * 100, 1)
                    if r["total"] else 0,
                }
            return result
    except Exception as exc:
        return f"[Neo4j indisponible] {exc}"


# ─── section F : signaux architecture ────────────────────────────────────────

def section_f(incs: list, sec_b: list[dict], sec_c: dict, sec_e) -> list[str]:
    n = len(incs)
    lines = []

    # % reliés à ≥1 Personne
    rels = sec_e.get("_relations", {}) if isinstance(sec_e, dict) else {}
    if "Personne" in rels:
        p = rels["Personne"]
        lines.append(f"Incidents reliés à ≥1 Personne : {p['incidents_avec']:,} / {n:,} ({p['pct']:.1f}%)")
    else:
        with_personne = sum(1 for i in incs
                            if any(e.noeud == "Personne" for e in i.entites))
        lines.append(f"Incidents avec ≥1 Personne (source fichier) : {with_personne:,} / {n:,} ({with_personne/n*100:.1f}%)")

    # resume_llm depuis Neo4j
    neo4j_props = sec_e.get("_neo4j_props", {}) if isinstance(sec_e, dict) else {}
    if neo4j_props:
        lines.append(
            f"resume_llm (Neo4j) : {neo4j_props['resume_llm']:,} / {neo4j_props['total']:,} "
            f"({neo4j_props['resume_llm_pct']:.1f}%)"
        )

    # action_corrective
    ac = next((r for r in sec_b if r["champ"] == "action_corrective"), None)
    if ac:
        lines.append(
            f"action_corrective — trivial: {ac['trivial_pct']:.1f}% | "
            f"au-dessus seuil embedding: {ac['pct_embed']:.1f}%"
        )

    # detail non trivial
    det = next((r for r in sec_b if r["champ"] == "detail"), None)
    if det:
        lines.append(
            f"detail non trivial : {100 - det['trivial_pct']:.1f}% | "
            f"au-dessus seuil embedding : {det['pct_embed']:.1f}%"
        )

    # % incidents produisant ≥1 chunk
    n_avec_chunk = sum(
        1 for i in incs if i.textes_pour_embedding()
    )
    lines.append(f"Incidents produisant ≥1 chunk Qdrant : {n_avec_chunk:,} / {n:,} ({n_avec_chunk/n*100:.1f}%)")

    # champs catégoriels assez remplis
    bien_remplis = [
        f"{champ} ({stats['total']:,} remplis, {stats['distincts']} valeurs)"
        for champ, stats in sec_c.items()
        if stats["total"] / n >= 0.80
    ]
    lines.append(f"Catégoriels ≥80% remplis (agrégation possible) : {', '.join(bien_remplis)}")

    return lines


# ─── anonymisation ────────────────────────────────────────────────────────────

def _build_person_map(incs: list) -> dict[str, str]:
    """Logins extraits de tous les EntiteLiee Personne → pseudonymes stables."""
    logins: set[str] = set()
    for inc in incs:
        for e in inc.entites:
            if e.noeud == "Personne":
                logins.add(e.valeur)
    mapping = {}
    for i, login in enumerate(sorted(logins), 1):
        mapping[login] = f"Agent_{i:03d}"
    return mapping


def _scrub_text(text: str, person_map: dict[str, str]) -> str:
    if not text:
        return text
    for real, fake in person_map.items():
        text = re.sub(re.escape(real), fake, text, flags=re.IGNORECASE)
    # emails
    text = re.sub(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", "[EMAIL]", text)
    # téléphones
    text = re.sub(r"\b(?:0[1-9])(?:[\s.\-]?\d{2}){4}\b", "[TEL]", text)
    return text


def _inc_to_dict(inc: IncidentSecuriteV2Canonique, person_map: dict[str, str]) -> dict:
    text_fields = set(CHAMPS_TEXTUELS)
    d = {}
    for f in fields(inc):
        v = getattr(inc, f.name)
        if f.name == "entites":
            continue
        if isinstance(v, (datetime, date, time)):
            v = str(v)
        if f.name in text_fields and isinstance(v, str):
            v = _scrub_text(v, person_map)
        d[f.name] = v
    # entités liées
    d["entites"] = [
        {
            "noeud": e.noeud,
            "cle": e.cle,
            "valeur": person_map.get(e.valeur, e.valeur) if e.noeud == "Personne" else e.valeur,
            "relation": e.relation,
        }
        for e in inc.entites
    ]
    return d


def choisir_echantillon(incs: list) -> list[IncidentSecuriteV2Canonique]:
    """Stratifie sur etat × severite ; favorise diversité et richesse."""
    seen_strata: set[tuple] = set()
    selected: list[IncidentSecuriteV2Canonique] = []

    def score(i: IncidentSecuriteV2Canonique) -> int:
        s = 0
        if i.detail and len(i.detail) > 100:
            s += 3
        if i.action_corrective and len(i.action_corrective.strip()) > 20 \
                and i.action_corrective.strip() not in {"0", "-"}:
            s += 2
        if any(e.noeud == "Personne" for e in i.entites):
            s += 1
        if i.desc_cause_1:
            s += 1
        if i.resume_llm:
            s += 1
        return s

    # 1er passage : un par strate (etat, severite)
    by_score = sorted(incs, key=score, reverse=True)
    for inc in by_score:
        if len(selected) >= 8:
            break
        strat = (inc.etat, inc.severite)
        if strat not in seen_strata:
            seen_strata.add(strat)
            selected.append(inc)

    # 2ème passage : compléter à 8 avec les mieux scorés non encore pris
    taken_ids = {i.incident_id for i in selected}
    for inc in by_score:
        if len(selected) >= 8:
            break
        if inc.incident_id not in taken_ids:
            selected.append(inc)
            taken_ids.add(inc.incident_id)

    return selected[:8]


# ─── rendu Markdown ──────────────────────────────────────────────────────────

def render_md(incs, n_skip, sec_a, sec_b, sec_c, sec_d, sec_e, sec_f) -> str:
    n = len(incs)
    n_test = sum(1 for i in incs if i.is_test_data)
    lines = []
    w = lines.append

    w("# Profil données — incident_securite_v2\n")
    w(f"- **Total enregistrements** : {n:,}")
    w(f"- **Ignorés (sans Num F.E.)** : {n_skip:,}")
    w(f"- **Marqués is_test_data** : {n_test:,}")
    w("")

    w("## A. Remplissage global\n")
    w("| Champ | Type | Rempli | % |")
    w("|---|---|---:|---:|")
    for r in sec_a:
        w(f"| `{r['champ']}` | {r['type']} | {r['rempli']:,} | {r['pct']:.1f}% |")
    w("")

    w("## B. Champs textuels\n")
    w("| Champ | Rempli% | Trivial% | Méd. len | Moy. len | ≥seuil embed% |")
    w("|---|---:|---:|---:|---:|---:|")
    for r in sec_b:
        embed_str = f"{r['pct_embed']:.1f}%" if r["pct_embed"] is not None else "—"
        w(f"| `{r['champ']}` | {r['rempli_pct']:.1f}% | {r['trivial_pct']:.1f}% "
          f"| {r['med_len']} | {r['avg_len']} | {embed_str} |")
    w("")

    w("## C. Champs catégoriels\n")
    for champ, stats in sec_c.items():
        w(f"### `{champ}` — {stats['total']:,} remplis, {stats['distincts']} valeurs distinctes\n")
        w("| Valeur | Count |")
        w("|---|---:|")
        for val, cnt in stats["top8"]:
            w(f"| {val} | {cnt:,} |")
        w("")

    w("## D. Dates et booléens\n")
    w("### Dates\n")
    w("| Champ | Rempli | % | Min | Max |")
    w("|---|---:|---:|---|---|")
    for champ, s in sec_d["dates"].items():
        w(f"| `{champ}` | {s['n']:,} | {s['pct']:.1f}% | {s['min']} | {s['max']} |")
    w("")
    w("### Booléens\n")
    w("| Champ | True | False | None |")
    w("|---|---:|---:|---:|")
    for champ, s in sec_d["bools"].items():
        w(f"| `{champ}` | {s['true']:,} | {s['false']:,} | {s['none']:,} |")
    w("")

    w("## E. Relations Neo4j\n")
    if isinstance(sec_e, str):
        w(f"> {sec_e}\n")
    else:
        rels = sec_e.get("_relations", {})
        neo4j_props = sec_e.get("_neo4j_props", {})
        w("| Type nœud | Incidents avec ≥1 | % | Moy. voisins |")
        w("|---|---:|---:|---:|")
        for lbl, s in rels.items():
            w(f"| `{lbl}` | {s['incidents_avec']:,} | {s['pct']:.1f}% | {s['moy_par_incident']} |")
        if neo4j_props:
            w(f"\n**Propriétés enrichies (Neo4j)** :")
            w(f"- `resume_llm` : {neo4j_props['resume_llm']:,} / {neo4j_props['total']:,} "
              f"({neo4j_props['resume_llm_pct']:.1f}%)")
    w("")

    w("## F. Signaux pour l'architecture\n")
    for line in sec_f:
        w(f"- {line}")
    w("")

    w("## Champs avec remplissage < 20%\n")
    bas = [r for r in sec_a if r["pct"] < 20]
    if bas:
        for r in bas:
            w(f"- `{r['champ']}` : {r['pct']:.1f}%")
    else:
        w("_Aucun champ sous 20%._")

    return "\n".join(lines)


# ─── résumé stdout ────────────────────────────────────────────────────────────

def print_summary(incs, n_skip, sec_a, sec_b, sec_e, sec_f):
    n = len(incs)
    print(f"\n{'='*60}")
    print(f"  PROFIL incident_securite_v2  —  {n:,} incidents")
    print(f"{'='*60}")
    print(f"  Ignorés (sans Num F.E.) : {n_skip:,}")
    print(f"  is_test_data            : {sum(1 for i in incs if i.is_test_data):,}")

    print(f"\n  Remplissage — champs principaux :")
    for r in sec_a[:12]:
        bar = "█" * int(r["pct"] / 5)
        print(f"    {r['champ']:<28s} {r['pct']:5.1f}%  {bar}")

    print(f"\n  Champs textuels — couverture embedding :")
    for r in sec_b:
        if r["pct_embed"] is not None:
            print(f"    {r['champ']:<28s} {r['pct_embed']:5.1f}%  ≥seuil")

    # resume_llm depuis Neo4j
    if isinstance(sec_e, dict) and "_neo4j_props" in sec_e:
        np = sec_e["_neo4j_props"]
        print(f"\n  Enrichissement LLM (Neo4j) :")
        print(f"    resume_llm : {np['resume_llm']:,} / {np['total']:,} ({np['resume_llm_pct']:.1f}%)")

    print(f"\n  Signaux architecture :")
    for line in sec_f:
        print(f"    • {line}")

    print(f"\n  Champs < 20% rempli :")
    bas = [r for r in sec_a if r["pct"] < 20]
    if bas:
        for r in bas:
            print(f"    ⚠  {r['champ']:<28s} {r['pct']:.1f}%")
    else:
        print("    (aucun)")
    print()


# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    REPORTS_DIR.mkdir(exist_ok=True)

    print("Chargement des incidents...", flush=True)
    incs, n_skip = charger_incidents()
    print(f"  {len(incs):,} incidents chargés, {n_skip:,} ignorés.")

    print("Calcul des statistiques...", flush=True)
    sec_a = section_a(incs)
    sec_b = section_b(incs)
    sec_c = section_c(incs)
    sec_d = section_d(incs)
    sec_e = section_e(incs)
    sec_f = section_f(incs, sec_b, sec_c, sec_e)

    # livrable 1 : rapport MD
    md = render_md(incs, n_skip, sec_a, sec_b, sec_c, sec_d, sec_e, sec_f)
    md_path = REPORTS_DIR / "profil_incident_v2.md"
    md_path.write_text(md, encoding="utf-8")

    # livrable 2 : échantillon anonymisé
    print("Construction de l'échantillon anonymisé...", flush=True)
    person_map = _build_person_map(incs)
    sample = choisir_echantillon(incs)
    sample_dicts = [_inc_to_dict(i, person_map) for i in sample]
    output = {
        "_avertissement": (
            "Ce fichier a été anonymisé automatiquement. "
            "L'anonymisation des champs texte libre est imparfaite : "
            "des données personnelles résiduelles peuvent subsister. "
            "Une relecture humaine est OBLIGATOIRE avant tout partage externe."
        ),
        "incidents": sample_dicts,
    }
    json_path = REPORTS_DIR / "echantillon_anonymise_incident_v2.json"
    json_path.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str),
                         encoding="utf-8")

    print_summary(incs, n_skip, sec_a, sec_b, sec_e, sec_f)
    print(f"  Rapport    : {md_path}")
    print(f"  Échantillon: {json_path}")
    print(f"  Pseudonymes: {len(person_map)} logins → Agent_XXX\n")


if __name__ == "__main__":
    main()
