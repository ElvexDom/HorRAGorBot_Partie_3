"""
Tool 4 : calculate_movie_age
Calcule l'âge exact d'un film à partir de sa date de sortie en base.
Récupère les données via la Couche Données (tools/data_api_client.py) —
aucun appel LLM, aucun SQL direct.
"""
import logging
from datetime import date

from tools import data_api_client

_MOIS_FR = [
    "", "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre"
]

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


def calculate_movie_age(movie_name: str) -> str:
    """
    Cherche le film via la Couche Données, récupère sa date de sortie et
    calcule son âge.
    """
    try:
        film = data_api_client.search_film(movie_name)

        if not film:
            return f"Film « {movie_name} » introuvable dans la base de données."

        if not film.get("release_date"):
            return f"La date de sortie de « {film['title']} » n'est pas renseignée en base."

        release = date.fromisoformat(film["release_date"])
        today   = date.today()
        age     = today.year - release.year - (
            (today.month, today.day) < (release.month, release.day)
        )

        title_display = film["title"]
        if film.get("original_title") and film["original_title"] != film["title"]:
            title_display += f" ({film['original_title']})"

        date_fr = f"{release.day} {_MOIS_FR[release.month]} {release.year}"

        return (
            f"« {title_display} » est sorti le {date_fr}.\n"
            f"Il y a exactement {age} an{'s' if age > 1 else ''} "
            f"(en {today.year})."
        )

    except Exception as e:
        logger.error(f"Erreur calculate_movie_age({movie_name!r}) : {e}")
        return f"Impossible de calculer l'âge de « {movie_name} »."
