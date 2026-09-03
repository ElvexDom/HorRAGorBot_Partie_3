"""
Tool 1 : query_movie_metadata
Récupère les métadonnées d'un film via la Couche Données (data_api/) :
titre, année, genres, notes. Le LLM ne parle jamais SQL — la requête est
paramétrée côté data_api/db.py, ce tool ne fait que la formater.
"""
import logging

from tools import data_api_client

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


def query_movie_metadata(movie_name: str) -> str:
    """
    Cherche un film par son nom et retourne ses métadonnées formatées pour le LLM.
    Priorité : correspondance exacte > correspondance partielle > popularité
    (logique appliquée côté Couche Données, data_api/db.py).
    """
    try:
        film = data_api_client.search_film(movie_name)

        if not film:
            return f"Aucun film trouvé pour « {movie_name} » dans la base de données."

        genres_str = ", ".join(film["genres"]) if film["genres"] else "Non renseigné"

        evaluations = film.get("evaluations") or {}
        scores = []
        if evaluations.get("tmdb") is not None:
            scores.append(f"TMDB : {evaluations['tmdb']:.1f}/10")
        if evaluations.get("imdb") is not None:
            scores.append(f"IMDB : {evaluations['imdb']:.1f}/10")
        if evaluations.get("rt_critic") is not None:
            scores.append(f"RT Critiques : {int(evaluations['rt_critic'])}%")
        if evaluations.get("rt_audience") is not None:
            scores.append(f"RT Audience : {int(evaluations['rt_audience'])}%")
        scores_str = " | ".join(scores) if scores else "Non disponible"

        title_line = film["title"]
        if film.get("original_title") and film["original_title"] != film["title"]:
            title_line += f" ({film['original_title']})"

        year = film["release_date"][:4] if film.get("release_date") else None

        return (
            f"Titre : {title_line}\n"
            f"Année : {year or 'Inconnue'}\n"
            f"Genres : {genres_str}\n"
            f"Notes : {scores_str}\n"
            f"Synopsis : {film.get('overview') or 'Aucun synopsis disponible.'}"
        )

    except Exception as e:
        logger.error(f"Erreur query_movie_metadata({movie_name!r}) : {e}")
        return f"Impossible de récupérer les informations pour « {movie_name} »."
