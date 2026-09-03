"""
Client HTTP vers la Couche Données (data_api/). Remplace les connexions
psycopg2 directes qu'effectuaient auparavant les tools de la Couche
Intelligence — plus aucun tool ne parle SQL.
"""
import logging
import os

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 5.0


def _base_url() -> str:
    return os.environ.get("DATA_API_URL", "http://localhost:8100")


def search_film(title: str) -> dict | None:
    """Cherche un film par titre (flou). Retourne None si introuvable ou si
    la Couche Données est inaccessible."""
    try:
        resp = httpx.get(f"{_base_url()}/films/search", params={"title": title}, timeout=_DEFAULT_TIMEOUT)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        logger.error(f"Data API inaccessible (search_film {title!r}) : {e}")
        return None


def get_films_by_ids(ids: list[int]) -> list[dict]:
    """Récupère plusieurs films par id, dans l'ordre fourni.

    Lève RuntimeError si la Couche Données est injoignable, plutôt que de
    retourner silencieusement une liste vide — certains appelants (ex:
    rag_tool.search_horror_movies) doivent distinguer "aucun résultat" de
    "service indisponible" pour informer l'utilisateur correctement."""
    if not ids:
        return []
    try:
        resp = httpx.get(
            f"{_base_url()}/films/batch",
            params={"ids": ",".join(str(i) for i in ids)},
            timeout=_DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        logger.error(f"Data API inaccessible (get_films_by_ids {ids!r}) : {e}")
        raise RuntimeError("Data API inaccessible (base en pause ?)") from e
