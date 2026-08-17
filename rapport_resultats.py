#!/usr/bin/env python3
"""Assemble le rapport des résultats à partir des mesures brutes -> rapport_resultats.md"""
import json, statistics, datetime
from collections import defaultdict

B = "/home/yie0070/retex-split/retex-ingestion/"
m = statistics.mean


def charge(f):
    R = [json.loads(l) for l in open(B + f, encoding="utf-8")]
    g, v = defaultdict(lambda: defaultdict(list)), defaultdict(lambda: defaultdict(list))
    for d in R:
        for k in ("prec", "couv", "mrr"):
            g[(d["mode"], d["collection"])][k].append(d[k])
            v[(d["voie"], d["mode"], d["collection"])][k].append(d[k])
        g[(d["mode"], d["collection"])]["abst"].append(1.0 if d["abstention"] else 0.0)
    return g, v


APRES, VA = charge("eval_voies.jsonl")
AVANT, VB = charge("eval_voies_AVANT_FIX.jsonl")
G = [json.loads(l) for l in open(B + "golden_voies.jsonl", encoding="utf-8")]
COLLS = ["Ancien", "Enrichi", "Hybride"]
MODES = ["dense", "recherche", "reco", "causes"]

L = []
L.append("# Résultats des mesures — récupération intra'know\n")
L.append(f"*{datetime.date.today().isoformat()} · toutes les mesures de ce document sont "
         "reproductibles à partir des scripts et jeux de données cités en fin de fichier.*\n")

# ── méthode
L.append("## Méthode\n")
L.append(f"**Jeu de référence** : {len(G)} questions à vérité terrain exacte "
         f"({sum(1 for g in G if g['voie']=='recherche')} recherche · "
         f"{sum(1 for g in G if g['voie']=='cause')} cause · "
         f"{sum(1 for g in G if g['voie']=='action')} action). Pour chaque question, un "
         "**ensemble non ordonné** de fiches, à **pertinence binaire** — toutes également pertinentes.\n")
L.append("**Trois collections comparées**, mêmes 9 191 fiches, trois découpages :\n")
L.append("| Collection | Qdrant | Points | Découpage |")
L.append("|---|---|---:|---|")
L.append("| **Ancien** | `incident_chunks` | 27 195 | 1 chunk par **champ** (production actuelle) |")
L.append("| **Enrichi** (v2b) | `incident_chunks_v2b` | 9 585 | 1 chunk par **fiche** (tout fusionné) |")
L.append("| **Hybride** (v2c) | `incident_chunks_v2c` | 17 117 | fiche **+ chunks cause/action** (dupliqués) |")
L.append("\n**Quatre voies** : `dense` (cosinus seul, = production `/auto`) · `recherche` "
         "(dense + BM25 + RRF + reranker) · `reco` (idem, seuils reco) · `causes` (routage sur les chunks cause).\n")
ge = sum(1 for g in G if g["n_pertinents"] >= g["k"])
L.append(f"> ⚠️ **Aucun plafond** : les {ge}/{len(G)} questions ont au moins `k` bonnes réponses "
         "disponibles, donc la précision@k peut atteindre 100 % partout. Une précision de 35 % "
         "signifie **6,5 fiches fausses sur 10**, pas une limite du jeu de test.\n")

L.append("\n### Les métriques retenues — et celle qu'on a écartée\n")
L.append("| Métrique | Définition | Ce qu'elle mesure |")
L.append("|---|---|---|")
L.append("| **précision@k** | bonnes rendues / k | le **bruit** que le générateur doit filtrer |")
L.append("| **succès@k** | % de questions avec **au moins une** bonne fiche | la capacité à répondre **tout court** |")
L.append("| **n brut (médiane)** | nombre de bonnes fiches rendues | ce qui **nourrit** réellement le LLM |")
L.append("| **MRR** | 1 / rang de la 1ʳᵉ bonne | la **position** — la troncature coupe |")
L.append("| **rappel@50** *(diagnostic)* | bonnes fiches dans les 50 premiers chunks | sépare « jamais vue » de « mal classée » |")
L.append("\n> **Métrique écartée — la « couverture ».** Définie comme `bonnes / min(k, n)`, elle s'est "
         "révélée **identique à la précision@k sur 552/552 mesures** : toutes les questions ayant n ≥ k, "
         "`min(k,n)` vaut toujours `k`. Elle a été publiée comme si elle ajoutait une information ; "
         "elle n'en ajoutait aucune. Le **rappel brut** est lui aussi inutilisable ici — il plafonne "
         "mécaniquement dès que n dépasse k.\n")
L.append("> **Pourquoi la moyenne ne suffit pas.** Une question à 30 % (3 bonnes fiches sur 10) est "
         "parfaitement répondable ; une question à 0 % ne l'est pas du tout. La moyenne mélange les deux. "
         "D'où la publication de la **distribution** (§ 2 bis) plutôt que d'un seul chiffre.\n")

# ── résultat principal
L.append("\n## 1. Le résultat principal — le correctif du reranker\n")
L.append("Le document soumis au cross-encoder était composé du seul `titre + description`. "
         "Une fiche retrouvée via un chunk cause ou action était donc **jugée sur un texte ne "
         "contenant pas l'information qui avait fait le match** → score ≈ 0,008 → rejetée, alors "
         "que la récupération l'avait correctement trouvée. Le correctif injecte le texte des "
         "champs ayant matché.\n")
L.append("| Voie | Collection | avant | après | Δ | abstentions avant → après |")
L.append("|---|---|---:|---:|---:|---|")
for mode in MODES:
    for lab in COLLS:
        a, b = AVANT[(mode, lab)], APRES[(mode, lab)]
        if not a["prec"]:
            continue
        d = m(b["prec"]) - m(a["prec"])
        star = " **★**" if d >= 0.05 else ""
        L.append(f"| {mode} | {lab} | {m(a['prec']):.0%} | **{m(b['prec']):.0%}** | {d:+.0%} | "
                 f"{int(sum(a['abst']))}/46 → **{int(sum(b['abst']))}/46**{star} |")
L.append("\n**Le mode `dense` est resté strictement identique (+0 % partout)** — il n'a pas de "
         "reranker : c'est le témoin qui prouve que la récupération n'a pas été touchée.\n")
L.append("Gain le plus fort : **recherche / Hybride +13 points**, et les abstentions passent de "
         "16/46 à 4/46. L'assistant refusait de répondre à **un tiers des questions** parce que le "
         "reranker regardait le mauvais texte.\n")

# ── par type
L.append("\n## 2. Résultats par type de question (après correctif)\n")
for voie in ("recherche", "cause", "action"):
    nq = sum(1 for g in G if g["voie"] == voie)
    L.append(f"\n**Questions « {voie} »** ({nq} questions) — précision@k\n")
    L.append("| Méthode | Ancien | Enrichi | Hybride |")
    L.append("|---|---:|---:|---:|")
    for mode in MODES:
        cells = [f"{m(VA[(voie,mode,lab)]['prec']):.0%}" if VA[(voie, mode, lab)]["prec"] else "—"
                 for lab in COLLS]
        L.append(f"| {mode} | " + " | ".join(cells) + " |")

L.append("\n**Lecture** : Enrichi domine les questions de recherche pure ; Hybride domine "
         "nettement les questions causales grâce à son chunk cause dédié ; l'Ancien est en retrait "
         "partout sauf en recherche rerankée.\n")

# ── 2 bis : succès, n brut, distribution
from collections import Counter
E_APRES = [json.loads(l) for l in open(B + "eval_voies.jsonl", encoding="utf-8")]
par = defaultdict(list)
for d in E_APRES:
    par[(d["mode"], d["collection"])].append(round(d["prec"] * d["k"]))

L.append("\n## 2 bis. Succès, matière fournie, et distribution\n")
L.append("La précision seule est trompeuse : elle agrège des questions **répondables** (3-4 bonnes "
         "fiches) et des questions **sans aucune réponse**. Les deux métriques ci-dessous les séparent.\n")
L.append("| Voie | Collection | précision@k | **succès@k** | **médiane n** | MRR |")
L.append("|---|---|---:|---:|---:|---:|")
for mode in MODES:
    for lab in COLLS:
        a = APRES[(mode, lab)]
        n = par[(mode, lab)]
        if not a["prec"] or not n:
            continue
        succes = sum(1 for v in n if v >= 1) / len(n)
        L.append(f"| {mode} | {lab} | {m(a['prec']):.0%} | **{succes:.0%}** | "
                 f"**{statistics.median(n):.0f}** | {m(a['mrr']):.2f} |")

L.append("\n**Distribution du nombre de bonnes fiches** — meilleure configuration "
         "(`recherche` / Hybride), sur les 46 questions :\n")
n = par[("recherche", "Hybride")]
c = Counter(n)
L.append("```")
for v in range(0, max(c) + 1):
    if c.get(v):
        L.append(f"{v:2} bonne(s) : {'█' * c[v]} {c[v]}")
L.append("```")
z = c.get(0, 0); trois = sum(k for v, k in c.items() if v >= 3)
L.append(f"\n**{z} questions à zéro ({z/len(n):.0%}) · {trois} questions à ≥3 ({trois/len(n):.0%}).** "
         "La distribution est **bimodale** : le système n'est pas médiocre partout, il est bon sur "
         "la moitié des questions et aveugle sur un quart. Le milieu est creux — ce qui signifie "
         "qu'optimiser le **classement** serait la mauvaise réponse.\n")
zeros = [d for d in E_APRES if d["mode"] == "recherche" and d["collection"] == "Hybride"
         and round(d["prec"] * d["k"]) == 0]
cz = Counter(d["voie"] for d in zeros)
detail_zeros = ", ".join(f"**{n} en {voie}**" for voie, n in cz.most_common())
L.append(f"Et les zéros ne sont pas répartis au hasard : {detail_zeros}. "
         f"{sum(1 for d in zeros if d['abstention'])} d'entre eux sont des **abstentions** "
         "(le reranker a tout jugé sous le seuil), les autres rendent 10 fiches toutes fausses — "
         "deux pannes distinctes, qui appellent deux correctifs distincts.\n")

# ── mécanismes
L.append("\n## 3. Les trois mécanismes identifiés\n")
L.append("### a. Dilution — le chunk trop long\n")
L.append("Même fiche, même information causale, deux emballages :\n")
L.append("| chunk | taille | cosinus vs « cause : agent nouvellement arrivé » |")
L.append("|---|---:|---:|")
L.append("| `fiche` *(contient la cause)* | 908 car | **0,470** — au ras du seuil 0,45 |")
L.append("| `cause` *(cause seule)* | 146 car | **0,679** |")
L.append("\nLe texte contient pourtant *« Nouvel agent, nouvellement formé »* — quasi-appariement "
         "littéral avec la requête. **+0,21 de cosinus uniquement grâce à l'emballage** : au-delà "
         "d'une certaine longueur, un chunk devient un résumé flou de lui-même où aucun détail ne "
         "ressort. C'est ce qui explique l'écart 3 % (Enrichi) vs 18 % (Hybride) sur les questions causales.\n")

L.append("### b. Micro-chunks dupliqués — le chunk trop court (Ancien)\n")
L.append("**207 fiches portent exactement le titre « collision aviaire »** → 207 vecteurs `titre` "
         "**identiques** → cosinus **1,000** pour les 10 premiers résultats → l'ordre entre elles "
         "est **arbitraire** (ordre interne de l'index). Sur une question portant sur les espèces, "
         "les fiches retenues — et donc les espèces observées — ne doivent rien à la pertinence.\n")

L.append("### c. Biais de multiplicité — plus de chunks, plus de tirages\n")
L.append("Une fiche indexée 3 fois a 3 occasions d'entrer dans le top-N. Mesuré :\n")
L.append("| | population | fiches récupérées |")
L.append("|---|---:|---:|")
L.append("| chunks/fiche (v2c) | 1,86 | **2,46** → biais **×1,32** |")
L.append("| part des fiches à ≥3 chunks | 29 % | **54 %** |")
L.append("\nAmpleur par collection, sur les fiches attendues des questions causales :\n")
L.append("| Collection | population | q. cause | avantage mécanique |")
L.append("|---|---:|---:|---:|")
L.append("| Ancien | 2,96 | 4,55 | ×1,54 |")
L.append("| **Enrichi** | **1,04** | 1,26 | **×1,21** — quasi neutre |")
L.append("| **Hybride** | 1,86 | 3,03 | **×1,63** — le plus biaisé |")
L.append("\n**Ce biais n'explique pourtant pas les scores.** Test de profondeur sur les 12 questions "
         "causales (dense pur, précision@10) :\n")
L.append("| profondeur de récupération | Enrichi | Hybride | écart |")
L.append("|---:|---:|---:|---:|")
for p in (50, 150, 400, 1000):
    L.append(f"| {p} | 3 % | 18 % | **+14 pts** |")
L.append("\nL'écart **ne bouge pas d'un point** en récupérant 20× plus profond. Si l'avantage de "
         "v2c tenait à la multiplicité, Enrichi rattraperait en creusant — il ne rattrape jamais. "
         "**L'avantage est sémantique, pas arithmétique.** Le biais déplace *quelles* fiches "
         "sortent, pas *si* v2c trouve mieux les causes.\n")

L.append("> Ce biais reste important pour une autre raison : il rend l'échantillon récupéré "
         "**non représentatif** du corpus (sur-représentation des fiches bien documentées). "
         "Toute lecture *fréquentielle* de ce qui remonte est donc faussée.\n")

# ── agrégation
L.append("\n## 4. Ce que la récupération ne peut pas faire\n")
L.append("Question testée : **« quelles races d'oiseaux sont les plus concernées par les collisions "
         "aviaires ? »**, avec une vérité terrain complète (extraction des espèces sur 1 439 fiches, "
         "84 % des collisions aviaires).\n")
L.append("| | Résultat |")
L.append("|---|---|")
L.append("| Espèce n°1 correcte | **11 / 11** configurations ✅ |")
L.append("| Classement (top 3) correct | **0 / 11** ❌ |")
L.append("\nLe faucon crécerelle pèse **51,6 %** : il ressort de n'importe quel échantillon de 10 "
         "fiches. **La bonne réponse est un effet de dominance statistique, pas un comptage.** "
         "Le classement, lui, exige de distinguer martinet (8,3 %) et buse variable (7,9 %) — "
         "impossible sur 10 fiches tirées de 1 439. Le martinet, 2ᵉ espèce réelle avec 120 fiches, "
         "**n'apparaît aucune fois** sur les 11 échantillons, alors qu'on en attendrait ~7 si le "
         "tirage était neutre.\n")
L.append("**Conclusion** : aucun réglage de voie, de collection ou de `k` ne fera répondre à cette "
         "question. Elle relève de l'**agrégation** (champ dérivé `espece` + voie statistique), "
         "pas de la recherche.\n")

# ── conclusions
L.append("\n## 5. Conclusions\n")
L.append("1. **Le correctif du reranker est le gain le plus rentable** : +6 à +13 points selon la "
         "configuration, abstentions divisées par 4, **indépendant de la collection** — il profite "
         "donc à la production telle qu'elle est, sans ré-ingestion.\n")
L.append("2. **Aucune collection ne domine partout.** Enrichi gagne en recherche pure, Hybride en "
         "causal. Les deux échouent par des extrémités opposées : chunk trop long (dilution) contre "
         "chunks trop courts et dupliqués.\n")
L.append("3. **Une même fiche doit être interrogeable à plusieurs échelles.** C'est le vrai argument "
         "en faveur de l'approche hybride — pas la redondance, mais la granularité.\n")
L.append("4. **Les questions de comptage ne doivent pas passer par la récupération.** "
         "Le retrieval trouve, le graphe compte.\n")

L.append("\n## 6. Ce qui reste ouvert\n")
L.append("- **v2d — la séparation stricte** : aujourd'hui v2c **duplique** (causes et actions sont "
         "à la fois dans le chunk fiche et dans les chunks dédiés). Un design où le chunk fiche ne "
         "contiendrait que la **situation** rendrait le matching *problème ↔ problème* effectif et "
         "supprimerait la redondance. **Jamais construit ni mesuré.**\n")
L.append("- **Champ dérivé `espece`** : l'extraction existe (84 % de couverture), reste à l'injecter "
         "dans le schéma et Neo4j pour que la voie statistique réponde exactement.\n")
L.append("- **Purge de l'action « à chaud »** du chunk action : +15 points mesurés séparément, "
         "non encore appliqué.\n")
L.append("- **Mesure de bout en bout** : tout ce document mesure la **récupération**, pas la "
         "réponse rédigée par le LLM.\n")

L.append("\n---\n")
L.append("*Sources : `golden_voies.jsonl` (jeu de référence) · `eval_voies.jsonl` et "
         "`eval_voies_AVANT_FIX.jsonl` (552 mesures chacun) · `resultats_especes_voies.md` · "
         "scripts `eval_voies.py`, `test_especes_voies.py`, `inspect_chunks.py`. "
         "Outil de comparaison interactif : `compare_front.py`.*\n")

open(B + "rapport_resultats.md", "w", encoding="utf-8").write("\n".join(L) + "\n")
print("écrit : " + B + "rapport_resultats.md")
