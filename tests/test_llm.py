"""
Tests unitaires de graph/llm.py — le client Groq partagé par les nœuds.
"""
import pytest

from graph.llm import get_groq_llm


def test_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        get_groq_llm()


def test_returns_chat_groq_client_when_key_configured(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-tests")

    llm = get_groq_llm(temperature=0.3)

    assert llm.temperature == 0.3
    assert llm.model_name == "llama-3.3-70b-versatile"
