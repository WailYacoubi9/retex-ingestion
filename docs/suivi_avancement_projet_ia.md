# Projet IA intra'know — Suivi d'avancement

*Compte rendu — 5 août 2026*

## Où en est le projet

Assistant RETEX Safety sur les fiches d'incidents des Aéroports de Lyon (**9 191 fiches**, 2008-2026).
Le **socle est opérationnel** ; le chantier en cours porte sur la **qualité de la recherche
d'information** et la **rigueur des données** qui alimentent l'assistant.

## Le socle opérationnel

- Plusieurs **voies de réponse** spécialisées — comptage / statistiques, recherche, recommandation,
  synthèse — chacune avec un **refus explicite** quand la donnée ne permet pas de répondre : l'assistant
  ne « comble pas les trous » par une réponse inventée.
- Les **comptages déterministes** (total, par année, par gravité, par type) sont **fiables** et servent
  de repères de contrôle.

## Chantier en cours — améliorer la recherche

Diagnostic mesuré : l'assistant traitait chaque fiche **champ par champ**, ce qui bridait la recherche.
Trois évolutions (détaillées dans la note dédiée) :

1. **Un chunk = une fiche entière.** La recherche prend en compte tous les champs utiles, plus
   seulement le texte. Gain mesuré au banc d'essai : la capacité à retrouver les bonnes fiches passe de
   **40 % à 58 %**.
2. **Un filtrage sur les champs.** Restreindre sur des critères exacts (année, type, lieu…) avant de
   chercher — *remarque de Louis-Nicolas*.
3. **Deux étiquettes « cause » et « action ».** Cibler les fiches réellement exploitables pour
   l'analyse des causes et la recommandation — *remarque d'Hélèna*.

**État : implémenté et validé en local** (index divisé par 3, plus aucun doublon). Reste la
**ré-ingestion sur le serveur** puis son test.

## Données & configuration

- Le **fichier de configuration** qui pilote l'assistant a été revu sur la base des **statistiques** du
  corpus **et** des **explications métier de Hugo** — le rôle de chaque champ est désormais justifié.
- Un **journal des défauts de données** est tenu pour la mise en production (fiabilité des champs,
  populations hétérogènes…).

## Validation métier

Questionnaire transmis à Hugo : plusieurs points **tranchés** (séparation sécurité / sûreté, analyse
causale fondée sur les 7M) et **intégrés** à la configuration. Quelques champs restent à confirmer.

## Prochaines étapes

1. **Ré-ingestion serveur** + mesure du gain, sous garde que les comptages de référence ne régressent pas.
2. **Suite des améliorations** : normalisation des acteurs (une même société aujourd'hui éclatée en
   plusieurs), filtres de dates (« entre 2020 et 2023 »), pré-filtrage.
3. **Confirmation métier** des derniers champs.

## Points d'attention

- **Plafonds de données** : les causes sont rédigées sur ~41 % des fiches, les plans d'action sur
  ~10 % — l'assistant doit l'**annoncer** plutôt que généraliser.
- **Corpus hétérogène** (fiches récentes complètes vs anciennes réduites) : tout pourcentage doit
  **déclarer sa population** de référence.
