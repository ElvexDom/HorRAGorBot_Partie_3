"""
Tool 5 : horror_survival_simulator
Outil ludique qui simule les chances de survie de l'utilisateur
dans le scénario d'un film d'horreur.
Utilise le synopsis + les mots-clés horreur de la base pour nourrir le LLM.
"""
import logging
import os

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "survival_sim",
        "description": (
            "Simule de façon ludique et créative les chances de survie de l'utilisateur "
            "dans le scénario d'un film d'horreur. "
            "À utiliser quand l'utilisateur demande ses chances de survie, "
            "s'il survivrait dans un film, ou veut jouer avec le scénario d'un film d'horreur."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "movie_name": {
                    "type": "string",
                    "description": "Titre du film d'horreur pour la simulation"
                }
            },
            "required": ["movie_name"]
        }
    }
}

# Prompt créatif injecté dans le tool_result pour forcer un format engageant
SURVIVAL_INSTRUCTION = """
[INSTRUCTION CRÉATIVE — SIMULATEUR DE SURVIE]
Tu es un maître du jeu d'horreur sadique et omniscient.
À partir du contexte ci-dessus, génère un rapport de survie fictif, dramatique et amusant.
Respecte STRICTEMENT ce format markdown :

🩸 **SIMULATEUR DE SURVIE — [TITRE EN MAJUSCULES] ([ANNÉE])**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 **Probabilité de survie : XX%**
*(sois impitoyable, les films d'horreur ne font pas de cadeau)*

💀 **Cause de mort la plus probable :**
[Description dramatique et précise basée sur les éléments du film — 2-3 phrases]

🔪 **Les 3 menaces principales :**
1. [Menace tirée du film]
2. [Menace tirée du film]
3. [Menace tirée du film]

🛡️ **Tes seules chances :**
• [Conseil spécifique au film, concret]
• [Conseil spécifique au film, concret]
• [Conseil spécifique au film, concret]

☠️ **Verdict final :**
*[Une phrase finale cinglante sur ton destin inévitable]*

Sois créatif, précis sur les éléments du film, et garde un ton entre humour noir et horreur authentique.
"""


def _get_conn():
    db_url = os.environ.get("SUPABASE_DB_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        raise ValueError("SUPABASE_DB_URL ou DATABASE_URL non configurée.")
    return psycopg2.connect(db_url)


def get_survival_context(movie_name: str) -> str:
    """
    Récupère le synopsis, les mots-clés horreur et les métadonnées du film
    pour alimenter la simulation de survie.
    """
    try:
        conn = _get_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    f.title,
                    f.original_title,
                    EXTRACT(YEAR FROM f.release_date)::int  AS year,
                    f.overview,
                    ARRAY_AGG(DISTINCT g.name)
                        FILTER (WHERE g.name IS NOT NULL)   AS genres,
                    s.horror_keywords,
                    s.richness_score
                FROM film f
                LEFT JOIN film_genre fg   ON f.id = fg.film_id
                LEFT JOIN genre g         ON fg.genre_id = g.id
                LEFT JOIN analyse_spark s ON f.id = s.film_id
                WHERE f.title ILIKE %s OR f.original_title ILIKE %s
                GROUP BY
                    f.id, f.title, f.original_title, f.release_date,
                    f.overview, s.horror_keywords, s.richness_score
                ORDER BY
                    CASE WHEN LOWER(f.title) = LOWER(%s) THEN 0 ELSE 1 END,
                    f.popularity DESC NULLS LAST
                LIMIT 1
                """,
                (f"%{movie_name}%", f"%{movie_name}%", movie_name)
            )
            row = cur.fetchone()
        conn.close()

        if not row:
            return f"Film « {movie_name} » introuvable en base."

        row = dict(row)
        title = row["title"]
        if row["original_title"] and row["original_title"] != row["title"]:
            title += f" ({row['original_title']})"

        genres = ", ".join(row["genres"]) if row["genres"] else "Horreur"

        keywords = ""
        if row["horror_keywords"]:
            kw = row["horror_keywords"]
            if isinstance(kw, list):
                keywords = ", ".join(kw[:15])
            elif isinstance(kw, str):
                keywords = kw

        context = (
            f"Film : {title} ({row['year'] or '?'})\n"
            f"Genres : {genres}\n"
            f"Synopsis : {row['overview'] or 'Non disponible'}\n"
        )
        if keywords:
            context += f"Éléments d'horreur clés : {keywords}\n"

        context += SURVIVAL_INSTRUCTION
        return context

    except Exception as e:
        logger.error(f"Erreur get_survival_context({movie_name!r}) : {e}")
        return (
            f"Données limitées pour « {movie_name} ».\n"
            f"Génère quand même la simulation avec ta connaissance générale du film.\n"
            + SURVIVAL_INSTRUCTION
        )
