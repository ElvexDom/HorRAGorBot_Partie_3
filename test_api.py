"""
Tests de l'API FastAPI HorRAGor BOT
"""

import pytest
from fastapi.testclient import TestClient
from main_api import app, ChatRequest, ChatResponse, JudgeVerdict


client = TestClient(app)


class TestHealthEndpoint:
    """Tests de l'endpoint /health"""
    
    def test_health_check_returns_ok(self):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestChatEndpoint:
    """Tests de l'endpoint /chat"""
    
    def test_chat_with_valid_request(self):
        """Test d'une requête valide"""
        payload = {
            "question": "Recommande-moi un film d'horreur",
            "user_id": "test_user",
            "conversation_id": "test_conv"
        }
        
        response = client.post("/chat", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        assert "answer" in data
        assert "tools_used" in data
        assert "conversation_id" in data
        assert isinstance(data["tools_used"], list)
    
    def test_chat_with_minimal_request(self):
        """Test avec seulement la question obligatoire"""
        payload = {"question": "Parle-moi de The Shining"}
        
        response = client.post("/chat", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        assert "answer" in data
    
    def test_chat_with_empty_question(self):
        """Test avec une question vide"""
        payload = {"question": ""}
        
        response = client.post("/chat", json=payload)
        assert response.status_code == 422  # Validation error
    
    def test_chat_with_missing_question(self):
        """Test sans la question"""
        payload = {"user_id": "test"}
        
        response = client.post("/chat", json=payload)
        assert response.status_code == 422  # Validation error
    
    def test_chat_response_structure(self):
        """Test que la réponse a la bonne structure"""
        payload = {
            "question": "Test question",
            "user_id": "user1",
            "conversation_id": "conv1"
        }
        
        response = client.post("/chat", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        
        # Vérifier les champs requis
        assert "answer" in data
        assert isinstance(data["answer"], str)
        assert len(data["answer"]) > 0
        
        assert "tools_used" in data
        assert isinstance(data["tools_used"], list)
        
        assert "conversation_id" in data
        
        # Vérifier le judge_verdict si présent
        if data.get("judge_verdict"):
            verdict = data["judge_verdict"]
            assert "is_valid" in verdict
            assert "confidence" in verdict
            assert "reasoning" in verdict
            assert isinstance(verdict["is_valid"], bool)
            assert 0.0 <= verdict["confidence"] <= 1.0


class TestPydanticModels:
    """Tests de validation des modèles Pydantic"""
    
    def test_chat_request_validation(self):
        """Test la validation de ChatRequest"""
        # Valid request
        req = ChatRequest(question="Test question")
        assert req.question == "Test question"
        
        # Question vide
        with pytest.raises(ValueError):
            ChatRequest(question="")
        
        # Question trop longue
        with pytest.raises(ValueError):
            ChatRequest(question="x" * 6000)
    
    def test_judge_verdict_validation(self):
        """Test la validation de JudgeVerdict"""
        # Valid verdict
        verdict = JudgeVerdict(
            is_valid=True,
            confidence=0.85,
            reasoning="Test reasoning"
        )
        assert verdict.is_valid is True
        assert verdict.confidence == 0.85
        
        # Confidence en dehors de [0, 1]
        with pytest.raises(ValueError):
            JudgeVerdict(
                is_valid=True,
                confidence=1.5,
                reasoning="Test"
            )
    
    def test_chat_response_validation(self):
        """Test la validation de ChatResponse"""
        response = ChatResponse(
            answer="Test answer",
            conversation_id="conv123",
            tools_used=["tool1", "tool2"],
            judge_verdict=JudgeVerdict(
                is_valid=True,
                confidence=0.9,
                reasoning="Valid"
            )
        )
        assert response.answer == "Test answer"
        assert len(response.tools_used) == 2


class TestErrorHandling:
    """Tests de gestion des erreurs"""
    
    def test_chat_with_very_long_question(self):
        """Test avec une question trop longue"""
        payload = {"question": "x" * 5001}
        
        response = client.post("/chat", json=payload)
        assert response.status_code == 422
    
    def test_invalid_json(self):
        """Test avec du JSON invalide"""
        response = client.post(
            "/chat",
            data="invalid json",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422


class TestInfoEndpoint:
    """Tests de l'endpoint /info"""
    
    def test_info_returns_available_tools(self):
        """Test que /info retourne les outils disponibles"""
        response = client.get("/info")
        assert response.status_code == 200
        
        data = response.json()
        assert "available_tools" in data
        assert len(data["available_tools"]) > 0
        assert "query_movie_metadata" in data["available_tools"]
        assert "find_similar_horror_movies" in data["available_tools"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
