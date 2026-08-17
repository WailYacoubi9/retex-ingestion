# Note — évolutions de l'assistant intra'know

*Compte rendu de suivi d'avancement — projet IA · 5 août 2026*

L'assistant s'appuie sur **deux moteurs complémentaires** : une **base structurée** (le graphe) pour
les questions précises — combien, par année, par gravité, par type — et une **recherche par le sens**
pour retrouver des fiches similaires et alimenter les recommandations.

L'information des champs (lieu, date, type, gravité, compagnie…) était **déjà** exploitée par la base
structurée. Ce qui change : la **recherche par le sens en profite maintenant aussi**. On combine
désormais les **deux** — la précision des champs *et* la souplesse de la recherche.

## Ce qui change

**1. La recherche par le sens prend en compte les champs qui comptent, plus seulement le texte.**
Avant, pour retrouver des fiches « proches », l'assistant ne regardait que le texte de la fiche.
Désormais il tient compte, en même temps, du type, du lieu, de la piste, de la date, de la gravité,
de la compagnie… Une recherche comme « les collisions aviaires sur la 36L en 2024 » retrouve les
bonnes fiches même quand ces précisions avaient seulement été *cochées* dans le formulaire.

Ces champs n'ont pas été choisis au hasard : ils ont été **retenus sur la base des statistiques du
corpus** — ce sont ceux qui **distinguent réellement une fiche d'une autre**. Un champ qui vaut
presque toujours la même valeur (l'aérodrome, « LYS » dans 95 % des cas) n'aide pas à retrouver la
bonne fiche et n'a donc pas été retenu ; un champ qui varie (le type, le lieu, la gravité) si.
Chaque champ conservé l'a été **mesures à l'appui**, pas au jugé.

**2. Les recommandations s'appuient sur tous les champs — remarque de Louis-Nicolas.**
Comme l'a souligné Louis-Nicolas au copil, une recommandation ne doit pas reposer sur la seule
description. L'assistant croise maintenant réellement les caractéristiques d'une fiche (année, type,
lieu, gravité, compagnie), en plus de son récit.

**3. Deux étiquettes simples : « cause » et « action ».**
Chaque fiche reçoit deux repères : *a-t-elle une cause rédigée ?* et *a-t-elle un plan d'action de
suivi ?*
- L'étiquette **cause** sert à l'**analyse des causes** : l'assistant ne travaille que sur les fiches
  qui ont réellement une cause.
- L'étiquette **action** sert aux **recommandations — en réponse à la remarque d'Hélèna**. Une
  recommandation ne doit pas s'appuyer sur les actions prises « à chaud » (immédiates, propres à
  l'instant de l'événement), mais sur les **plans d'action de suivi**. L'étiquette **écarte
  automatiquement** les fiches sans plan d'action structuré, et l'assistant **le dit clairement**
  quand aucune fiche comparable n'en porte — plutôt que d'inventer une recommandation.

## Un paramétrage revu sur les données — et sur l'expertise métier

Toutes ces améliorations reposent sur un **fichier de configuration unique**, qui définit ce que
l'assistant exploite dans chaque fiche pour alimenter la base structurée. Il a été **entièrement revu
à partir des statistiques du corpus** — le choix et le traitement de chaque champ s'appuient sur les
données plutôt que sur une appréciation — et il est **enrichi par les explications de Hugo** sur le
sens des champs (ce que chacun mesure réellement, comment l'interpréter, lesquels sont fiables).
Statistiques et connaissance métier se combinent : on est ainsi **rigoureusement sélectif**, la donnée
qui alimente l'assistant est mieux qualifiée, et ce paramétrage sert de **référence unique**.

## Prochaine étape

Ces évolutions sont **en cours de finalisation** dans le code — proches d'être prêtes — et leurs
**tests sont en préparation**. Elles seront évaluées avant tout déploiement, en vérifiant qu'elles
améliorent les réponses sans dégrader les résultats déjà fiables (comptages par année, par
gravité, etc.).
