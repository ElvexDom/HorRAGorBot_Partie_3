"""
Tool 2 : find_similar_horror_movies
Trouve les films d'horreur les plus proches sémantiquement d'un film donné,
en utilisant l'index FAISS (similarité cosinus sur les vecteurs de synopsis).
Les métadonnées des films sont récupérées via la Couche Données (data_api/).

Le retriever (model, index, id_map) est injecté depuis tools.rag_tool pour
éviter de charger le modèle deux fois en mémoire.
"""
import logging

from tools import data_api_client

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


def _get_film_overview(movie_name: str) -> tuple:
    """Retourne (film_id, overview, title) pour le film demandé."""
    film = data_api_client.search_film(movie_name)
    if not film:
        return None, "", movie_name
    return film["id"], film.get("overview") or "", film["title"]


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

    try:
        films = data_api_client.get_films_by_ids(film_ids)
    except RuntimeError as e:
        logger.error(f"Erreur find_similar_horror_movies : {e}")
        films = []

    if not films:
        return f"Aucun film similaire trouvé pour « {found_title} »."

    lines = [f"Films similaires à « {found_title} » :\n"]
    for i, f in enumerate(films, 1):
        genres = ", ".join(f["genres"]) if f["genres"] else "N/A"
        tmdb_score = (f.get("evaluations") or {}).get("tmdb")
        score = f"{tmdb_score:.1f}/10" if tmdb_score else "N/A"
        year = f["release_date"][:4] if f.get("release_date") else "?"
        lines.append(f"{i}. {f['title']} ({year}) — {genres} — TMDB {score}")

    return "\n".join(lines)
