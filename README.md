# retex-ingestion

Pipeline de chargement du projet RETEX (tickets, projets, collaborateurs,
incidents, DGAC). **Client** du `retex-backbone` : écrit dans Neo4j/Qdrant et
utilise Ollama. Se lance à la demande (batch), séparément de l'app.

## Prérequis
- `retex-backbone` lancé (neo4j/qdrant/ollama accessibles).
- Modèles Ollama pull : `qwen2.5:7b`, `bge-m3`.

## Installation
```bash
python3 -m venv .venv && source .venv/bin/activate   # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt
cp .env.example .env        # ajuster si besoin
```

## Données
Le dossier `data/` est **gitignoré** (données confidentielles). Y placer les
fichiers d'entrée. En particulier `data/personnes_mapping.csv` (login;nom) est
le chemin par défaut d'`ingest_personnes.py`.

## Lancer (ordre)
```bash
# Tickets (--skip-llm pour un test rapide sans GPU ; --limit N pour un échantillon)
python scripts/ingest_tickets.py --input <tickets.json> --csv <ticket.csv> [--skip-existing]
# Liens hiérarchie parent/enfant
python scripts/link_tickets_hierarchie.py --input <tickets.json>
# Collaborateurs (mapping login -> nom)
python scripts/ingest_personnes.py
# Projets (+ clients, hiérarchie, liens par titre)
python scripts/ingest_projets.py --input <projet_client.csv> --only-referenced
```

## Connexion au backbone
Par défaut les scripts visent `localhost:7687/6333/11434` (backbone local, ports
exposés). Pour pointer ailleurs, exporter les variables de `.env`.
