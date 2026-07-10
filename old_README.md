# HorRAGor BOT — Partie 1 : Pipeline d'Ingestion de Données

> **HorRAGor** est un agent conversationnel spécialisé dans l'horreur (cinéma, littérature, jeux vidéo).
> Cette Partie 1 construit la **base de connaissances** qui alimentera le bot — sans données solides, un chatbot hallucine.

---

## C'est quoi ce projet ?

Un **pipeline de données** qui collecte, nettoie et fusionne des informations sur **1 179 films d'horreur** provenant de 5 sources différentes, puis les stocke dans une base de données cloud (Supabase/PostgreSQL).

Ce travail correspond au **Bloc E1** de la formation DEV IA — il valide les compétences en ingestion de données massives, en scraping web, en traitement Big Data et en modélisation de bases de données.

### Pourquoi 5 sources ?

Aucune source unique ne contient tout. TMDB donne les métadonnées officielles, Rotten Tomatoes les critiques, Kaggle des données financières, IMDB les notes des spectateurs, et PySpark fait de l'analyse textuelle sur les synopsis.

---

## Statistiques réelles du projet (base Supabase)

> Données récupérées après le pipeline complet (mai 2026)

### Volume de données

| Métrique | Valeur |
|----------|--------|
| **Films d'horreur indexés** | **1 179** |
| Films avec synopsis (overview) | 1 092 / 1 179 (93%) |
| Films avec ID IMDB | 1 171 / 1 179 (99%) |
| Films avec scores Rotten Tomatoes | 757 / 1 179 (64%) |
| Films avec analyse textuelle Spark | 922 / 1 179 (78%) |

### Scores moyens (par source)

| Source | Score moyen | Échelle |
|--------|------------|---------|
| Rotten Tomatoes (Tomatometer) | 58.3 | /100 |
| IMDB (vote communauté) | 6.04 | /10 |
| TMDB (vote utilisateurs) | 6.18 | /10 |

### État de la base de données (6 tables)

| Table | Rôle | Enregistrements |
|-------|------|-----------------|
| `film` | Films dédupliqués — table centrale | **1 179** |
| `genre` | Genres uniques référencés | 18 |
| `film_genre` | Associations film ↔ genre | 3 147 |
| `evaluation` | Scores de toutes les sources | **3 319** |
| `analyse_spark` | Analyses textuelles NLP | 922 |
| `source` | Traçabilité MDM (quelle source a fourni quoi) | 2 535 |

### Top genres dans le corpus

| Genre | Nb films |
|-------|----------|
| Horror | 1 178 |
| Thriller | 583 |
| Mystery | 284 |
| Drama | 200 |
| Science Fiction | 200 |
| Action | 174 |

---

## Architecture du pipeline

```
╔══════════════════════════════════════════════════════════════╗
║                     5 SOURCES DE DONNÉES                     ║
╠══════════╦══════════════╦═══════════╦══════════╦═════════════╣
║ TMDB API ║Rotten Tomatoes║ Kaggle CSV║IMDB SQLite║  PySpark   ║
║(REST API)║  (Selenium)  ║  (Polars) ║ (SQLite) ║(Analyse NLP)║
╚════╤═════╩══════╤═══════╩═════╤═════╩═════╤════╩══════╤══════╝
     │            │             │           │           │
     ▼            ▼             ▼           ▼           ▼
╔════════════════════════════════════════════════════════════╗
║              PIPELINE MDM  (main.py)                       ║
║                                                            ║
║  1. TMDB   ──────────────────────────────▶ Base maîtresse  ║
║  2. RT     ──── enrichit ───────────────▶ + scores RT      ║
║  3. Kaggle ──── enrichit ───────────────▶ + synopsis/budget║
║  4. IMDB   ──── enrichit ───────────────▶ + IMDB ID/notes  ║
║  5. Spark  ──── enrichit ───────────────▶ + analyse texte  ║
╚══════════════════════════╤═════════════════════════════════╝
                           │
           ┌───────────────┴───────────────┐
           ▼                               ▼
  ┌─────────────────┐           ┌──────────────────────┐
  │ horragor_gold   │           │  Supabase (PostgreSQL)│
  │   .json         │           │  6 tables, ~9 000     │
  │ (1 179 films)   │           │  enregistrements      │
  └─────────────────┘           └──────────────────────┘
```

**Principe MDM (Master Data Management) :** TMDB est la source de référence. Les autres sources **enrichissent** uniquement les champs manquants, elles ne créent jamais de nouveaux films ni n'écrasent les données TMDB.

---

## Les 5 sources de données

### Source 1 — API TMDB (source maîtresse)
- **Technologie :** API REST (requests)
- **Ce qu'on récupère :** titre, titre original, date de sortie, synopsis, popularité, genres, poster
- **Volume :** 1 179 films d'horreur (triés par popularité)
- **Pourquoi c'est la source maîtresse :** TMDB fournit les identifiants officiels (`tmdb_id`, `imdb_id`) qui servent de clé de jointure avec toutes les autres sources

### Source 2 — Web Scraping Rotten Tomatoes (Selenium)
- **Technologie :** Selenium + Chrome en mode invisible (headless), webdriver-manager
- **Ce qu'on récupère :** tomatometer (% critiques positifs), audience score, consensus des critiques
- **Volume :** 757 films enrichis sur 1 179
- **Défi technique :** RT utilise des Web Components JavaScript — scraping asynchrone, validation du titre par similarité Jaccard pour éviter les faux positifs, fallback sur le titre original anglais si le titre français n'est pas trouvé

### Source 3 — Fichiers Kaggle (Polars)
- **Technologie :** Polars (alternative rapide à Pandas pour les gros volumes)
- **Fichier :** `horror_movies.csv` (~14 MB, ~35 000 entrées)
- **Ce qu'on récupère :** synopsis alternatifs, budget, recettes au box-office
- **Nettoyage :** suppression des doublons `(titre + date)`, nettoyage balises HTML

### Source 4 — Base de données SQLite IMDB
- **Technologie :** SQLite + SQLAlchemy
- **Fichier :** `imdb.db` (~2 GB, construit depuis les fichiers TSV officiels IMDB)
- **Requête :** jointure `title_basics ⋈ title_ratings` filtrée sur Horror avec minimum 1 000 votes
- **Ce qu'on récupère :** identifiant IMDB (`tconst`), note moyenne, nombre de votes
- **Filtre qualité :** seuil `numVotes >= 1 000` pour exclure les films sans audience

### Source 5 — PySpark (analyse textuelle)
- **Technologie :** PySpark (mode local) — fallback Python pur sur Windows
- **Ce qu'on produit :**
  - `detected_language` : langue du synopsis (FR/EN/autre)
  - `overview_word_count` : nombre de mots
  - `horror_keywords` : mots-clés horreur extraits (50+ mots EN + FR)
  - `richness_score` : score de richesse du synopsis (0-100)

---

## Stratégie MDM — Comment on fusionne les sources

### Priorité des sources (la plus haute gagne)

| Priorité | Source | Rôle |
|----------|--------|------|
| 1 | **TMDB** | Source maîtresse — identifiants et titres officiels |
| 2 | Rotten Tomatoes | Scores critiques et consensus |
| 3 | Kaggle | Synopsis et données financières |
| 4 | IMDB | Identifiant IMDB et notation communauté |
| 5 | Spark | Analyses textuelles |

### Matching en 3 niveaux (réconciliation)

```
Niveau 1 : ID TMDB exact          ← O(1), le plus fiable
    │
    └──▶ Niveau 2 : ID IMDB exact  ← O(1), très fiable
              │
              └──▶ Niveau 3 : Titre + Année (Levenshtein ≤ 2)  ← fuzzy matching
```

### Règle fondamentale

Un champ déjà rempli par TMDB **n'est jamais écrasé**. On ne remplit que les champs vides :

```python
# Exemple : si TMDB n'a pas de synopsis, on prend celui de Kaggle
if not base.overview and kaggle_movie.overview:
    base.overview = kaggle_movie.overview
```

---

## Modélisation de la base de données

Le schéma complet (MCD / MLD / MPD avec diagrammes) est dans [Merise.md](Merise.md).

**Architecture Hub & Spoke :**

```
          GENRE ─────┐
                     │ N-N
    SOURCE ──────▶  FILM  ◀────── EVALUATION
                     │           (TMDB / RT / IMDB)
    ANALYSE_SPARK ───┘
```

- **FILM** (Hub) : table centrale, clé `tmdb_id`
- **EVALUATION** : tous les scores dans une seule table (évite les colonnes vides)
- **ANALYSE_SPARK** : résultats NLP, relation 1-1 avec FILM
- **SOURCE** : traçabilité MDM — trace quelle source a contribué quels champs
- **GENRE** / **FILM_GENRE** : relation N-N (un film peut avoir plusieurs genres)

---

## Stack technique

| Composant | Technologie | Version |
|-----------|-------------|---------|
| Langage | Python | 3.10+ |
| API REST | requests | 2.31 |
| Scraping | Selenium + webdriver-manager | 4.18 |
| Dataframes | Polars | ≥1.40 |
| Big Data | PySpark | ≥4.1 |
| ORM | SQLAlchemy | 2.0 |
| Driver DB | psycopg2-binary | 2.9 |
| Validation | Pydantic + pydantic-settings | 2.x |
| Base de données | **Supabase** (PostgreSQL hébergé) | — |
| Fuzzy matching | Levenshtein (implémentation native) | — |

---

## Installation

### Prérequis

- Python 3.10 ou supérieur
- Google Chrome installé (pour Selenium)
- Compte [TMDB](https://www.themoviedb.org/) — clé API gratuite
- Compte [Supabase](https://supabase.com/) — gratuit pour ce volume

### Étapes

```bash
# 1. Cloner le projet
git clone <url-du-repo>
cd "HorRAGor Bot"

# 2. Installer les dépendances (avec uv, recommandé)
uv sync

# OU avec pip
pip install -r requirements.txt
```

---

## Configuration

Créer un fichier `.env` à la racine :

```env
# Clé API TMDB (obligatoire)
TMDB_API_KEY=votre_cle_tmdb_ici

# URL de connexion Supabase — format PostgreSQL
DATABASE_URL=postgresql://postgres:<mot_de_passe>@<host>:5432/postgres
```

### Fichiers de données requis dans `data/input/`

| Fichier | Source | Taille |
|---------|--------|--------|
| `horror_movies.csv` | [Kaggle Horror Movies Dataset](https://www.kaggle.com/datasets/PromptCloudHQ/imdb-horror-movie-dataset) | ~14 MB |
| `title.basics.tsv` | [IMDB Datasets](https://datasets.imdbws.com/) | ~1 GB |
| `title.ratings.tsv` | [IMDB Datasets](https://datasets.imdbws.com/) | ~30 MB |

> **Construire `imdb.db`** (une seule fois, ~10 min) :
> ```bash
> python create_imdb_db.py
> ```

---

## Lancer le pipeline

### Exécution standard

```bash
python main.py
```

Par défaut : 50 pages TMDB (~1 000 films), sans scraping RT en temps réel, sauvegarde JSON + Supabase.

### Options avancées

```python
from main import run_pipeline

movies = run_pipeline(
    tmdb_pages=25,       # 25 pages × 20 films = ~500 films
    scrape_rt=False,     # True pour activer le scraping RT (lent : ~5 sec/film)
    rt_max_movies=50,    # Nombre de films à scraper sur RT si scrape_rt=True
    save_output=True,    # Sauvegarde le JSON Gold Layer
    push_to_db=True,     # Envoie vers Supabase
)
```

### Enrichissement RT en masse (script dédié)

Pour scraper Rotten Tomatoes sur toute la base de manière incrémentale (reprend automatiquement là où il s'est arrêté) :

```bash
# Scraper 500 films avec 2.5 secondes entre chaque requête
python enrich_rt.py --limit 500 --delay 2.5
```

Le script gère automatiquement :
- La reprise après interruption (ignore les films déjà enrichis en DB)
- La reconnexion Supabase si la session est coupée (timeout)
- Les commits toutes les 10 réussites

---

## Sortie — Gold Layer

### Fichier JSON `data/output/horragor_gold.json`

Chaque film est représenté comme un objet JSON enrichi :

```json
{
  "title": "Hereditary",
  "original_title": "Hereditary",
  "release_date": "2018-06-07",
  "tmdb_id": 493922,
  "imdb_id": "tt7784604",
  "overview": "When Ellen, the matriarch of the Graham family, passes away...",
  "vote_average": 7.3,
  "popularity": 47.2,
  "genres": ["Horror", "Mystery", "Thriller"],
  "source_system": "HorRAGor-Pipeline/TMDB",
  "rt_tomatometer": 89,
  "rt_audience_score": 66,
  "rt_critics_consensus": "Hereditary subverts family drama conventions...",
  "horror_keywords": "[\"death\", \"dark\", \"cult\", \"ritual\"]",
  "detected_language": "en",
  "overview_word_count": 52
}
```

---

## Structure du projet

```
HorRAGor Bot/
│
├── main.py                    # Point d'entrée — orchestre tout le pipeline
├── enrich_rt.py               # Script dédié à l'enrichissement RT (standalone)
├── create_imdb_db.py          # Construit imdb.db depuis les TSV IMDB (une fois)
├── test_pipeline.py           # Tests d'intégration
│
├── app/
│   ├── config/
│   │   └── config.py          # Paramètres (clés API, chemins, DB) via .env
│   ├── models/
│   │   ├── schema.py          # Modèles Pydantic (MovieGold, RottenTomatoesData)
│   │   └── database.py        # Modèles SQLAlchemy ORM (Film, Evaluation, ...)
│   ├── services/
│   │   ├── tmdb_api.py        # Client API TMDB
│   │   ├── kaggle_service.py  # Lecture CSV Kaggle avec Polars
│   │   ├── imdb_service.py    # Extraction IMDB depuis SQLite
│   │   ├── spark_service.py   # Analyses textuelles PySpark / Python pur
│   │   └── db_service.py      # Persistance vers Supabase (PostgreSQL)
│   ├── scrapers/
│   │   └── rotten_tomatoes.py # Scraper Selenium avec validation titre
│   └── utils/
│       ├── logger.py          # Logger UTF-8 (compatible Windows)
│       └── browser.py         # Initialisation Chrome WebDriver
│
├── data/
│   ├── input/                 # Fichiers source (CSV, TSV, SQLite — non versionnés)
│   └── output/                # Gold Layer généré (JSON)
│
├── tests/                     # Tests unitaires
├── Merise.md                  # Documentation MCD / MLD / MPD complète
├── MERISE.loo                 # Diagramme Merise (logiciel Looping)
├── requirements.txt           # Dépendances pip
├── pyproject.toml             # Métadonnées projet (uv)
└── .env                       # Variables d'environnement (NON versionné — confidentiel)
```

---

## Perspectives — Partie 2

Ce pipeline est le socle de l'architecture RAG de HorRAGor BOT. La Partie 2 construira par-dessus :

- **Vectorisation** : transformer les synopsis en vecteurs numériques (embeddings) via un LLM
- **Stockage vectoriel** : indexer ces vecteurs dans pgvector (extension PostgreSQL de Supabase)
- **RAG** : pour chaque question posée, retrouver les films les plus pertinents, puis générer une réponse contextuelle
- **Interface** : API FastAPI + interface conversationnelle

---

## Auteur

**Tim Dazayous** — Formation DEV IA Data Analyst, Simplon
Projet encadré par Antony Schutz
