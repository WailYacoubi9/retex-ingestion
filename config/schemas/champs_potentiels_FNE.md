# Champs FNE potentiels — présents dans le modèle, pas encore en production

Ces **18 champs** apparaissent dans le modèle intra'know (vus dans
`incidents_extracted.json`) mais **n'arrivent pas** dans l'export de production
(`incidents_securite.json`, 100 fiches).

⚠️ **À lire avant d'utiliser ce tableau :**
- Source = **2 fiches de test Postman**, pas de la prod → c'est le *potentiel*, pas le réel.
- Aujourd'hui, **aucun** de ces champs n'est livré par l'export prod.
- Les **exemples** viennent des données (fiables). Le **sens** est une interprétation
  **à confirmer par le métier**.
- Presque tous sont des **référentiels** : si un jour ils arrivent, leur signification
  est déjà dans la donnée (`_label`) → rien à saisir à la main.

| Champ (JSON) | Thème | Exemple observé | Nature | Sens (à confirmer métier) |
|--------------|-------|-----------------|--------|----------------------------|
| `graviteecc` | Criticité | `4 - Mineur` | référentiel | Gravité de l'événement, échelle ECCAIRS ⭐ |
| `securitetypeevnt0` | Typologie | `FOD` | référentiel | Catégorie d'événement (niveau 0) ⭐ |
| `securitetypeevnt1` | Typologie | `Autre (FOD)` | référentiel | Sous-type d'événement (niveau 1) |
| `securitetypeevnt2` | Typologie | `ADRM: Aerodrome` | référentiel | Sous-type d'événement (niveau 2) |
| `type_de_no` | Typologie | `Externe` | référentiel | Type de notification (interne / externe ?) |
| `contxtcondmeteo` | Contexte | `Beau temps` | référentiel | Conditions météo au moment de l'événement |
| `contxtetatsol` | Contexte | `6 - Sèche` | référentiel | État du sol / de la piste |
| `contxtlorsdejournuit` | Contexte | `Nuit` | référentiel | Moment : jour / nuit |
| `contxtprecisionsmeteo` | Contexte | `NIL` | texte libre | Précisions météo en clair |
| `securitelieu1` | Lieu | `Parking aviation générale` | référentiel | Lieu de l'événement (niveau 1) |
| `securitelieu2` | Lieu | `Aire de stationnement` | référentiel | Lieu de l'événement (niveau 2) |
| `precisionsurlelieu` | Lieu | `PK12` | texte libre | Précision libre sur le lieu |
| `causespresumees` | Analyse | `Erreur d'inattention cause échange au casque...` | texte libre | Causes présumées de l'événement |
| `analysedescausessuppecc` | Analyse | `Facteur humain : Erreur d'inattention de l'agent...` | texte libre | Analyse des causes (champ ECCAIRS) |
| `contributionatm` | Impact ATM | `Aucune implication` | référentiel | Contribution du contrôle aérien (ATM) |
| `effetsurleserviceatm` | Impact ATM | `Aucun effet` | référentiel | Effet de l'événement sur le service ATM |
| `organisationsinformees` | Parties prenantes | `Exploitant de l'aérodrome` | liste référentiel | Organisations informées de l'événement |
| `notifiant` | Parties prenantes | `ACRIV` | référentiel | Entité ayant émis la notification |

## Les pépites

`graviteecc` (criticité) et `securitetypeevnt0/1/2` (typologie) sont les plus à
forte valeur : ils permettraient de **filtrer et trier** les incidents par gravité
et par catégorie — exactement la taxonomie volontairement reportée en V1.

## Décision à prendre

La vraie question reste : **la production va-t-elle livrer ces champs un jour ?**
Tant que non, inutile de les ajouter au schéma. Si oui, leur intégration sera
quasi gratuite (ce sont des référentiels).

---
*Généré depuis `scripts/diff_champs_samples.py` (diff filtré sur le type `q_incident_securite`).*
