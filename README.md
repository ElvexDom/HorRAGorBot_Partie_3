# 🩸 HorRAGor BOT — Partie 3

Agent conversationnel spécialisé dans l'univers de l'horreur (cinéma, littérature, jeux vidéo), porté sur une architecture **multi-agent LangGraph** (Groq LLM, FAISS, Supabase), monitorée avec **Langfuse**.

La Partie 2 reposait sur un agent ReAct monolithique (`llm_groq.py`, une seule boucle tool-use). La Partie 3 casse ce modèle centralisé : trois agents ultra-spécialisés se passent le relais dans un `StateGraph`, sans nœud "chef de projet" central.

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
                   │ agent_graph.ainvoke()      ──► Langfuse (traces, coût, latence)
                   ▼
┌──────────────────────────────────────────────────────────────┐
│   graph/pipeline.py — StateGraph (peer to peer, sans manager) │
│                                                                │
│   ┌────────────┐   sufficient?   ┌───────────┐   ┌──────────┐│
│   │ rag_node   │────router.py───►│ narration ││   │          ││
│   │ (Chercheur │       │         │  _node    ││   │          ││
│   │  Local)    │    insuffisant  │ (Écrivain ││   │          ││
│   │            │       ▼         │  Gothique)├┤──►│  Réponse ││
│   │ tools/     │  ┌────────────┐ │  aucun    ││   │          ││
│   │ rag_tool.py│  │scraper_node│─►  tool     ││   │          ││
│   └─────┬──────┘  │(Enquêteur  │ └───────────┘│   │          ││
│         │         │ du Web)    │              │   │          ││
│         │         │tools/      │              │   │          ││
│         │         │scraper_tool│              │   │          ││
│         │         └─────┬──────┘              │   └──────────┘│
└─────────┼───────────────┼─────────────────────┼───────────────┘
          ▼               ▼                     │  Le Juge (graph/judge.py)
┌────────────┐  ┌──────────────┐                │  post-traitement : évalue +
│ FAISS RAM  │  │  Supabase    │        Wikipedia│  retry (max 2, seuil 0.65)
│ 1179 films │  │  (PostgreSQL)│        (REST)   │
│ (synopsis) │  │ film/genre/  │                 │
│            │  │ evaluation   │                 │
└────────────┘  └──────────────┘
```

---

## Stack technique

| Composant | Technologie |
|-----------|-------------|
| Orchestration multi-agent | LangGraph — `StateGraph` (`graph/`) |
| LLM | Groq — `llama-3.3-70b-versatile` via `langchain-groq` |
| Monitoring agent | Langfuse (traces, coût, latence par nœud, arbre de décision) |
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
- Docker (optionnel — pour Langfuse en local, voir plus bas)

---

## Installation

```bash
git clone https://github.com/ElvexDom/HorRAGorBot_Partie_3.git
cd HorRAGorBot_Partie_3
uv sync
```

---

## Configuration

Crée un fichier `.env` à la racine (copie `.env.example`) :

```env
# Connexion PostgreSQL (le code utilise SUPABASE_DB_URL en priorité, sinon DATABASE_URL)
SUPABASE_DB_URL=postgresql://<user>:<password>@<host>:5432/<database>

# LLM Groq
GROQ_API_KEY=<your-groq-api-key>

# Monitoring Langfuse (optionnel — laisser vide pour désactiver le monitoring)
LANGFUSE_PUBLIC_KEY=<pk-lf-...>
LANGFUSE_SECRET_KEY=<sk-lf-...>
LANGFUSE_HOST=http://localhost:3000
```

> La clé Groq est disponible sur [console.groq.com](https://console.groq.com/) → **API Keys** → **Create API Key**

> ⚠️ **Supabase / connexion directe IPv6-only** : la chaîne de connexion directe
> (`db.<ref>.supabase.co:5432`) n'a qu'un enregistrement DNS **AAAA (IPv6)**.
> Sans sortie IPv6 fonctionnelle sur ton réseau (cas fréquent), la connexion
> échoue avec `could not translate host name`. Utilise plutôt le
> **connection pooler** (IPv4) : Dashboard Supabase → *Project Settings →
> Database → Connection pooling*, format
> `postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres`.

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

**Terminal 3 (optionnel) — Langfuse en local**
```bash
git clone https://github.com/langfuse/langfuse.git
cd langfuse
docker compose up -d
# → http://localhost:3000 — crée un compte (email factice OK en local),
#   crée un projet, récupère les clés pk-lf-.../sk-lf-... pour le .env
```

---

## Les trois agents

Aucun nœud "chef de projet" central : les agents travaillent en chaîne directe,
sans jamais savoir qui a travaillé avant eux ni qui prendra la suite.

| Agent | Fichier | Rôle | Outils |
|-------|---------|------|--------|
| **RAG** — Le Chercheur Local | `graph/nodes.py::rag_node` | Premier point de contact : interroge FAISS + Supabase, corrige les approximations de l'utilisateur | `search_horror_movies`, `query_movie_metadata`, `similar_movies`, `movie_age`, `survival_sim` (`tools/rag_tool.py`) |
| **Scraper** — L'Enquêteur du Web | `graph/nodes.py::scraper_node` | Déclenché uniquement si le routeur juge le savoir local insuffisant : va chercher les détails manquants sur Wikipedia | `detailed_synopsis` (`tools/scraper_tool.py`) |
| **Narration** — L'Écrivain Gothique | `graph/nodes.py::narration_node` | Isolé de toute la plomberie technique (aucun tool, aucun log brut) : ne reçoit que la synthèse des données pour l'habiller en prose gothique | *(aucun)* |

### Le routeur (`graph/router.py`)

`should_scrape_or_narrate(state)` est une fonction pure, testable sans lancer tout le pipeline :

```python
def should_scrape_or_narrate(state: AgentState) -> str:
    if state.get("rag_sufficient"):
        return "narration"
    return "scraper"
```

`rag_sufficient` est posé par `rag_node` selon une heuristique déterministe (absence de marqueurs
d'échec comme « Aucun film trouvé », « introuvable »…).

### Exemples de questions

```
"Parle-moi de The Shining"               → rag_node (query_movie_metadata) → narration directe
"Recommande un film de possession"       → rag_node (search_horror_movies) → narration directe
"Anecdotes sur un film obscur et rare"   → rag_node insuffisant → scraper_node (Wikipedia) → narration
"Je survivrais dans Scream ?"            → rag_node (survival_sim) → narration directe
```

---

## Monitoring — Langfuse

Chaque appel à `agent_graph.ainvoke()` passe un `CallbackHandler` Langfuse (`langfuse.langchain`)
si `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` sont configurées ; sinon le graphe tourne sans
monitoring (pas d'erreur bloquante — Langfuse est optionnel en local).

Une fois lancé (voir *Lancement* ci-dessus) et une conversation testée, va sur
`http://localhost:3000` pour observer :

- le coût et la consommation de tokens par appel LLM,
- la latence exacte de chaque nœud (`rag`, `scraper`, `narration`),
- le tracé complet des appels d'outils,
- l'arborescence de décision du routeur (`rag` → `scraper` ou `narration` directement).

---

## Le Juge (évaluateur de réponse)

Après la sortie du graphe (`graph/judge.py`), un second appel LLM — **Le Juge** — évalue la
réponse finale de l'Agent de Narration :

- Détecte les hallucinations et incohérences avec les données réelles
- Fournit un score de confiance (0.0 → 1.0)
- Déclenche un **retry automatique** (max 2 fois) si la confiance est < 0.65

Le verdict s'affiche en temps réel dans le **bandeau bas** de l'interface Streamlit :

| Icône | Label | Condition |
|-------|-------|-----------|
| 🩸 | LE JUGE A APPROUVÉ | is_valid=True et confiance ≥ 80 % |
| ⚠️ | LE JUGE EST MITIGÉ | is_valid=True et confiance < 80 % |
| 💀 | LE JUGE CONDAMNE | is_valid=False |

Le bandeau affiche aussi les **agents/outils traversés** (`⚙ query_movie_metadata › detailed_synopsis › narration-llm`, etc.).
Les noms d'outils n'apparaissent jamais dans le corps de la réponse : ils sont réservés au
bandeau du Juge pour garder les messages naturels.

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
  "answer": "Dans les profondeurs d'un hiver sans fin... [prose gothique de l'Agent de Narration]",
  "tools_used": ["query_movie_metadata", "narration-llm"],
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
HorRAGorBot_Partie_3/
├── frontend/
│   ├── app.py                         # Interface Streamlit (thème dark horror animé)
│   └── .streamlit/config.toml         # Config Streamlit
├── graph/
│   ├── state.py                       # AgentState — State de confiance partagé
│   ├── nodes.py                       # rag_node, scraper_node, narration_node
│   ├── router.py                      # should_scrape_or_narrate (arête conditionnelle)
│   ├── pipeline.py                    # StateGraph — câblage + app = workflow.compile()
│   ├── judge.py                       # Le Juge — évaluation qualité post-graphe
│   └── llm.py                         # Client ChatGroq partagé par les nœuds
├── tools/
│   ├── __init__.py
│   ├── rag_tool.py                    # Retriever FAISS + tools de l'Agent RAG
│   ├── scraper_tool.py                # Tool Wikipedia de l'Agent Scraper
│   ├── query_movie_metadata.py        # Métadonnées SQL Supabase
│   ├── find_similar_horror_movies.py  # Similarité FAISS + Supabase
│   ├── calculate_movie_age.py         # Calcul âge film (date en FR)
│   ├── scrape_detailed_synopsis.py    # Scraping Wikipedia (REST)
│   └── horror_survival_simulator.py   # Simulation de survie ludique
├── utils/
│   └── build_faiss_index.py           # Construction de l'index FAISS
├── data/
│   ├── faiss.index                    # Index vectoriel (1179 films)
│   └── id_map.npy                     # Mapping index → ID film en base
├── main_api.py                        # API FastAPI — branche le graphe + Langfuse + Le Juge
├── .env.example                       # Template de configuration
└── pyproject.toml                     # Dépendances (uv)
```

---

## Dépannage

| Erreur | Solution |
|--------|----------|
| `GROQ_API_KEY non configurée` | Vérifie le fichier `.env` |
| `could not translate host name "db.*.supabase.co"` | Connexion directe IPv6-only sans route IPv6 — passe par le **connection pooler** Supabase (voir *Configuration*) |
| `SUPABASE_DB_URL et DATABASE_URL absentes` | Renseigne au moins l'une des deux dans `.env` |
| L'agent répond "base inaccessible" | Supabase est en pause (Free Tier après 7 j) — réactive le projet sur le dashboard Supabase (voir logs API : `psycopg2.OperationalError`) |
| `groq.BadRequestError: tool_use_failed` | Le modèle a sérialisé un argument dans le mauvais type (ex. `k` en string) — `rag_node`/`scraper_node` l'attrapent et dégradent proprement (voir logs `[RAG] Appel LLM rejeté par Groq`) |
| `ModuleNotFoundError` | Lance `uv sync` |
| `Connection refused` sur /chat | Vérifie que `uvicorn main_api:app` tourne |
| Monitoring Langfuse absent des traces | Vérifie `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` dans `.env` et que `docker compose up -d` tourne sur le repo Langfuse |
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

## Parties précédentes

- **Partie 1** — pipeline de données (ingestion TMDB, Kaggle, IMDB, Rotten Tomatoes, PySpark) : [HorRAGor BOT Partie 1.pdf](HorRAGor%20BOT%20Partie%201.pdf) et [old_README.md](old_README.md).
- **Partie 2** — agent ReAct monolithique (`llm_groq.py`, remplacé en Partie 3 par le graphe multi-agent) : [HorRAGor BOT Partie 2.pdf](HorRAGor%20BOT%20Partie%202.pdf).
