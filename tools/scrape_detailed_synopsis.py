"""
Tool 3 : scrape_detailed_synopsis
Récupère un synopsis détaillé depuis l'API Wikipedia (REST + BeautifulSoup).
Activé uniquement si l'utilisateur demande des détails approfondis
non présents dans la base (anecdotes, contexte de production, etc.).
"""
import logging
import os
import re

import psycopg2
import requests
from bs4 import BeautifulSoup
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "detailed_synopsis",
        "description": (
            "Récupère un synopsis détaillé et des informations approfondies sur un film d'horreur "
            "depuis Wikipedia. À utiliser UNIQUEMENT si l'utilisateur demande des détails précis "
            "non disponibles en base : anecdotes de tournage, contexte de production, analyse, "
            "réception critique détaillée, ou si l'utilisateur dit 'dis-m'en plus', 'plus de détails', "
            "'anecdotes', 'comment a été fait le film'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "movie_name": {
                    "type": "string",
                    "description": "Titre du film à rechercher sur Wikipedia"
                }
            },
            "required": ["movie_name"]
        }
    }
}

_HEADERS = {
    "User-Agent": "HorRAGorBot/2.0 (educational project; contact: horragor@example.com)"
}
_WIKI_SEARCH_URL = "https://fr.wikipedia.org/w/api.php"
_WIKI_PARSE_URL  = "https://fr.wikipedia.org/w/api.php"
_MAX_CHARS = 2000


def _get_conn():
    db_url = os.environ.get("SUPABASE_DB_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        raise ValueError("SUPABASE_DB_URL ou DATABASE_URL non configurée.")
    return psycopg2.connect(db_url)


def _get_film_title(movie_name: str) -> str:
    """Récupère le titre exact depuis la base pour améliorer la recherche Wikipedia."""
    try:
        conn = _get_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT title, original_title FROM film
                WHERE title ILIKE %s OR original_title ILIKE %s
                ORDER BY
                    CASE WHEN LOWER(title) = LOWER(%s) THEN 0
                         ELSE 1 END,
                    popularity DESC NULLS LAST
                LIMIT 1
                """,
                (f"%{movie_name}%", f"%{movie_name}%", movie_name)
            )
            row = cur.fetchone()
        conn.close()
        if row:
            # Préfère le titre original pour Wikipedia (souvent en anglais)
            return row["original_title"] or row["title"]
    except Exception as e:
        logger.warning(f"DB inaccessible pour titre : {e}")
    return movie_name


def _search_wikipedia_page(query: str) -> str | None:
    """Cherche une page Wikipedia et retourne son titre exact."""
    params = {
        "action":   "query",
        "list":     "search",
        "srsearch": f"{query} film horreur",
        "srlimit":  3,
        "format":   "json",
        "origin":   "*",
    }
    try:
        resp = requests.get(_WIKI_SEARCH_URL, params=params, headers=_HEADERS, timeout=8)
        resp.raise_for_status()
        results = resp.json().get("query", {}).get("search", [])
        if results:
            return results[0]["title"]
    except Exception as e:
        logger.error(f"Erreur recherche Wikipedia : {e}")
    return None


def _get_page_extract(page_title: str) -> str:
    """Récupère le texte de la section principale de la page Wikipedia."""
    params = {
        "action":      "query",
        "prop":        "extracts",
        "exintro":     False,
        "explaintext": True,
        "titles":      page_title,
        "format":      "json",
        "origin":      "*",
    }
    try:
        resp = requests.get(_WIKI_PARSE_URL, params=params, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        pages = resp.json().get("query", {}).get("pages", {})
        page  = next(iter(pages.values()))
        return page.get("extract", "")
    except Exception as e:
        logger.error(f"Erreur extraction Wikipedia : {e}")
    return ""


def _clean_and_truncate(text: str, max_chars: int = _MAX_CHARS) -> str:
    """Nettoie le texte Wikipedia et le tronque proprement."""
    # Supprime les sections peu utiles (références, liens externes, etc.)
    for section in ["== Références ==", "== Liens externes ==",
                    "== Notes ==", "== Voir aussi =="]:
        idx = text.find(section)
        if idx != -1:
            text = text[:idx]

    # Normalise les espaces et sauts de ligne
    text = re.sub(r"\n{3,}", "\n\n", text.strip())

    if len(text) <= max_chars:
        return text

    # Tronque à la dernière phrase complète avant max_chars
    truncated = text[:max_chars]
    last_dot  = truncated.rfind(".")
    if last_dot > max_chars * 0.7:
        truncated = truncated[:last_dot + 1]

    return truncated + "\n\n[...] (résumé tronqué)"


def scrape_detailed_synopsis(movie_name: str) -> str:
    """
    Récupère un synopsis détaillé depuis Wikipedia pour un film d'horreur.
    Utilise l'API REST Wikipedia (pas de scraping HTML brut).
    """
    # 1. Titre exact depuis la DB
    search_title = _get_film_title(movie_name)
    logger.info(f"Recherche Wikipedia pour : {search_title!r}")

    # 2. Recherche de la page Wikipedia
    page_title = _search_wikipedia_page(search_title)
    if not page_title:
        # Deuxième tentative en français
        page_title = _search_wikipedia_page(movie_name)

    if not page_title:
        return f"Aucune page Wikipedia trouvée pour « {movie_name} »."

    logger.info(f"Page Wikipedia trouvée : {page_title!r}")

    # 3. Récupération du contenu
    extract = _get_page_extract(page_title)
    if not extract:
        return f"La page Wikipedia « {page_title} » existe mais son contenu est vide."

    # 4. Nettoyage et troncature
    clean = _clean_and_truncate(extract)

    return f"Source Wikipedia — « {page_title} » :\n\n{clean}"
