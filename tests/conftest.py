"""
Fixtures partagées — isolent tous les tests des services externes réels
(Groq, PostgreSQL, FAISS, Wikipedia). Aucun test de ce projet ne doit
déclencher un appel réseau ou consommer un vrai budget d'API.
"""
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage


class FakeLLM:
    """Double d'un ChatGroq lié à des tools. `responses` est consommée dans
    l'ordre à chaque appel `.invoke()` (une réponse par tour de boucle
    tool-use). La dernière réponse est réutilisée si on invoque plus de fois
    que prévu."""

    def __init__(self, responses: list[AIMessage]):
        self._responses = list(responses)
        self.invocations: list[list] = []

    def bind_tools(self, *args, **kwargs):
        return self

    def invoke(self, messages):
        self.invocations.append(messages)
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]


def make_ai_message(content: str = "", tool_calls: list[dict] | None = None) -> AIMessage:
    """Construit un AIMessage avec ou sans tool_calls, comme le ferait Groq."""
    return AIMessage(content=content, tool_calls=tool_calls or [])


@pytest.fixture
def fake_llm_factory():
    """Fixture retournant le constructeur FakeLLM, pour que chaque test
    fabrique la séquence de réponses qui lui convient."""
    return FakeLLM


class FakeCursor:
    """Double d'un curseur psycopg2 (RealDictCursor). `rows` est la liste
    de dicts renvoyée par le prochain fetchone()/fetchall()."""

    def __init__(self, rows: list[dict] | None = None):
        self._rows = rows or []

    def execute(self, *args, **kwargs):
        pass

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, rows: list[dict] | None = None):
        self._rows = rows or []

    def cursor(self, cursor_factory=None):
        return FakeCursor(self._rows)

    def close(self):
        pass


@pytest.fixture
def fake_db(monkeypatch):
    """Monkeypatch `psycopg2.connect` pour tous les modules qui l'importent
    directement (`import psycopg2` puis `psycopg2.connect(...)`). Fixe aussi
    DATABASE_URL pour passer le garde-fou `_get_conn()` de chaque tool, quel
    que soit le contenu réel du `.env` local. Retourne une fonction
    `set_rows(rows)` pour configurer la réponse du prochain appel DB."""
    state = {"rows": []}

    def fake_connect(*args, **kwargs):
        return FakeConnection(state["rows"])

    monkeypatch.setattr("psycopg2.connect", fake_connect)
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")

    def set_rows(rows: list[dict]):
        state["rows"] = rows

    return set_rows
