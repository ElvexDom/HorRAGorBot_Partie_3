"""
Outil natif de recherche Web — Agent Scraper (L'Enquêteur du Web).
Fine enveloppe autour de tools.scrape_detailed_synopsis : c'est le seul
outil auquel l'Agent Scraper a accès, déclenché uniquement par le routeur
quand le savoir local (Agent RAG) est jugé insuffisant.
"""
import logging

from tools.scrape_detailed_synopsis import (
    TOOL_DEFINITION as SCRAPE_SYNOPSIS_TOOL,
    scrape_detailed_synopsis,
)

logger = logging.getLogger(__name__)

SCRAPER_TOOLS = [SCRAPE_SYNOPSIS_TOOL]

SCRAPER_TOOL_DISPATCH = {
    "detailed_synopsis": lambda args: scrape_detailed_synopsis(
        args.get("movie_name", "")
    ),
}


def run_scraper(movie_name: str) -> str:
    """Va creuser Wikipedia pour un film donné et retourne le texte trouvé."""
    return scrape_detailed_synopsis(movie_name)
