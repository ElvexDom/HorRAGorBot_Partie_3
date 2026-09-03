"""
Tool 5 : horror_survival_simulator
Outil ludique qui simule les chances de survie de l'utilisateur
dans le scénario d'un film d'horreur.
Utilise le synopsis + les mots-clés horreur (Couche Données) pour nourrir le LLM.
"""
import logging

from tools import data_api_client

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


def get_survival_context(movie_name: str) -> str:
    """
    Récupère le synopsis, les mots-clés horreur et les métadonnées du film
    (via la Couche Données) pour alimenter la simulation de survie.
    """
    try:
        film = data_api_client.search_film(movie_name)

        if not film:
            return f"Film « {movie_name} » introuvable en base."

        title = film["title"]
        if film.get("original_title") and film["original_title"] != film["title"]:
            title += f" ({film['original_title']})"

        genres = ", ".join(film["genres"]) if film["genres"] else "Horreur"
        keywords = ", ".join(film["horror_keywords"][:15]) if film.get("horror_keywords") else ""
        year = film["release_date"][:4] if film.get("release_date") else None

        context = (
            f"Film : {title} ({year or '?'})\n"
            f"Genres : {genres}\n"
            f"Synopsis : {film.get('overview') or 'Non disponible'}\n"
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
