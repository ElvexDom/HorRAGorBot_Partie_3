"""
Fixtures partagées — isolent tous les tests des services externes réels
(Groq, Couche Données / data_api, FAISS, Wikipedia). Aucun test de ce projet
ne doit déclencher un appel réseau ou consommer un vrai budget d'API.
"""
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


class FakeDataApi:
    """Double de tools/data_api_client.py — configure les réponses de
    `search_film` (un film ou None) et `get_films_by_ids` (une liste, ou
    lève RuntimeError si `.unreachable()` a été appelé, pour simuler une
    Couche Données injoignable)."""

    def __init__(self):
        self.film: dict | None = None
        self.films: list[dict] = []
        self._raise = False

    def set_film(self, film: dict | None):
        self.film = film

    def set_films(self, films: list[dict]):
        self.films = films

    def unreachable(self):
        self._raise = True

    def search_film(self, title: str) -> dict | None:
        return self.film

    def get_films_by_ids(self, ids: list[int]) -> list[dict]:
        if self._raise:
            raise RuntimeError("Data API inaccessible (base en pause ?)")
        return self.films


@pytest.fixture
def fake_data_api(monkeypatch):
    """Monkeypatch tools.data_api_client.search_film / get_films_by_ids —
    tous les tools y accèdent via `from tools import data_api_client` (accès
    qualifié), donc ce monkeypatch global les affecte tous."""
    fake = FakeDataApi()
    monkeypatch.setattr("tools.data_api_client.search_film", fake.search_film)
    monkeypatch.setattr("tools.data_api_client.get_films_by_ids", fake.get_films_by_ids)
    return fake
