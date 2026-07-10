"""
Client API TMDB (The Movie Database).

TMDB est la SOURCE MAÎTRESSE du pipeline HorRAGor.
Elle fournit les identifiants de référence (tmdb_id, imdb_id),
les titres officiels, et les métadonnées structurées de chaque film.

API gratuite avec clé sur https://www.themoviedb.org/settings/api
Documentation : https://developer.themoviedb.org/reference/intro/getting-started
"""
import requests
from typing import List, Optional, Dict
from app.config.config import settings
from app.utils.logger import logger
from app.models.schema import MovieGold


class TMDBService:
    """
    Wrapper autour de l'API REST TMDB v3.
    Deux endpoints principaux utilisés par le pipeline :
      - /discover/movie : liste paginée des films d'horreur
      - /movie/{id}     : détails complets d'un film (pour imdb_id et genres)
    """

    HORROR_GENRE_ID = 27   # ID TMDB du genre "Horror"

    def __init__(self):
        self.api_key  = settings.TMDB_API_KEY
        self.base_url = settings.TMDB_BASE_URL
        self.headers  = {"Accept": "application/json"}

    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """
        Requête GET générique vers l'API TMDB.
        Injecte automatiquement la clé API dans les paramètres.
        Retourne None en cas d'erreur réseau ou HTTP (pas d'exception levée).
        """
        if params is None:
            params = {}
        params["api_key"] = self.api_key
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            response = requests.get(url, params=params, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Erreur lors de l'appel TMDB ({endpoint}): {str(e)}")
            return None

    def search_horror_movies(self, query: str, year: Optional[str] = None) -> List[MovieGold]:
        """
        Recherche des films d'horreur par titre (endpoint /search/movie).
        Filtre les résultats pour ne garder que genre_id=27 (Horror).
        Utilisé pour des recherches ponctuelles, pas pour le pipeline batch.
        """
        params = {
            "query": query,
            "include_adult": "false",
            "language": "fr-FR",
        }
        if year:
            params["year"] = year

        data = self._get("search/movie", params)
        if not data or "results" not in data:
            return []

        movies = []
        for result in data["results"]:
            if self.HORROR_GENRE_ID in result.get("genre_ids", []):
                details = self.get_movie_details(result["id"])
                movie = MovieGold(
                    tmdb_id=result["id"],
                    imdb_id=details.get("imdb_id") if details else None,
                    title=result["title"],
                    original_title=result.get("original_title"),
                    release_date=result.get("release_date"),
                    overview=result.get("overview"),
                    vote_average=result.get("vote_average"),
                    popularity=result.get("popularity"),
                    genres=[g["name"] for g in details.get("genres", [])] if details else ["Horror"],
                )
                movies.append(movie)

        return movies

    def get_movie_details(self, tmdb_id: int) -> Optional[Dict]:
        """
        Récupère les détails complets d'un film via /movie/{id}.
        Nécessaire pour obtenir imdb_id et la liste complète des genres
        (les genres ne sont pas inclus dans la réponse /discover).
        """
        return self._get(f"movie/{tmdb_id}")

    def discover_horror_movies(self, page: int = 1, sort_by: str = "popularity.desc") -> Dict:
        """
        Découvre les films d'horreur via /discover/movie.
        Trie par popularité décroissante — les films les plus connus en premier.
        Retourne 20 films par page (limite TMDB).

        Usage dans le pipeline :
          for page in range(1, pages + 1):
              data = tmdb.discover_horror_movies(page=page)
        """
        params = {
            "with_genres": self.HORROR_GENRE_ID,
            "sort_by": sort_by,
            "page": page,
            "language": "fr-FR",
        }
        return self._get("discover/movie", params)
