"""
Tests d'intégration du StateGraph compilé (graph/pipeline.py), LLM et tools
mockés au niveau des nœuds. Ces tests prouvent le critère du cahier des
charges : "Déterminisme du routage — le graphe ne boucle jamais à l'infini,
les transitions conditionnelles s'exécutent de manière prévisible."
"""
import pytest

from graph.pipeline import app as agent_graph
from tests.conftest import make_ai_message


@pytest.mark.asyncio
async def test_sufficient_rag_skips_scraper_entirely(monkeypatch, fake_llm_factory):
    # rag_node : 1 tool-call puis arrêt (2 invoke) ; narration_node : 1 invoke.
    llm = fake_llm_factory([
        make_ai_message(tool_calls=[
            {"name": "search_horror_movies", "args": {"query": "Shining"}, "id": "1"}
        ]),
        make_ai_message(content="terminé"),
        make_ai_message(content="Il était une fois, dans un hôtel maudit..."),
    ])
    monkeypatch.setattr("graph.nodes.get_groq_llm", lambda temperature=None, **k: llm)
    monkeypatch.setattr(
        "graph.nodes.RAG_TOOL_DISPATCH",
        {"search_horror_movies": lambda args: "Titre : Shining (1980)\nGenres : Horror"},
    )

    result = await agent_graph.ainvoke({
        "user_question": "Parle-moi de Shining",
        "messages": [],
        "tools_used": [],
    })

    assert result["rag_sufficient"] is True
    assert "detailed_synopsis" not in result["tools_used"]  # scraper jamais déclenché
    assert result["tools_used"] == ["search_horror_movies", "narration-llm"]
    assert result["messages"][-1].content == "Il était une fois, dans un hôtel maudit..."


@pytest.mark.asyncio
async def test_insufficient_rag_routes_through_scraper_then_narration(monkeypatch, fake_llm_factory):
    # rag_node : 1 tool-call puis arrêt (2 invoke) ; scraper_node : 1 invoke ;
    # narration_node : 1 invoke. Total 4 appels, dans cet ordre précis.
    llm = fake_llm_factory([
        make_ai_message(tool_calls=[
            {"name": "search_horror_movies", "args": {"query": "Film obscur"}, "id": "1"}
        ]),
        make_ai_message(content="terminé"),
        make_ai_message(tool_calls=[
            {"name": "detailed_synopsis", "args": {"movie_name": "Film obscur"}, "id": "2"}
        ]),
        make_ai_message(content="Une créature rôde dans l'ombre..."),
    ])
    monkeypatch.setattr("graph.nodes.get_groq_llm", lambda temperature=None, **k: llm)
    monkeypatch.setattr(
        "graph.nodes.RAG_TOOL_DISPATCH",
        {"search_horror_movies": lambda args: "Aucun film trouvé dans la base de données."},
    )
    monkeypatch.setattr(
        "graph.nodes.SCRAPER_TOOL_DISPATCH",
        {"detailed_synopsis": lambda args: "Source Wikipedia — Film obscur : anecdotes..."},
    )

    result = await agent_graph.ainvoke({
        "user_question": "Parle-moi d'un film totalement obscur",
        "messages": [],
        "tools_used": [],
    })

    assert result["rag_sufficient"] is False
    assert result["tools_used"] == ["search_horror_movies", "detailed_synopsis", "narration-llm"]
    assert result["messages"][-1].content == "Une créature rôde dans l'ombre..."


@pytest.mark.asyncio
async def test_tools_used_accumulates_without_overwriting(monkeypatch, fake_llm_factory):
    """Intégrité du State : tools_used (operator.add) doit accumuler les
    contributions de chaque nœud sans jamais écraser les précédentes."""
    llm = fake_llm_factory([
        make_ai_message(tool_calls=[
            {"name": "search_horror_movies", "args": {"query": "x"}, "id": "1"}
        ]),
        make_ai_message(content="terminé"),
        make_ai_message(content="Conte gothique final."),
    ])
    monkeypatch.setattr("graph.nodes.get_groq_llm", lambda temperature=None, **k: llm)
    monkeypatch.setattr(
        "graph.nodes.RAG_TOOL_DISPATCH",
        {"search_horror_movies": lambda args: "Titre : X"},
    )

    result = await agent_graph.ainvoke({
        "user_question": "Question",
        "messages": [],
        "tools_used": [],
    })

    # 1 outil RAG + le nœud de narration ajoutent chacun leur entrée, dans l'ordre.
    assert result["tools_used"] == ["search_horror_movies", "narration-llm"]
