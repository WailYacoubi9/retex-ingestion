# Pourquoi un chunk par fiche, enrichi

Note explicative sur le changement d'indexation. Tous les chiffres cités sont mesurés sur le corpus (9 191 fiches) ou sur banc d'essai avec bge-m3.

---

## Le problème de départ

Aujourd'hui, chaque **champ** d'une fiche produit son propre vecteur. Une fiche donne donc 2 à 5 points séparés dans Qdrant : un pour le titre, un pour la description, un pour l'action corrective, etc. Au total **27 195 chunks pour 9 191 fiches**.

Deux conséquences, toutes deux mesurées.

**Les chunks sont trop courts.** Médiane : **14 tokens**. 77 % font moins de 32 tokens. On considère généralement qu'un chunk utile commence vers 100-200 tokens — on est cinq à dix fois en dessous.

**Le titre gagne toujours.** Le champ `titre` représente 33,5 % de l'index mais capte **87 % des dix premiers résultats**. Un texte court concentre les termes de la requête, donc il obtient mécaniquement un meilleur score qu'une description de trente mots qui, elle, contient la réponse.

Et comme les titres se répètent, **29,7 % des chunks sont des doublons stricts**. « Collision aviaire 36L » est le texte de **212 chunks identiques** : leurs vecteurs sont les mêmes, donc leur classement relatif est arbitraire. Le système tire au sort.

---

## Le principe : un chunk = une fiche

On arrête de découper par champ. Chaque fiche produit **un seul vecteur**, construit ainsi :

```
Fiche une fiche témoin — collision aviaire
Collision aviaire | Piste | 35L | 17/07/2025 | 2 - tolérable | Incident |
Décollage | WIZZ AIR | A321 / 321 | ADL_LYS, DSAC-Ce, SNA-Ce |
Agent aire de manœuvre (LYS) | Nuit | Facteurs : Milieu
Description : Il est nuit et le PRA est donc inactif lorsque nous sommes
contactés par la tour de contrôle suite au décollage du vol WMT9BQ de la
compagnie Wizz Air. […]
Causes : Milieu — Faune aviaire.
Action immédiate : Inspection de la piste 35L, collecte cadavre, info TWR,
rédaction CR
```

Le titre d'abord, puis les champs importants séparés par `|`, puis le narratif.

### Les treize champs retenus

Ils ont été choisis sur une mesure — **l'entropie normalisée**, qui dit à quel point les valeurs d'un champ varient d'une fiche à l'autre. Seuil retenu : > 0,5.

```
type d'événement · précision du type · lieu · point précis · date · gravité
classification · phase de vol · compagnie · type d'aéronef · unité d'application
notifiant · condition lumineuse (jour/nuit)
```

Plus, si au moins un axe causal est coché : `Facteurs : Main d'œuvre, Milieu`.

**Écartés** : `aérodrome` (94,7 % « LYS »), `processus` (99,9 % « PM2 »), `organisations informées` (99,6 % « DSAC »), `type` (98,6 % « FNE »), `état`, `étape`, `statut`. Un champ qui vaut presque toujours la même chose n'apporte rien : il ajoute le même texte aux 9 191 fiches, donc il ne les distingue pas. Il occupe seulement de la place dans le vecteur, au détriment du reste.

### Sur le séparateur

Le `|` n'a pas de sens particulier — c'est un séparateur neutre, il pourrait être une virgule. On n'écrit **pas de phrase** (« Cet incident de type collision aviaire s'est produit le… ») pour deux raisons : ça coûterait une génération LLM par fiche, et les mots de liaison seraient présents dans les 9 191 fiches, donc sans valeur discriminante — le même défaut que les champs constants.

Quand un champ est multi-valué, ses valeurs sont séparées par des virgules (`ADL_LYS, DSAC-Ce, SNA-Ce`) pour ne pas se confondre avec le `|` qui sépare les champs.

---

## Ce que ça apporte

### 1. Des chunks assez longs

Médiane : **14 → 132 tokens**. Part des fiches sous 64 tokens : **88 % → 4 %**. On entre dans la plage où un embedding représente réellement quelque chose.

### 2. La discrimination

C'est le cœur du raisonnement. Chaque attribut ajouté découpe l'ensemble des candidats :

| Attribut | Fiches restantes |
|---|---:|
| collision aviaire | 1 691 |
| + 36L | ~340 |
| + 2024 | ~30 |
| + Décollage | ~10 |
| + WIZZ AIR | 1 ou 2 |

Un seul attribut ne suffit jamais. Cinq identifient presque une fiche unique. C'est pour ça qu'il faut plusieurs champs, et pas seulement deux.

### 3. La fin des doublons

Les 212 fiches « Collision aviaire 36L » avaient des vecteurs identiques. Après enrichissement, chacune porte sa date, sa phase, sa compagnie : **plus aucun doublon strict**. Le tirage au sort disparaît.

### 4. Le biais du texte court disparaît

Le titre ne concourt plus séparément contre la description : c'est le même vecteur. Il continue d'apporter son signal, mais il ne peut plus évincer le contenu.

### 5. Les métadonnées deviennent cherchables

Point souvent mal compris : **l'agent qui rédige la description ne réécrit pas ce qu'il a coché dans le formulaire.** Il vient de sélectionner `Piste`, `36L - MAN`, `27/06/2012`, `3 - important` — il ne va pas les répéter dans son texte.

Regarde une fiche réelle de 2012 :

> « Suite signalement pilote intervention du CSO pour retrouver un oiseau sur la piste. Recherche négative pendant l'inspection. Lors des travaux sur la piste le lendemain un technicien du balisage à retrouvé un (Oedicnéme) sur le bord de piste dans l'herbe au niveau de A7. »

Ni `36L`, ni la date, ni la gravité. Pourtant, tout cela est dans la fiche. Comme seul ce texte était vectorisé, une recherche « collision aviaire sur la 36L » ne pouvait pas trouver cette fiche.

**La concaténation ne crée rien.** Elle rapatrie dans le vecteur une information déjà présente dans la fiche, mais que la recherche sémantique ne voyait pas.

---

## Le résultat mesuré

Banc d'essai : 5 variantes, 45 requêtes métier, bge-m3 réel, comparaison appariée.

| Variante | rappel@10 |
|---|---:|
| chunks par champ *(actuel)* | 40,0 % |
| un chunk par fiche, narratif seul | 51,9 % |
| **un chunk par fiche, narratif + champs importants** | **58,4 %** |

- gain de la **fusion** : **+11,9 points**
- gain des **champs importants** : **+7,4 points**
- total : **+18,4 points**

Effet de bord : l'index passe de 27 195 à ~9 191 vecteurs. **Trois fois plus petit et plus performant.**

---

## Le payload : filtrer avant de chercher

À côté du vecteur, chaque point porte des **champs séparés** — le payload. Ils ne servent pas à la similarité mais au filtrage exact.

```
vecteur  : [0.12, -0.44, 0.81, ...]
payload  : { annee: 2025, type_evenement: ["Collision aviaire"],
             lieu: "Piste", compagnie: "wizz air", severite: "2 - tolérable",
             phase_vol: "Décollage", a_cause: true, a_action: false }
```

Aujourd'hui, le payload ne contient **qu'un seul champ métier** (`severite`). Il n'y a donc rien sur quoi filtrer — c'est pourquoi la ré-ingestion est nécessaire.

**Comment ça marche.** Sur « collisions aviaires sur la 36L en 2024 », le parseur extrait `annee=2024` et `type="Collision aviaire"`. Qdrant restreint l'espace de recherche aux ~98 points correspondants, **puis** la recherche vectorielle s'exécute dans ce sous-ensemble.

Important : on ne cherche pas la chaîne « 2024 » dans le texte. On compare un champ `annee` de type entier. C'est exact, sans ambiguïté — alors qu'une date peut apparaître sous plusieurs formes dans un texte, ou dans un numéro de fiche.

**Pourquoi c'est indispensable.** Mesuré aujourd'hui : sur cinq questions datées, **0 à 2 résultats sur 10** respectent l'année demandée. Un vecteur ne comprend pas une date — `2024` et `2023` sont proches sémantiquement alors qu'ils désignent des ensembles disjoints.

> Le filtre pour ce qui est exact, le vecteur pour ce qui est flou.

---

## Les étiquettes `a_cause` et `a_action`

Deux booléens dans le payload :

- `a_cause` : la fiche a au moins une cause rédigée
- `a_action` : la fiche a une action tracée

**Pourquoi.** Les voies *recommandation* et *analyse causale* ont besoin de fiches qui ont de la matière. Or les plafonds sont bas : les causes sont rédigées sur **40,7 %** des fiches, les plans d'action structurés sur **10,3 %**.

Cas concret : sur les collisions aviaires, **1 683 fiches et 0 % d'action structurée**. Sans filtre, la voie recommandation remonte vingt fiches dont aucune ne porte d'action — et le modèle, faute de matière, produit des généralités.

Avec `a_action = true` en pré-filtre, la recherche ne porte que sur les fiches exploitables. Et si le résultat est vide, l'assistant peut le dire : *« aucune fiche comparable ne porte d'action tracée »* — une abstention motivée plutôt qu'une recommandation inventée.

---

## En résumé

| | Avant | Après |
|---|---|---|
| Unité indexée | le champ | **la fiche** |
| Nombre de vecteurs | 27 195 | ~9 191 |
| Longueur médiane | 14 tokens | **132 tokens** |
| Doublons stricts | 29,7 % | **0 %** |
| Métadonnées cherchables | non | **13 champs** |
| Filtrage exact | impossible | **année, type, lieu, gravité, phase, compagnie** |
| Rappel@10 mesuré | 40,0 % | **58,4 %** |