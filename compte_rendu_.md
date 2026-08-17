# Compte rendu — Comparaison automatique de la récupération (retrieval)

*Lundi 11 août 2026 · point d'avancement · projet assistant RETEX sécurité (intra'know)*

## Objectif de la période
Améliorer la façon dont l'assistant **retrouve les fiches d'incidents**, et **se doter d'un test automatique** pour comparer objectivement les approches sur les **trois voies** de l'assistant : **recherche**, **recommandation** et **analyse des causes**.

---

## Ce qui a été réalisé

### 1. Deux nouvelles organisations des données (collections)
Le retrieval repose sur une base vectorielle (Qdrant) où chaque fiche est découpée en **chunks** (morceaux de texte vectorisés). La version actuelle découpe **1 chunk par champ** → beaucoup de fragments courts et redondants (ex. de nombreux titres identiques → doublons qui brouillent le classement).

J'ai construit **deux alternatives** :
- **Collection « enrichie » (par concaténation)** — 1 chunk = 1 fiche, en **concaténant dans un même texte** : le titre, les **champs statiques** (type, lieu, piste, date, gravité, compagnie…) et le récit. Ce sont précisément les **champs retenus dans le fichier de configuration sur la base des statistiques du corpus** (cf. compte rendu du 5 août — ceux qui distinguent réellement une fiche). Concrètement, ces champs statiques — jusque-là exploités par la seule base structurée — deviennent **cherchables par le sens**. Résultat : chunks plus riches, plus discriminants, et fin des doublons (index ÷3).
- **Collection « hybride »** — la fiche enrichie **+ des chunks dédiés pour les causes et les actions** (les deux « étiquettes » du CR du 5 août), pour pouvoir retrouver spécifiquement sur le contenu causal et sur les actions correctives de suivi.

### 2. Finalisation d'un test automatique de comparaison entre les 3 voies
Un **dispositif de comparaison automatisé et reproductible**, qui met les approches en concurrence **sur les trois voies** (recherche, recommandation, causes). Il se compose de deux briques :

- **Un script de test** — pour un jeu de questions, il interroge chaque approche et calcule **automatiquement des métriques** (précision, couverture, MRR), avec une **pertinence définie sur le contenu** (non circulaire). Reproductible : on relance, on obtient les mêmes chiffres.
- **Une petite plateforme web de comparaison** — 3 onglets (les 3 collections) qui rejouent le **vrai pipeline de production** (embedding + BM25 + fusion RRF + reranker) sur une même question, avec un sélecteur pour **chaque voie** (recherche dense, recherche hybride, recommandation, causes). Elle affiche, pour chaque fiche retrouvée, le **score** et le **texte du chunk** qui a matché.

→ On peut désormais comparer **n'importe quelle approche, sur n'importe quelle voie**, de façon **systématique** : à l'œil (la plateforme) **et** chiffrée (le script).

---

## Prochaines étapes
1. **Lancer la comparaison** sur un jeu de questions consolidé (généré depuis la source, une trentaine par voie) pour produire des **résultats fiables** et trancher entre les collections.
2. **Statuer sur la configuration** de récupération à déployer (collection + activation éventuelle du reranker dans la voie principale).

*À ce stade, le dispositif de test est finalisé ; les résultats chiffrés seront produits à l'étape suivante, une fois le jeu de questions consolidé.*
