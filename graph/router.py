"""
router.py — Les Aiguilleurs (La Logique Décisionnelle)

Une fonction de routage examine l'état actuel (state) et a pour seule
responsabilité de renvoyer une chaîne de caractères correspondant à la
prochaine destination. Isoler cette logique permet de la tester
unitairement, sans lancer tout le pipeline.
"""
from graph.state import AgentState


def should_scrape_or_narrate(state: AgentState) -> str:
    """Aiguille le flux après l'Agent RAG : si la récolte locale est
    suffisante, direction Narration ; sinon, direction Scraper."""
    if state.get("rag_sufficient"):
        return "narration"
    return "scraper"
