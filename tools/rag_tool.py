"""
Outil natif de recherche locale — Agent RAG (Le Chercheur Local).
Regroupe le retriever FAISS (recherche sémantique) et la liste des tools
Groq/OpenAI que l'Agent RAG a le droit d'appeler : recherche sémantique,
métadonnées précises, films similaires, âge d'un film, simulateur de survie.

Le savoir Wikipedia (detailed_synopsis) n'est PAS ici : c'est l'outil
exclusif de l'Agent Scraper (tools/scraper_tool.py).
"""
import logging
from pathlib import Path
from typing import Optional

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from tools.calculate_movie_age import TOOL_DEFINITION as MOVIE_AGE_TOOL
from tools.calculate_movie_age import calculate_movie_age
from tools import data_api_client
from tools.find_similar_horror_movies import TOOL_DEFINITION as FIND_SIMILAR_TOOL
from tools.find_similar_horror_movies import find_similar_horror_movies
from tools.horror_survival_simulator import TOOL_DEFINITION as SURVIVAL_SIM_TOOL
from tools.horror_survival_simulator import get_survival_context
from tools.query_movie_metadata import TOOL_DEFINITION as QUERY_METADATA_TOOL
from tools.query_movie_metadata import query_movie_metadata

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FAISS retriever (singleton partagé, préchargé au démarrage de l'API)
# ---------------------------------------------------------------------------

_BASE_DIR = Path(__file__).parent.parent
_FAISS_INDEX_PATH = _BASE_DIR / "data" / "faiss.index"
_ID_MAP_PATH = _BASE_DIR / "data" / "id_map.npy"

_model: Optional[SentenceTransformer] = None
_index: Optional[faiss.Index] = None
_id_map: Optional[np.ndarray] = None


def _get_retriever() -> tuple[SentenceTransformer, faiss.Index, np.ndarray]:
    global _model, _index, _id_map
    if _index is not None:
        return _model, _index, _id_map
    logger.info("Chargement SentenceTransformer + index FAISS...")
    _model = SentenceTransformer("all-MiniLM-L6-v2")
    _index = faiss.read_index(str(_FAISS_INDEX_PATH))
    _id_map = np.load(str(_ID_MAP_PATH))
    logger.info(f"Index FAISS chargé : {_index.ntotal} vecteurs")
    return _model, _index, _id_map


def get_retriever() -> tuple[SentenceTransformer, faiss.Index, np.ndarray]:
    """Accès public au retriever singleton (utilisé par similar_movies)."""
    return _get_retriever()


def initialize_retriever() -> None:
    """Pré-charge le modèle et l'index FAISS (à appeler au démarrage de l'API)."""
    _get_retriever()


# ---------------------------------------------------------------------------
# Tool : search_horror_movies (recherche sémantique libre)
# ---------------------------------------------------------------------------

SEARCH_HORROR_MOVIES_TOOL = {
    "type": "function",
    "function": {
        "name": "search_horror_movies",
        "description": (
            "Recherche sémantique dans la base de 1179 films d'horreur. "
            "À utiliser pour toute demande de recommandation ou suggestion de film : "
            "'quel film me conseilles-tu', 'un bon film d'horreur', "
            "'recommande-moi quelque chose', 'films avec des fantômes', etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "La requête de recherche sémantique"
                },
                "k": {
                    "type": "integer",
                    "description": "Nombre de films à récupérer (défaut : 5)",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    }
}


def search_horror_movies(query: str, k: int = 5) -> str:
    """Exécute la recherche FAISS + Couche Données et retourne le contexte textuel."""
    model, index, id_map = _get_retriever()
    vec = model.encode([query], normalize_embeddings=True).astype("float32")
    _, indices = index.search(vec, k)

    film_ids = [int(id_map[i]) for i in indices[0] if i < len(id_map)]
    try:
        films = data_api_client.get_films_by_ids(film_ids)
    except RuntimeError as e:
        return f"[ERREUR BASE DE DONNÉES] {e} — informe l'utilisateur que la base est temporairement inaccessible."

    if not films:
        return "Aucun film trouvé dans la base de données."

    parts = []
    for f in films:
        year = f["release_date"][:4] if f.get("release_date") else ""
        genres = ", ".join(f["genres"]) if f["genres"] else ""
        tmdb_score = (f.get("evaluations") or {}).get("tmdb")
        parts.append(
            f"Titre : {f['title']} ({year})\n"
            f"Genres : {genres}\n"
            f"Note TMDB : {tmdb_score or 'N/A'}\n"
            f"Synopsis : {f.get('overview') or ''}"
        )

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Tools disponibles pour l'Agent RAG
# ---------------------------------------------------------------------------

RAG_TOOLS = [
    SEARCH_HORROR_MOVIES_TOOL,
    QUERY_METADATA_TOOL,
    FIND_SIMILAR_TOOL,
    MOVIE_AGE_TOOL,
    SURVIVAL_SIM_TOOL,
]

# Dispatch nom de tool -> fonction Python (appelée par graph.nodes.rag_node)
RAG_TOOL_DISPATCH = {
    "search_horror_movies": lambda args: search_horror_movies(
        args.get("query", ""), args.get("k", 5)
    ),
    "query_movie_metadata": lambda args: query_movie_metadata(
        args.get("movie_name", "")
    ),
    "similar_movies": lambda args: find_similar_horror_movies(
        args.get("movie_name", ""), args.get("k", 5), *_get_retriever()
    ),
    "movie_age": lambda args: calculate_movie_age(args.get("movie_name", "")),
    "survival_sim": lambda args: get_survival_context(args.get("movie_name", "")),
}

# Marqueurs d'échec utilisés par graph.router pour juger si le RAG est suffisant
INSUFFICIENT_MARKERS = (
    "aucun film trouvé",
    "introuvable dans la base",
    "erreur base de données",
    "non disponible",
)
