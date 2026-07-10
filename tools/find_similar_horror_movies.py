"""
Tool 2 : find_similar_horror_movies
Trouve les films d'horreur les plus proches sémantiquement d'un film donné,
en utilisant l'index FAISS (similarité cosinus sur les vecteurs de synopsis).

Le retriever (model, index, id_map) est injecté depuis tools.rag_tool pour
éviter de charger le modèle deux fois en mémoire.
"""
import logging
import os

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "similar_movies",
        "description": (
            "Trouve les films d'horreur les plus similaires à un film précis, "
            "en comparant les synopsis par similarité sémantique (FAISS). "
            "À utiliser quand l'utilisateur demande des films similaires à un titre donné."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "movie_name": {
                    "type": "string",
                    "description": "Titre du film de référence"
                },
                "k": {
                    "type": "integer",
                    "description": "Nombre de films similaires à retourner (défaut : 5)",
                    "default": 5
                }
            },
            "required": ["movie_name"]
        }
    }
}


def _get_conn():
    db_url = os.environ.get("SUPABASE_DB_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        raise ValueError("SUPABASE_DB_URL ou DATABASE_URL non configurée.")
    return psycopg2.connect(db_url)


def _get_film_overview(movie_name: str) -> tuple:
    """Retourne (film_id, overview, title) pour le film demandé."""
    try:
        conn = _get_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, title, overview FROM film
                WHERE title ILIKE %s OR original_title ILIKE %s
                ORDER BY
                    CASE WHEN LOWER(title)          = LOWER(%s) THEN 0
                         WHEN LOWER(original_title) = LOWER(%s) THEN 1
                         ELSE 2
                    END,
                    popularity DESC NULLS LAST
                LIMIT 1
                """,
                (f"%{movie_name}%", f"%{movie_name}%", movie_name, movie_name)
            )
            row = cur.fetchone()
        conn.close()
        if not row:
            return None, "", movie_name
        return row["id"], row["overview"] or "", row["title"]
    except Exception as e:
        logger.error(f"Erreur _get_film_overview({movie_name!r}) : {e}")
        return None, "", movie_name


def _fetch_similar_films(film_ids: list) -> list:
    """Récupère les métadonnées des films similaires depuis Supabase."""
    if not film_ids:
        return []
    try:
        conn = _get_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    f.id,
                    f.title,
                    f.original_title,
                    EXTRACT(YEAR FROM f.release_date)::int          AS year,
                    ARRAY_AGG(DISTINCT g.name)
                        FILTER (WHERE g.name IS NOT NULL)           AS genres,
                    MAX(CASE WHEN e.source_name = 'TMDB'
                        THEN e.score_value END)                     AS tmdb_score
                FROM film f
                LEFT JOIN film_genre fg ON f.id = fg.film_id
                LEFT JOIN genre g       ON fg.genre_id = g.id
                LEFT JOIN evaluation e  ON f.id = e.film_id
                WHERE f.id = ANY(%s)
                GROUP BY f.id, f.title, f.original_title, f.release_date
                """,
                (film_ids,)
            )
            rows = cur.fetchall()
        conn.close()
        # Préserve l'ordre FAISS (par similarité décroissante)
        rows_by_id = {r["id"]: dict(r) for r in rows}
        return [rows_by_id[fid] for fid in film_ids if fid in rows_by_id]
    except Exception as e:
        logger.error(f"Erreur _fetch_similar_films : {e}")
        return []


def find_similar_horror_movies(
    movie_name: str,
    k: int = 5,
    model=None,
    index=None,
    id_map=None
) -> str:
    """
    Recherche les k films les plus similaires au film donné via FAISS.
    model / index / id_map sont injectés depuis tools.rag_tool (singleton partagé).
    """
    if model is None or index is None or id_map is None:
        return "Retriever FAISS non disponible."

    source_id, overview, found_title = _get_film_overview(movie_name)

    if not overview and source_id is None:
        return f"Film « {movie_name} » introuvable dans la base de données."

    # Encode le synopsis du film de référence (ou son titre si pas de synopsis)
    query_text = overview if overview else found_title
    vec = model.encode([query_text], normalize_embeddings=True).astype("float32")

    # Recherche k+1 pour pouvoir exclure le film source lui-même
    _, indices = index.search(vec, k + 1)

    import numpy as np
    film_ids = [
        int(id_map[i])
        for i in indices[0]
        if i < len(id_map)
    ]
    # Exclure le film source
    film_ids = [fid for fid in film_ids if fid != source_id][:k]

    films = _fetch_similar_films(film_ids)

    if not films:
        return f"Aucun film similaire trouvé pour « {found_title} »."

    lines = [f"Films similaires à « {found_title} » :\n"]
    for i, f in enumerate(films, 1):
        genres = ", ".join(f["genres"]) if f["genres"] else "N/A"
        score  = f"{f['tmdb_score']:.1f}/10" if f["tmdb_score"] else "N/A"
        lines.append(
            f"{i}. {f['title']} ({f['year'] or '?'}) — {genres} — TMDB {score}"
        )

    return "\n".join(lines)
