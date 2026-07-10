"""
State de confiance du système multi-agent HorRAGor.
Mémoire commune partagée et enrichie par les nœuds (rag_node, scraper_node,
narration_node) au fil du graphe. Les nœuds ne savent jamais qui a travaillé
avant eux ni qui prendra la suite — ils lisent/écrivent uniquement ce state.
"""
import operator
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """State de confiance partagé entre les agents RAG, Scraper et Narration."""

    messages: Annotated[list[BaseMessage], add_messages]

    # Question brute posée par l'utilisateur
    user_question: str

    # Contexte brut agrégé issu des tools de l'Agent RAG (FAISS + Supabase)
    rag_context: str

    # Posé par rag_node, lu par router.should_scrape_or_narrate
    rag_sufficient: bool

    # Contexte enrichi par l'Agent Scraper — vide si le routeur n'y a pas envoyé le flux
    scraper_context: str

    # Traçabilité des outils/agents traversés, pour l'API et le bandeau du Juge côté UI.
    # Chaque nœud ne connaît que sa propre liste : operator.add les cumule dans l'ordre du graphe.
    tools_used: Annotated[list[str], operator.add]
