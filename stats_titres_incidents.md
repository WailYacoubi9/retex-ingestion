# Statistique — fréquence des titres d'incidents

*Source : `data/samples/incidents_avec_actions.json` (9 191 fiches) · titres normalisés (minuscules, sans accents) · 6 août 2026.*

## Chiffres clés

- **9191 fiches** avec un titre.
- **5717 titres distincts** (bruts) / **5577 normalisés** — soit **140 variantes** de casse/accents (même titre écrit différemment).
- **4913 titres uniques** (1 seule fiche) = **88 % des titres**.
- **4278 fiches (46.5 %) partagent leur titre** avec ≥ 1 autre fiche.
- **2441 fiches (26.6 %)** sont dans un groupe de **≥ 10 titres identiques**.
- Plus gros groupe : **207 fiches** (« collision aviaire »).

## Top 30 des titres

| Fréquence | Titre (normalisé) |
|---:|---|
| 207 | collision aviaire |
| 205 | collision aviaire 36l |
| 153 | baisse np sslia np7 iso np9 sans impact operationnel |
| 153 | collision aviaire 35l |
| 136 | collision aviaire 36r |
| 118 | collision aviaire 35r |
| 78 | collision aviaire 18l |
| 75 | collision aviaire 18r |
| 74 | collision aviaire sur 36l |
| 57 | collision aviaire 17r |
| 56 | collision aviaire 17l |
| 56 | collision aviaire sur 36r |
| 52 | refus priorite avion au repoussage |
| 48 | collision aviaire - sans dommage - zone a |
| 45 | fod hydraulique |
| 44 | deroutement sur lys cause couvre feu gva |
| 44 | baisse np sslia np7 iso np9 - pas d'impact operationnel |
| 43 | fod |
| 41 | baisse np sslia np7 iso np9 sans impact sur le trafic |
| 40 | collision animale 36l |
| 38 | passagers indisciplines (paxi) |
| 27 | fod - fuite hydraulique |
| 25 | collision aviaire sur 18l |
| 24 | deroutement sur lys cause meteo |
| 24 | paxi |
| 24 | fuite hydraulique |
| 24 | collision animale 18r |
| 23 | refus priorite avion au roulage |
| 23 | retour parking cause probleme technique |
| 23 | repoussage non conforme |

## Distribution des groupes

| | |
|---|---:|
| Titres uniques (1 fiche) | 4913 (88.1 % des titres) |
| Titres partagés (≥ 2 fiches) | 664 |
| Fiches en groupe ≥ 2 | 4278 (46.5 % des fiches) |
| Fiches en groupe ≥ 10 | 2441 (26.6 % des fiches) |
| Plus gros groupe | 207 fiches |

## Lecture

- **Près de la moitié des fiches (46,5 %) portent un titre non discriminant** (partagé avec au moins une autre), un quart appartient à un gros groupe (≥ 10). Un chunk fondé sur le seul titre ne peut pas départager ces fiches → classement quasi aléatoire dans ces groupes.
- **Double défaut des « collisions aviaires »** : à la fois *redondantes* (207 titres « collision aviaire » identiques) et *éclatées* par piste (36l, 35l, 36r, 35r, 18l, 18r… + variantes « sur 36l ») — impossibles à regrouper OU à distinguer par le titre seul.
- **140 variantes de graphie** confirment qu'une normalisation de casse/accents est nécessaire sur le titre comme sur les autres champs texte.
- **Implication** : c'est la racine du problème de récupération. Le document enrichi (date, piste, compagnie, phase dans le même vecteur) rend ces jumelles distinctes — gain à mesurer dans l'A/B.

*Table complète des titres → `stats_titres_incidents.csv`.*
