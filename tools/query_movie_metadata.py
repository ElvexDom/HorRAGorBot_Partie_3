"""
Tool 1 : query_movie_metadata
Récupère les métadonnées d'un film depuis Supabase (titre, année, genres, notes).
Le LLM ne génère jamais de SQL brut — toutes les requêtes sont paramétrées ici.
"""
import logging
import os

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# Définition du tool au format OpenAI / Groq
TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "query_movie_metadata",
        "description": (
            "Récupère les informations détaillées d'un film d'horreur présent en base : "
            "titre, année de sortie, genres, synopsis, notes TMDB / IMDB / Rotten Tomatoes. "
            "À utiliser quand l'utilisateur pose une question sur un film précis."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "movie_name": {
                    "type": "string",
                    "description": "Titre du film à rechercher (français ou titre original)"
                }
            },
            "required": ["movie_name"]
        }
    }
}


def _get_conn() -> psycopg2.extensions.connection:
    db_url = os.environ.get("SUPABASE_DB_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        raise ValueError("SUPABASE_DB_URL ou DATABASE_URL non configurée.")
    return psycopg2.connect(db_url)


def query_movie_metadata(movie_name: str) -> str:
    """
    Cherche un film par son nom et retourne ses métadonnées formatées pour le LLM.
    Priorité : correspondance exacte > correspondance partielle > popularité.
    """
    try:
        conn = _get_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    f.title,
                    f.original_title,
                    EXTRACT(YEAR FROM f.release_date)::int          AS year,
                    f.overview,
                    ARRAY_AGG(DISTINCT g.name)
                        FILTER (WHERE g.name IS NOT NULL)           AS genres,
                    MAX(CASE WHEN e.source_name = 'TMDB'
                        THEN e.score_value END)                     AS tmdb_score,
                    MAX(CASE WHEN e.source_name = 'IMDB'
                        THEN e.score_value END)                     AS imdb_score,
                    MAX(CASE WHEN e.source_name = 'Rotten Tomatoes'
                             AND e.score_type = 'Critic'
                        THEN e.score_value END)                     AS rt_critic,
                    MAX(CASE WHEN e.source_name = 'Rotten Tomatoes'
                             AND e.score_type = 'Audience'
                        THEN e.score_value END)                     AS rt_audience
                FROM film f
                LEFT JOIN film_genre fg ON f.id = fg.film_id
                LEFT JOIN genre g       ON fg.genre_id = g.id
                LEFT JOIN evaluation e  ON f.id = e.film_id
                WHERE f.title ILIKE %s OR f.original_title ILIKE %s
                GROUP BY
                    f.id, f.title, f.original_title, f.release_date,
                    f.overview, f.popularity
                ORDER BY
                    CASE WHEN LOWER(f.title)          = LOWER(%s) THEN 0
                         WHEN LOWER(f.original_title) = LOWER(%s) THEN 1
                         ELSE 2
                    END,
                    f.popularity DESC NULLS LAST
                LIMIT 1
                """,
                (f"%{movie_name}%", f"%{movie_name}%", movie_name, movie_name)
            )
            row = cur.fetchone()
        conn.close()

        if not row:
            return f"Aucun film trouvé pour « {movie_name} » dans la base de données."

        row = dict(row)

        genres_str = ", ".join(row["genres"]) if row["genres"] else "Non renseigné"

        scores = []
        if row["tmdb_score"] is not None:
            scores.append(f"TMDB : {row['tmdb_score']:.1f}/10")
        if row["imdb_score"] is not None:
            scores.append(f"IMDB : {row['imdb_score']:.1f}/10")
        if row["rt_critic"] is not None:
            scores.append(f"RT Critiques : {int(row['rt_critic'])}%")
        if row["rt_audience"] is not None:
            scores.append(f"RT Audience : {int(row['rt_audience'])}%")
        scores_str = " | ".join(scores) if scores else "Non disponible"

        title_line = row["title"]
        if row["original_title"] and row["original_title"] != row["title"]:
            title_line += f" ({row['original_title']})"

        return (
            f"Titre : {title_line}\n"
            f"Année : {row['year'] or 'Inconnue'}\n"
            f"Genres : {genres_str}\n"
            f"Notes : {scores_str}\n"
            f"Synopsis : {row['overview'] or 'Aucun synopsis disponible.'}"
        )

    except Exception as e:
        logger.error(f"Erreur query_movie_metadata({movie_name!r}) : {e}")
        return f"Impossible de récupérer les informations pour « {movie_name} »."
