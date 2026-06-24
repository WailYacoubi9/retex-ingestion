# Guide — schéma d'un module

Ce fichier `*.schema.yaml` décrit chaque champ d'un type de données.
Il est **déjà pré-rempli**. Voici ce qu'on attend de toi.

## Ta tâche

Ctrl+F sur `⚠️ à confirmer (métier)` et remplace chaque marqueur. Deux types :

**1. `libelle_formulaire`** → le nom du champ tel qu'affiché dans le formulaire
intra'know (souvent différent du nom technique du JSON).

```yaml
  - cle: detail
    nom_json: detail_nc                      # nom technique (ne pas toucher)
    libelle_formulaire: "Description"        # ← tu mets le nom vu à l'écran
```

**2. `valeurs_possibles`** → la signification de chaque code.

```yaml
valeurs_possibles:
  1: "Ouvert"        # ← le vrai sens, jamais inventé
  5: "Clôturé"
```

## 3 règles

1. **N'invente pas** un sens de code. Si tu n'es pas sûre, laisse le marqueur.
2. Ne touche **jamais** à `cle:` ni à la zone marquée 🔴.
3. `type:` se choisit dans : `texte, entier, decimal, booleen, date, horodatage, heure`.

## Si tu veux aussi modifier un champ

- **Renommer** → change `libelle:`, garde l'ancien dans `anciens_noms:`. Ne touche pas à `cle:`.
- **Ajouter** → copie un bloc et adapte-le.
- **Changer un `type:`** → demande un développeur (ça impacte les données existantes).
