"""
Tests unitaires de tools/data_api_client.py — le client HTTP vers la Couche
Données. httpx est mocké : ces tests vérifient le contrat du client
(succès, 404, service injoignable), pas un vrai réseau.
"""
from unittest.mock import MagicMock

import httpx
import pytest

from tools import data_api_client


class TestSearchFilm:
    def test_returns_parsed_json_on_success(self, monkeypatch):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"id": 1, "title": "Halloween"}
        monkeypatch.setattr("httpx.get", lambda *a, **k: resp)

        result = data_api_client.search_film("Halloween")

        assert result == {"id": 1, "title": "Halloween"}

    def test_returns_none_on_404(self, monkeypatch):
        resp = MagicMock()
        resp.status_code = 404
        monkeypatch.setattr("httpx.get", lambda *a, **k: resp)

        result = data_api_client.search_film("Film inconnu")

        assert result is None

    def test_returns_none_when_data_api_unreachable(self, monkeypatch):
        def raising_get(*a, **k):
            raise httpx.ConnectError("connexion refusée")

        monkeypatch.setattr("httpx.get", raising_get)

        result = data_api_client.search_film("Halloween")

        assert result is None


class TestGetFilmsByIds:
    def test_returns_empty_list_for_empty_input(self):
        assert data_api_client.get_films_by_ids([]) == []

    def test_returns_parsed_json_on_success(self, monkeypatch):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = [{"id": 1}, {"id": 2}]
        monkeypatch.setattr("httpx.get", lambda *a, **k: resp)

        result = data_api_client.get_films_by_ids([1, 2])

        assert result == [{"id": 1}, {"id": 2}]

    def test_raises_runtime_error_when_data_api_unreachable(self, monkeypatch):
        def raising_get(*a, **k):
            raise httpx.ConnectError("connexion refusée")

        monkeypatch.setattr("httpx.get", raising_get)

        with pytest.raises(RuntimeError):
            data_api_client.get_films_by_ids([1, 2])
