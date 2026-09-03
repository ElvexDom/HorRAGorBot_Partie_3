"""
Tests de l'API FastAPI HorRAGor BOT (main_api.py).
Le graphe multi-agent (agent_graph.ainvoke), Le Juge (judge_and_retry) et le
chargement du retriever FAISS au démarrage sont mockés : ces tests vérifient
le contrat HTTP de l'API, pas le comportement du graphe (couvert par
tests/test_graph_pipeline.py) ni celui du LLM.
"""
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

import main_api
from main_api import ChatRequest, ChatResponse, JudgeVerdict


@pytest.fixture
def client(monkeypatch):
    """TestClient avec le retriever FAISS/SentenceTransformer neutralisé au
    démarrage (lifespan) — sinon chaque test chargerait un vrai modèle."""
    monkeypatch.setattr(main_api, "initialize_retriever", lambda: None)
    with TestClient(main_api.app) as c:
        yield c


def _mock_graph_result(answer: str = "Réponse fabriquée.", tools_used: list[str] | None = None):
    async def _fake_ainvoke(initial_state, config=None):
        return {
            "messages": [*initial_state["messages"], AIMessage(content=answer)],
            "tools_used": tools_used or [],
        }
    return _fake_ainvoke


def _mock_judge(is_valid: bool = True, confidence: float = 0.9, reasoning: str = "ok"):
    def _fake_judge(question, answer, tools_used):
        return answer, {"is_valid": is_valid, "confidence": confidence, "reasoning": reasoning}
    return _fake_judge


class TestHealthEndpoint:
    def test_health_check_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestRootEndpoint:
    def test_root_returns_service_metadata(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert response.json()["name"] == "HorRAGor BOT API"


class TestChatEndpoint:
    def test_chat_with_valid_request(self, client, monkeypatch):
        monkeypatch.setattr(main_api, "agent_graph", main_api.agent_graph)
        monkeypatch.setattr(main_api.agent_graph, "ainvoke", _mock_graph_result(tools_used=["search_horror_movies"]))
        monkeypatch.setattr(main_api, "judge_and_retry", _mock_judge())

        payload = {
            "question": "Recommande-moi un film d'horreur",
            "user_id": "test_user",
            "conversation_id": "test_conv",
        }
        response = client.post("/chat", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["answer"] == "Réponse fabriquée."
        assert data["tools_used"] == ["search_horror_movies"]
        assert data["conversation_id"] == "test_conv"

    def test_chat_with_minimal_request(self, client, monkeypatch):
        monkeypatch.setattr(main_api.agent_graph, "ainvoke", _mock_graph_result())
        monkeypatch.setattr(main_api, "judge_and_retry", _mock_judge())

        response = client.post("/chat", json={"question": "Parle-moi de The Shining"})

        assert response.status_code == 200
        assert response.json()["answer"] == "Réponse fabriquée."

    def test_chat_with_empty_question(self, client):
        response = client.post("/chat", json={"question": ""})
        assert response.status_code == 422

    def test_chat_with_missing_question(self, client):
        response = client.post("/chat", json={"user_id": "test"})
        assert response.status_code == 422

    def test_chat_with_very_long_question(self, client):
        response = client.post("/chat", json={"question": "x" * 5001})
        assert response.status_code == 422

    def test_chat_response_structure_includes_judge_verdict(self, client, monkeypatch):
        monkeypatch.setattr(main_api.agent_graph, "ainvoke", _mock_graph_result())
        monkeypatch.setattr(main_api, "judge_and_retry", _mock_judge(confidence=0.42, reasoning="incertain"))

        response = client.post("/chat", json={"question": "Test question"})

        data = response.json()
        verdict = data["judge_verdict"]
        assert verdict["is_valid"] is True
        assert verdict["confidence"] == 0.42
        assert verdict["reasoning"] == "incertain"

    def test_chat_falls_back_to_anonymous_conversation_id(self, client, monkeypatch):
        monkeypatch.setattr(main_api.agent_graph, "ainvoke", _mock_graph_result())
        monkeypatch.setattr(main_api, "judge_and_retry", _mock_judge())

        response = client.post("/chat", json={"question": "Test"})

        assert response.json()["conversation_id"] == "conv_anonymous"

    def test_chat_missing_groq_key_returns_500(self, client, monkeypatch):
        async def _raise_value_error(initial_state, config=None):
            raise ValueError("GROQ_API_KEY manquante")

        monkeypatch.setattr(main_api.agent_graph, "ainvoke", _raise_value_error)

        response = client.post("/chat", json={"question": "Test"})

        assert response.status_code == 500
        assert "GROQ_API_KEY" in response.json()["detail"]

    def test_invalid_json_returns_422(self, client):
        response = client.post(
            "/chat", data="invalid json", headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422

    def test_unexpected_error_returns_500(self, client, monkeypatch):
        async def _raise_runtime_error(initial_state, config=None):
            raise RuntimeError("panne inattendue")

        monkeypatch.setattr(main_api.agent_graph, "ainvoke", _raise_runtime_error)

        response = client.post("/chat", json={"question": "Test"})

        assert response.status_code == 500
        assert "panne inattendue" in response.json()["detail"]


class TestLangfuseCallbacks:
    def test_disabled_without_keys(self, monkeypatch):
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

        assert main_api._get_langfuse_callbacks() == []

    def test_enabled_when_keys_configured(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

        callbacks = main_api._get_langfuse_callbacks()

        assert len(callbacks) == 1


class TestInfoEndpoint:
    def test_info_returns_agents_and_their_tools(self, client):
        response = client.get("/info")
        assert response.status_code == 200

        data = response.json()
        assert data["architecture"].startswith("multi-agent")
        assert "search_horror_movies" in data["agents"]["rag_node"]
        assert "detailed_synopsis" in data["agents"]["scraper_node"]


class TestPydanticModels:
    def test_chat_request_validation(self):
        req = ChatRequest(question="Test question")
        assert req.question == "Test question"

        with pytest.raises(ValueError):
            ChatRequest(question="")

        with pytest.raises(ValueError):
            ChatRequest(question="x" * 6000)

    def test_judge_verdict_validation(self):
        verdict = JudgeVerdict(is_valid=True, confidence=0.85, reasoning="Test reasoning")
        assert verdict.is_valid is True
        assert verdict.confidence == 0.85

        with pytest.raises(ValueError):
            JudgeVerdict(is_valid=True, confidence=1.5, reasoning="Test")

    def test_chat_response_validation(self):
        response = ChatResponse(
            answer="Test answer",
            conversation_id="conv123",
            tools_used=["tool1", "tool2"],
            judge_verdict=JudgeVerdict(is_valid=True, confidence=0.9, reasoning="Valid"),
        )
        assert response.answer == "Test answer"
        assert len(response.tools_used) == 2
