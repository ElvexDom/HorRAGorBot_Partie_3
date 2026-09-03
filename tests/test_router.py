"""
Tests unitaires de graph/router.py — l'aiguilleur du graphe.
Aucune dépendance externe : c'est justement le but de l'isoler.
"""
from graph.router import should_scrape_or_narrate


def test_routes_to_narration_when_rag_sufficient():
    state = {"rag_sufficient": True}
    assert should_scrape_or_narrate(state) == "narration"


def test_routes_to_scraper_when_rag_insufficient():
    state = {"rag_sufficient": False}
    assert should_scrape_or_narrate(state) == "scraper"


def test_routes_to_scraper_when_key_missing():
    """Absence de la clé (rag_node n'aurait pas dû se produire, mais le
    routeur ne doit jamais planter) -> comportement prudent : scraper."""
    state = {}
    assert should_scrape_or_narrate(state) == "scraper"
