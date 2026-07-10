# Modélisation Merise — HorRAGor BOT (Partie 1)

> Architecture de données pour la persistance du *Gold Layer* sur Supabase.
> Méthodologie : **Merise** (MCD → MLD → MPD).
> Approche : **Hub & Spoke** avec table `EVALUATION` unifiée pour tous les scores.

---

## 1. Modèle Conceptuel de Données (MCD)

Le MCD représente les concepts métiers de façon sémantique, indépendamment de toute technologie.

### Entités et attributs

**FILM** *(entité centrale — Hub)*
- `tmdb_id` — identifiant TMDB (référence universelle)
- `imdb_id` — identifiant IMDB (optionnel, issu de l'enrichissement)
- `title` — titre officiel (fourni par TMDB)
- `original_title` — titre original (langue d'origine)
- `release_date` — date de sortie normalisée ISO 8601
- `overview` — synopsis du film (jusqu'à 2000 caractères)
- `popularity` — indice de popularité TMDB (float)
- `source_system` — système d'alimentation (ex. `HorRAGor-Pipeline/TMDB`)
- `last_updated` — horodatage de la dernière mise à jour

**GENRE**
- `name` — libellé du genre (ex. `Horror`, `Thriller`)

**EVALUATION** *(Spoke — scores multi-sources)*
- `source_name` — source de la note (ex. `TMDB`, `IMDB`, `Rotten Tomatoes`)
- `score_type` — type d'évaluation : `Critic`, `Audience`, `User`
- `score_value` — valeur numérique (ex. `7.3`, `85.0`)
- `score_scale` — échelle de la note (ex. `10.0` pour TMDB/IMDB, `100.0` pour RT)
- `num_votes` — nombre de votants (pour TMDB et IMDB)
- `review_text` — texte du consensus critiques (Rotten Tomatoes)
- `source_url` — URL source de la critique ou de la page RT
- `evaluated_at` — horodatage de l'évaluation

**ANALYSE_SPARK** *(Spoke — enrichissement NLP)*
- `detected_language` — langue détectée du synopsis (`en`, `fr`, `other`)
- `overview_word_count` — nombre de mots du synopsis
- `horror_keywords` — liste JSON des mots-clés horreur détectés
- `richness_score` — score de richesse du synopsis (0-100)
- `analysed_at` — horodatage de l'analyse

**SOURCE** *(Spoke — traçabilité MDM)*
- `source_name` — nom de la source d'enrichissement
- `contributed_fields` — JSON listant les champs fournis par cette source
- `ingested_at` — horodatage d'ingestion

---

### Associations et cardinalités

| Association | FILM | | Entité | Signification |
|---|---|---|---|---|
| **appartient_à** | (0,n) | — | (0,n) GENRE | Un film peut appartenir à plusieurs genres ; un genre peut caractériser plusieurs films |
| **reçoit** | (1,1) | — | (0,n) EVALUATION | Un film peut recevoir plusieurs évaluations (une par source) ; chaque évaluation note exactement un film |
| **possède** | (1,1) | — | (0,1) ANALYSE_SPARK | Un film peut avoir au plus une analyse Spark ; cette analyse appartient à exactement un film |
| **tracé_par** | (1,1) | — | (0,n) SOURCE | Un film peut être tracé par plusieurs sources ; chaque source alimente exactement un film |

---

### Représentation schématique du MCD

```
                        ┌──────────────┐
                        │    GENRE     │
                        │─────────────│
                        │ name        │
                        └──────┬───────┘
                               │ (0,n)
                     appartient_à (N-N)
                               │ (0,n)
┌──────────────┐        ┌──────┴───────┐       ┌────────────────────┐
│   EVALUATION │        │    FILM      │       │   ANALYSE_SPARK    │
│──────────────│(0,n)   │──────────────│(0,1)  │────────────────────│
│ source_name  │◀──────▶│ tmdb_id      │◀─────▶│ detected_language  │
│ score_type   │ reçoit │ imdb_id      │possède│ overview_word_count│
│ score_value  │        │ title        │       │ horror_keywords    │
│ score_scale  │        │ original_    │       │ richness_score     │
│ num_votes    │        │   title      │       │ analysed_at        │
│ review_text  │        │ release_date │       └────────────────────┘
│ source_url   │        │ overview     │
│ evaluated_at │        │ popularity   │       ┌────────────────────┐
└──────────────┘        │ source_system│       │      SOURCE        │
                        │ last_updated │(0,n)  │────────────────────│
                        └──────────────│◀─────▶│ source_name        │
                                       │tracé  │ contributed_fields │
                                       │       │ ingested_at        │
                                       └───────└────────────────────┘
```

---

## 2. Modèle Logique de Données (MLD)

Le MLD traduit le MCD en modèle relationnel. La relation N-N FILM ↔ GENRE génère une table de liaison.

### Relations

- **FILM** (<u>id_film</u>, tmdb_id*, imdb_id, title, original_title, release_date, overview, popularity, source_system, last_updated)
- **GENRE** (<u>id_genre</u>, name*)
- **FILM_GENRE** (<u>#id_film</u>, <u>#id_genre</u>)  ← table de liaison N-N
- **EVALUATION** (<u>id_eval</u>, source_name, score_type, score_value, score_scale, num_votes, review_text, source_url, evaluated_at, *#id_film*)
- **ANALYSE_SPARK** (<u>id_analyse</u>, detected_language, overview_word_count, horror_keywords, richness_score, analysed_at, *#id_film*°)  ← contrainte UNIQUE sur id_film
- **SOURCE** (<u>id_source</u>, source_name, contributed_fields, ingested_at, *#id_film*)

> Légende : <u>souligné</u> = clé primaire | #clé_étrangère | * = NOT NULL | ° = UNIQUE

---

### Diagramme entité-relation (MLD)

```mermaid
erDiagram
    FILM {
        int     id           PK
        int     tmdb_id      UK "NOT NULL — clé de référence MDM"
        varchar imdb_id      UK "nullable — enrichi par IMDB"
        varchar title        "NOT NULL"
        varchar original_title
        date    release_date
        text    overview
        float   popularity
        varchar source_system "NOT NULL"
        timestamp last_updated
    }

    GENRE {
        int     id   PK
        varchar name UK "NOT NULL"
    }

    FILM_GENRE {
        int film_id  FK
        int genre_id FK
    }

    EVALUATION {
        int       id          PK
        int       film_id     FK "NOT NULL"
        varchar   source_name "NOT NULL — TMDB, IMDB, Rotten Tomatoes"
        varchar   score_type  "NOT NULL — Critic, Audience, User"
        float     score_value "NOT NULL"
        float     score_scale "NOT NULL — 10 ou 100"
        int       num_votes
        text      review_text "critics_consensus RT"
        varchar   source_url
        timestamp evaluated_at
    }

    ANALYSE_SPARK {
        int       id                  PK
        int       film_id             FK UK "UNIQUE — 1 analyse par film"
        varchar   detected_language   "en, fr, other"
        int       overview_word_count
        jsonb     horror_keywords     "liste de mots-clés détectés"
        int       richness_score      "0-100"
        timestamp analysed_at
    }

    SOURCE {
        int       id                PK
        int       film_id           FK "NOT NULL"
        varchar   source_name       "NOT NULL"
        jsonb     contributed_fields "liste des champs fournis"
        timestamp ingested_at
    }

    FILM        ||--o{ FILM_GENRE   : "appartient à"
    GENRE       ||--o{ FILM_GENRE   : "caractérise"
    FILM        ||--o{ EVALUATION   : "reçoit"
    FILM        ||--o| ANALYSE_SPARK : "possède"
    FILM        ||--o{ SOURCE       : "tracé par"
```

---

## 3. Modèle Physique de Données (MPD)

Implémentation SQL pour **PostgreSQL (Supabase)**. Le type `JSONB` est utilisé pour les champs JSON afin de bénéficier de l'indexation native PostgreSQL.

```sql
-- =========================================================
-- TABLE FILM (Hub central — source maîtresse TMDB)
-- =========================================================
CREATE TABLE film (
    id             SERIAL PRIMARY KEY,
    tmdb_id        INTEGER UNIQUE NOT NULL,         -- Clé MDM de référence
    imdb_id        VARCHAR(20) UNIQUE,              -- Nullable : fourni par TMDB ou enrichi IMDB
    title          VARCHAR(500) NOT NULL,
    original_title VARCHAR(500),
    release_date   DATE,
    overview       TEXT,
    popularity     FLOAT,
    source_system  VARCHAR(100) NOT NULL DEFAULT 'HorRAGor-Pipeline/TMDB',
    last_updated   TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_film_tmdb_id  ON film(tmdb_id);
CREATE INDEX idx_film_imdb_id  ON film(imdb_id);
CREATE INDEX idx_film_title    ON film(title);

-- =========================================================
-- TABLE GENRE
-- =========================================================
CREATE TABLE genre (
    id   SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL
);

-- =========================================================
-- TABLE DE LIAISON FILM_GENRE (N-N)
-- =========================================================
CREATE TABLE film_genre (
    film_id  INTEGER REFERENCES film(id)  ON DELETE CASCADE,
    genre_id INTEGER REFERENCES genre(id) ON DELETE CASCADE,
    PRIMARY KEY (film_id, genre_id)
);

-- =========================================================
-- TABLE EVALUATION (Spoke — scores multi-sources)
-- =========================================================
CREATE TABLE evaluation (
    id           SERIAL PRIMARY KEY,
    film_id      INTEGER NOT NULL REFERENCES film(id) ON DELETE CASCADE,
    source_name  VARCHAR(100) NOT NULL,  -- "TMDB", "IMDB", "Rotten Tomatoes"
    score_type   VARCHAR(50)  NOT NULL,  -- "User", "Critic", "Audience"
    score_value  FLOAT        NOT NULL,
    score_scale  FLOAT        NOT NULL,  -- 10.0 (TMDB/IMDB) ou 100.0 (RT)
    num_votes    INTEGER,
    review_text  TEXT,                   -- critics_consensus Rotten Tomatoes
    source_url   VARCHAR(500),
    evaluated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_evaluation_film_id     ON evaluation(film_id);
CREATE INDEX idx_evaluation_source_name ON evaluation(source_name);

-- =========================================================
-- TABLE ANALYSE_SPARK (Spoke — NLP, 1-1 avec FILM)
-- =========================================================
CREATE TABLE analyse_spark (
    id                   SERIAL PRIMARY KEY,
    film_id              INTEGER UNIQUE NOT NULL REFERENCES film(id) ON DELETE CASCADE,
    detected_language    VARCHAR(10),           -- "en", "fr", "other", "unknown"
    overview_word_count  INTEGER,
    horror_keywords      JSONB,                 -- ex: ["blood", "death", "ghost"]
    richness_score       INTEGER CHECK (richness_score BETWEEN 0 AND 100),
    analysed_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =========================================================
-- TABLE SOURCE (Spoke — traçabilité MDM)
-- =========================================================
CREATE TABLE source (
    id                 SERIAL PRIMARY KEY,
    film_id            INTEGER NOT NULL REFERENCES film(id) ON DELETE CASCADE,
    source_name        VARCHAR(100) NOT NULL,
    contributed_fields JSONB NOT NULL,          -- ex: ["overview", "budget"]
    ingested_at        TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_source_film_id    ON source(film_id);
CREATE INDEX idx_source_name       ON source(source_name);
```

---

## 4. Exemples d'enregistrements

### Table `evaluation` — exemples multi-sources

| source_name | score_type | score_value | score_scale | num_votes | review_text |
|---|---|---|---|---|---|
| `TMDB` | `User` | `7.3` | `10.0` | `4 050` | *null* |
| `IMDB` | `User` | `7.8` | `10.0` | `150 000` | *null* |
| `Rotten Tomatoes` | `Critic` | `89.0` | `100.0` | *null* | `"Hereditary subverts..."` |
| `Rotten Tomatoes` | `Audience` | `66.0` | `100.0` | *null* | *null* |

> Les scores RT (0-100%) et TMDB/IMDB (0-10) sont conservés dans leur **échelle native**
> (`score_scale` permet la normalisation côté application ou requête SQL).

### Table `source` — traçabilité MDM

| source_name | contributed_fields |
|---|---|
| `TMDB` | `["title", "overview", "release_date", "vote_average", "popularity", "genres"]` |
| `Kaggle` | `["overview"]` (synopsis manquant comblé) |
| `IMDB` | `["imdb_id"]` (identifiant récupéré) |
| `Spark` | `["detected_language", "overview_word_count", "horror_keywords", "richness_score"]` |

---

## 5. Principes RGPD appliqués

Conformément aux exigences du cahier des charges :

| Principe | Application |
|---|---|
| **Minimisation des données** | Seules les données nécessaires au RAG sont stockées. Pas de données personnelles utilisateurs collectées. |
| **Données publiques uniquement** | Toutes les sources sont publiques (API officielle, bases ouvertes, scraping de données non personnelles). |
| **Traçabilité** | La table `SOURCE` enregistre la provenance de chaque champ, conformément au principe d'accountability. |
| **Suppression en cascade** | `ON DELETE CASCADE` sur toutes les clés étrangères : supprimer un film supprime toutes ses données satellites. |
| **Pas de données personnelles** | Aucune donnée d'acteur, réalisateur ou utilisateur n'est stockée dans cette version. Le champ `review_text` contient uniquement le consensus éditorial de Rotten Tomatoes. |
