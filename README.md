# 🩸 HorRAGor BOT — Partie 2

Agent conversationnel spécialisé dans l'univers de l'horreur (cinéma, littérature, jeux vidéo), basé sur une architecture **ReAct** avec Groq LLM, FAISS et Supabase.

---

## Architecture

```
┌──────────────────────────────────────┐
│   Streamlit  (Front-End)             │
│   frontend/app.py                    │
│   • Thème dark horror animé          │
│     (zombies, chauves-souris,        │
│      château, lune, brouillard)      │
│   • Zombies interactifs : drag &     │
│     throw, plateformes (nuages,      │
│      créneaux du château, orbite     │
│      autour de la lune)              │
│   • Verdict du Juge dans le          │
│     bandeau bas (🩸 / ⚠️ / 💀)       │
└──────────────────┬───────────────────┘
                   │ HTTP POST /chat
                   ▼
┌──────────────────────────────────────┐
│   FastAPI    (Back-End)              │
│   main_api.py                        │
│   • /chat  /health  /info            │
└──────────────────┬───────────────────┘
                   │ generate_response()
                   ▼
┌──────────────────────────────────────┐
│   Groq LLM  llama-3.3-70b            │
│   llm_groq.py                        │
│   • Tool-use (6 outils)              │
│   • Le Juge : évaluateur + retry     │
└──────┬───────────┬───────────────────┘
       │ tool calls│
       ▼           ▼
┌────────────┐  ┌──────────────────────┐
│ FAISS RAM  │  │ Supabase (PostgreSQL) │
│ 1179 films │  │ film / evaluation /  │
│ (synopsis) │  │ genre / analyse_spark│
└────────────┘  └──────────────────────┘
```

---

## Stack technique

| Composant | Technologie |
|-----------|-------------|
| LLM | Groq — `llama-3.3-70b-versatile` |
| Back-End | FastAPI + Uvicorn (async) |
| Front-End | Streamlit — thème dark horror custom |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` |
| Mémoire vectorielle | FAISS (index en RAM) |
| Base de données | Supabase (PostgreSQL) via psycopg2 |
| Dépendances | `uv` |

---

## Prérequis

- Python 3.10+
- `uv` installé
- Compte [Groq](https://console.groq.com/) (gratuit)
- Accès Supabase (hérité Partie 1)

---

## Installation

```bash
git clone https://github.com/timdazayous/HorRAGorBot_Part_2.git
cd HorRAGorBot_Part_2
uv sync
```

---

## Configuration

Crée un fichier `.env` à la racine (copie `.env.example`) :

```env
# LLM
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxx

# Base de données Supabase
# L'une OU l'autre suffit : le code utilise SUPABASE_DB_URL en priorité,
# sinon DATABASE_URL en fallback.
DATABASE_URL=postgresql://postgres:PASSWORD@db.XXXX.supabase.co:5432/postgres
SUPABASE_DB_URL=postgresql://postgres:PASSWORD@db.XXXX.supabase.co:5432/postgres

# Optionnel — configuration du serveur
API_HOST=0.0.0.0
API_PORT=8000
LLM_MODEL=llama-3.3-70b-versatile
LLM_TEMPERATURE=0.7
LLM_MAX_TOKENS=2048
```

> La clé Groq est disponible sur [console.groq.com](https://console.groq.com/) → **API Keys** → **Create API Key**

---

## Lancement

**Terminal 1 — API FastAPI**
```bash
uvicorn main_api:app --reload
# → http://localhost:8000
# → Swagger : http://localhost:8000/docs
```

**Terminal 2 — Interface Streamlit**
```bash
cd frontend
streamlit run app.py
# → http://localhost:8501
```

---

## Outils de l'agent (Tools)

| # | Nom interne | Déclencheur LLM |
|---|-------------|-----------------|
| 1 | `query_movie_metadata` | Question sur un film précis ("parle-moi de X", "infos sur X") |
| 2 | `similar_movies` | Demande de films similaires à un titre |
| 3 | `search_horror_movies` | Recherche sémantique libre (requête FAISS) |
| 4 | `movie_age` | Âge d'un film, ancienneté, "est-ce récent ?" |
| 5 | `detailed_synopsis` | Détails approfondis, anecdotes, contexte de production |
| 6 | `survival_sim` | Simulation de survie dans un film ("je survivrais dans X ?") |

### Exemples de questions

```
"Parle-moi de The Shining"               → query_movie_metadata
"Films similaires à Hereditary"          → similar_movies
"Recommande un film de possession"       → search_horror_movies
"Quel âge a Halloween ?"                 → movie_age
"Donne-moi des anecdotes sur Get Out"    → detailed_synopsis
"Je survivrais dans Scream ?"            → survival_sim
```

---

## Le Juge (évaluateur de réponse)

Après chaque réponse de l'agent, un second appel LLM — **Le Juge** — évalue la qualité de la réponse :

- Détecte les hallucinations et incohérences avec les données réelles
- Fournit un score de confiance (0.0 → 1.0)
- Déclenche un **retry automatique** (max 2 fois) si la confiance est < 0.65

Le verdict s'affiche en temps réel dans le **bandeau bas** de l'interface Streamlit :

| Icône | Label | Condition |
|-------|-------|-----------|
| 🩸 | LE JUGE A APPROUVÉ | is_valid=True et confiance ≥ 80 % |
| ⚠️ | LE JUGE EST MITIGÉ | is_valid=True et confiance < 80 % |
| 💀 | LE JUGE CONDAMNE | is_valid=False |

Le bandeau affiche aussi les **outils utilisés** (`⚙ search_horror_movies`, etc.).
Les noms d'outils n'apparaissent jamais dans le corps de la réponse de l'agent :
ils sont réservés au bandeau du Juge pour garder les messages naturels.

---

## Interface interactive (thème dark horror)

L'arrière-plan animé de Streamlit est entièrement injecté en JS/SVG (canvas + overlay).
Les zombies sont **manipulables à la souris** :

- **Drag & throw** — attrape un zombie, déplace-le et relâche pour le lancer ;
  une physique de gravité le fait retomber jusqu'au sol en arc.
- **Plateformes** — un zombie lancé peut atterrir et marcher sur :
  - les **nuages** dérivants (il en tombe s'il dépasse le bord),
  - les **créneaux du château** (5 plateformes statiques),
  - la **lune**, autour de laquelle il marche en orbite, y compris tête en bas.

> Les zombies marchent **au premier plan** (z-index élevé), devant le bandeau
> d'input et le verdict du Juge, sans jamais bloquer la saisie
> (couche `pointer-events:none`, sauf sur le corps d'un zombie pour le drag).

---

## Endpoints API

### `GET /health`
```bash
curl http://localhost:8000/health
```

### `POST /chat`
```bash
curl -X POST "http://localhost:8000/chat" \
  -H "Content-Type: application/json" \
  -d '{"question": "Parle-moi de The Shining"}'
```

Réponse :
```json
{
  "answer": "Titre : The Shining (The Shining)\nAnnée : 1980\n...\n--------\nUn chef-d'œuvre de Kubrick...",
  "tools_used": ["query_movie_metadata", "groq-llm"],
  "judge_verdict": {
    "is_valid": true,
    "confidence": 0.95,
    "reasoning": "Réponse cohérente avec les données de la base."
  },
  "conversation_id": "conv_anonymous"
}
```

### `GET /info`
```bash
curl http://localhost:8000/info
```

---

## Structure du projet

```
HorRAGorBot_Part_2/
├── frontend/
│   ├── app.py                         # Interface Streamlit (thème dark horror animé)
│   └── .streamlit/config.toml         # Config Streamlit
├── tools/
│   ├── __init__.py
│   ├── query_movie_metadata.py        # Tool 1 — métadonnées SQL Supabase
│   ├── find_similar_horror_movies.py  # Tool 2 — similarité FAISS + Supabase
│   ├── calculate_movie_age.py         # Tool 4 — calcul âge film (date en FR)
│   ├── scrape_detailed_synopsis.py    # Tool 5 — scraping Wikipedia
│   └── horror_survival_simulator.py   # Tool 6 — simulation survie ludique
├── utils/
│   └── build_faiss_index.py           # Construction de l'index FAISS
├── data/
│   ├── faiss.index                    # Index vectoriel (1179 films)
│   └── id_map.npy                     # Mapping index → ID film en base
├── main_api.py                        # API FastAPI
├── llm_groq.py                        # Client Groq + dispatch tools + Le Juge
├── .env.example                       # Template de configuration
└── pyproject.toml                     # Dépendances (uv)
```

---

## Dépannage

| Erreur | Solution |
|--------|----------|
| `GROQ_API_KEY non configurée` | Vérifie le fichier `.env` |
| `SUPABASE_DB_URL et DATABASE_URL absentes` | Renseigne au moins `DATABASE_URL` dans `.env` |
| L'agent répond "base inaccessible" | Supabase est en pause (Free Tier après 7 j) — réactive le projet sur le dashboard Supabase (voir logs API : `psycopg2.OperationalError`) |
| L'agent répond "aucun film trouvé" alors que la base tourne | Vérifie le schéma Hub & Spoke : genres via `film_genre`/`genre`, notes via `evaluation` (voir logs API pour l'erreur SQL exacte) |
| `ModuleNotFoundError` | Lance `uv sync` |
| `Connection refused` sur /chat | Vérifie que `uvicorn main_api:app` tourne |
| HuggingFace télécharge le modèle | Normal au 1er lancement (~91 Mo, mis en cache ensuite) |
| Index FAISS manquant | Lance `python utils/build_faiss_index.py` |

---

## Branches de développement

| Branche | Développeur |
|---------|-------------|
| `main` | Production |
| `dev-tim` | Tim — Front-End Streamlit |
| `dev-nicolas` | Nicolas — FAISS + similarité |
| `dev_julie` | Julie — API FastAPI + Tools |

---

## Partie 1

Le pipeline de données (ingestion TMDB, Kaggle, IMDB, Rotten Tomatoes, PySpark) est documenté dans [HorRAGor BOT Partie 1.pdf](HorRAGor%20BOT%20Partie%201.pdf) et dans [old_README.md](old_README.md).
