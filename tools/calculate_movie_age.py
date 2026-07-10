"""
Tool 4 : calculate_movie_age
Calcule l'âge exact d'un film à partir de sa date de sortie en base.
Fonction Python pure — aucun appel LLM ni réseau.
"""
import logging
import os
from datetime import date

_MOIS_FR = [
    "", "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre"
]

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "movie_age",
        "description": (
            "Calcule l'âge exact d'un film d'horreur (en années) à partir de sa date de sortie. "
            "À utiliser quand l'utilisateur demande depuis combien de temps un film est sorti, "
            "son ancienneté, ou veut savoir si c'est un film récent ou ancien."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "movie_name": {
                    "type": "string",
                    "description": "Titre du film dont on veut calculer l'âge"
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


def calculate_movie_age(movie_name: str) -> str:
    """
    Cherche le film en base, récupère sa date de sortie et calcule son âge.
    """
    try:
        conn = _get_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT title, original_title, release_date
                FROM film
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
            return f"Film « {movie_name} » introuvable dans la base de données."

        if not row["release_date"]:
            return f"La date de sortie de « {row['title']} » n'est pas renseignée en base."

        release = row["release_date"]
        today   = date.today()
        age     = today.year - release.year - (
            (today.month, today.day) < (release.month, release.day)
        )

        title_display = row["title"]
        if row["original_title"] and row["original_title"] != row["title"]:
            title_display += f" ({row['original_title']})"

        date_fr = f"{release.day} {_MOIS_FR[release.month]} {release.year}"

        return (
            f"« {title_display} » est sorti le {date_fr}.\n"
            f"Il y a exactement {age} an{'s' if age > 1 else ''} "
            f"(en {today.year})."
        )

    except Exception as e:
        logger.error(f"Erreur calculate_movie_age({movie_name!r}) : {e}")
        return f"Impossible de calculer l'âge de « {movie_name} »."
