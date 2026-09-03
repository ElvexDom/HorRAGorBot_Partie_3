"""
Tests unitaires de graph/nodes.py — les trois agents (RAG, Scraper, Narration).
Le LLM Groq et les tools sont entièrement mockés : ces tests ne font ni
appel réseau, ni appel Postgres/FAISS/Wikipedia réel.
"""
import httpx
import pytest
from groq import BadRequestError

from graph.nodes import narration_node, rag_node, scraper_node
from tests.conftest import make_ai_message


def _bad_request_error() -> BadRequestError:
    response = httpx.Response(400, request=httpx.Request("POST", "http://groq.test"))
    return BadRequestError("invalid_request", response=response, body=None)


# ---------------------------------------------------------------------------
# rag_node
# ---------------------------------------------------------------------------

class TestRagNode:
    def test_sufficient_result_marks_rag_sufficient(self, monkeypatch, fake_llm_factory):
        tool_call = {"name": "search_horror_movies", "args": {"query": "Shining"}, "id": "1"}
        llm = fake_llm_factory([
            make_ai_message(tool_calls=[tool_call]),
            make_ai_message(content="terminé"),
        ])
        monkeypatch.setattr("graph.nodes.get_groq_llm", lambda temperature=0.2: llm)
        monkeypatch.setattr(
            "graph.nodes.RAG_TOOL_DISPATCH",
            {"search_horror_movies": lambda args: "Titre : Shining (1980)\nGenres : Horror"},
        )

        result = rag_node({"user_question": "Parle-moi de Shining"})

        assert result["rag_sufficient"] is True
        assert result["tools_used"] == ["search_horror_movies"]
        assert "Shining" in result["rag_context"]

    def test_insufficient_result_marks_rag_insufficient(self, monkeypatch, fake_llm_factory):
        tool_call = {"name": "search_horror_movies", "args": {"query": "Film inconnu"}, "id": "1"}
        llm = fake_llm_factory([
            make_ai_message(tool_calls=[tool_call]),
            make_ai_message(content="terminé"),
        ])
        monkeypatch.setattr("graph.nodes.get_groq_llm", lambda temperature=0.2: llm)
        monkeypatch.setattr(
            "graph.nodes.RAG_TOOL_DISPATCH",
            {"search_horror_movies": lambda args: "Aucun film trouvé dans la base de données."},
        )

        result = rag_node({"user_question": "Parle-moi d'un film totalement obscur"})

        assert result["rag_sufficient"] is False
        assert result["tools_used"] == ["search_horror_movies"]

    def test_no_tool_call_stops_loop_immediately(self, monkeypatch, fake_llm_factory):
        llm = fake_llm_factory([make_ai_message(content="Je ne sais pas.")])
        monkeypatch.setattr("graph.nodes.get_groq_llm", lambda temperature=0.2: llm)

        result = rag_node({"user_question": "Question quelconque"})

        assert result["tools_used"] == []
        assert result["rag_context"] == "Je ne sais pas."
        assert result["rag_sufficient"] is True  # pas de marqueur d'échec dans "Je ne sais pas."

    def test_groq_bad_request_error_stops_gracefully(self, monkeypatch, fake_llm_factory):
        class RaisingLLM:
            def bind_tools(self, *a, **k):
                return self

            def invoke(self, messages):
                raise _bad_request_error()

        monkeypatch.setattr("graph.nodes.get_groq_llm", lambda temperature=0.2: RaisingLLM())

        result = rag_node({"user_question": "Question quelconque"})

        assert result["rag_context"] == ""
        assert result["rag_sufficient"] is False
        assert result["tools_used"] == []

    def test_stops_after_max_tool_rounds(self, monkeypatch, fake_llm_factory):
        """3 tours de tool-call max (_MAX_TOOL_ROUNDS) : la boucle ne tourne
        jamais indéfiniment même si le LLM redemande sans cesse un outil."""
        tool_call = {"name": "search_horror_movies", "args": {"query": "x"}, "id": "1"}
        always_tool_call = make_ai_message(tool_calls=[tool_call])
        llm = fake_llm_factory([always_tool_call])  # toujours la même réponse
        monkeypatch.setattr("graph.nodes.get_groq_llm", lambda temperature=0.2: llm)
        monkeypatch.setattr(
            "graph.nodes.RAG_TOOL_DISPATCH",
            {"search_horror_movies": lambda args: "Titre : X"},
        )

        result = rag_node({"user_question": "Question quelconque"})

        assert len(llm.invocations) == 3
        assert result["tools_used"] == ["search_horror_movies"] * 3


# ---------------------------------------------------------------------------
# scraper_node
# ---------------------------------------------------------------------------

class TestScraperNode:
    def test_calls_detailed_synopsis_when_tool_requested(self, monkeypatch, fake_llm_factory):
        tool_call = {"name": "detailed_synopsis", "args": {"movie_name": "Shining"}, "id": "1"}
        llm = fake_llm_factory([make_ai_message(tool_calls=[tool_call])])
        monkeypatch.setattr("graph.nodes.get_groq_llm", lambda temperature=0.0: llm)
        monkeypatch.setattr(
            "graph.nodes.SCRAPER_TOOL_DISPATCH",
            {"detailed_synopsis": lambda args: "Source Wikipedia — Shining : ..."},
        )

        result = scraper_node({"user_question": "Dis-m'en plus sur Shining"})

        assert result["tools_used"] == ["detailed_synopsis"]
        assert "Wikipedia" in result["scraper_context"]

    def test_no_tool_call_returns_empty_context(self, monkeypatch, fake_llm_factory):
        llm = fake_llm_factory([make_ai_message(content="rien à ajouter")])
        monkeypatch.setattr("graph.nodes.get_groq_llm", lambda temperature=0.0: llm)

        result = scraper_node({"user_question": "Question quelconque"})

        assert result["scraper_context"] == ""
        assert result["tools_used"] == []

    def test_groq_bad_request_error_returns_empty_context(self, monkeypatch):
        class RaisingLLM:
            def bind_tools(self, *a, **k):
                return self

            def invoke(self, messages):
                raise _bad_request_error()

        monkeypatch.setattr("graph.nodes.get_groq_llm", lambda temperature=0.0: RaisingLLM())

        result = scraper_node({"user_question": "Question quelconque"})

        assert result == {"scraper_context": "", "tools_used": []}


# ---------------------------------------------------------------------------
# narration_node
# ---------------------------------------------------------------------------

class TestNarrationNode:
    def test_romances_rag_and_scraper_context(self, monkeypatch, fake_llm_factory):
        llm = fake_llm_factory([make_ai_message(content="Il était une fois, dans les ténèbres...")])
        monkeypatch.setattr("graph.nodes.get_groq_llm", lambda temperature=0.85: llm)

        result = narration_node({
            "user_question": "Parle-moi de Shining",
            "rag_context": "Titre : Shining (1980)",
            "scraper_context": "Anecdote : tourné aux studios Elstree.",
        })

        assert result["tools_used"] == ["narration-llm"]
        assert result["messages"][0].content == "Il était une fois, dans les ténèbres..."
        # Le prompt envoyé au LLM contient bien la synthèse des deux agents en amont
        sent_content = llm.invocations[0][1].content
        assert "Shining" in sent_content
        assert "Elstree" in sent_content

    def test_falls_back_to_general_knowledge_when_no_data(self, monkeypatch, fake_llm_factory):
        llm = fake_llm_factory([make_ai_message(content="Une réponse honnête et incertaine.")])
        monkeypatch.setattr("graph.nodes.get_groq_llm", lambda temperature=0.85: llm)

        result = narration_node({
            "user_question": "Un film obscur",
            "rag_context": "",
            "scraper_context": "",
        })

        sent_content = llm.invocations[0][1].content
        assert "connaissance générale" in sent_content
        assert result["messages"][0].content == "Une réponse honnête et incertaine."
