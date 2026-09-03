"""
Tests unitaires des outils appelés par les agents (tools/*.py).
PostgreSQL, FAISS et Wikipedia sont mockés — aucun appel réseau réel.
"""
import datetime
from unittest.mock import MagicMock

import numpy as np
import pytest

from tools.calculate_movie_age import calculate_movie_age
from tools.horror_survival_simulator import get_survival_context
from tools.query_movie_metadata import query_movie_metadata
from tools.find_similar_horror_movies import find_similar_horror_movies
from tools.scrape_detailed_synopsis import scrape_detailed_synopsis
from tools.rag_tool import search_horror_movies
from tools.scraper_tool import SCRAPER_TOOL_DISPATCH, run_scraper


# ---------------------------------------------------------------------------
# calculate_movie_age
# ---------------------------------------------------------------------------

class TestCalculateMovieAge:
    def test_found_computes_exact_age(self, fake_db):
        release = datetime.date(1978, 10, 25)
        fake_db([{"title": "Halloween", "original_title": None, "release_date": release}])

        result = calculate_movie_age("Halloween")

        today = datetime.date.today()
        expected_age = today.year - release.year - ((today.month, today.day) < (release.month, release.day))
        assert "Halloween" in result
        assert f"Il y a exactement {expected_age} an" in result

    def test_not_found_returns_clear_message(self, fake_db):
        fake_db([])

        result = calculate_movie_age("Film inconnu")

        assert "introuvable dans la base de données" in result

    def test_missing_release_date(self, fake_db):
        fake_db([{"title": "Film sans date", "original_title": None, "release_date": None}])

        result = calculate_movie_age("Film sans date")

        assert "n'est pas renseignée" in result

    def test_db_error_returns_fallback_message(self, monkeypatch):
        def raising_connect(*a, **k):
            raise RuntimeError("connexion refusée")

        monkeypatch.setattr("psycopg2.connect", raising_connect)
        monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")

        result = calculate_movie_age("Halloween")

        assert "Impossible de calculer l'âge" in result


# ---------------------------------------------------------------------------
# query_movie_metadata
# ---------------------------------------------------------------------------

class TestQueryMovieMetadata:
    def test_found_formats_all_fields(self, fake_db):
        fake_db([{
            "title": "The Shining", "original_title": "The Shining", "year": 1980,
            "overview": "Un écrivain sombre dans la folie.",
            "genres": ["Horror", "Thriller"],
            "tmdb_score": 8.4, "imdb_score": 8.4, "rt_critic": 84, "rt_audience": 88,
        }])

        result = query_movie_metadata("The Shining")

        assert "The Shining" in result
        assert "1980" in result
        assert "Horror, Thriller" in result
        assert "TMDB : 8.4/10" in result

    def test_not_found_returns_clear_message(self, fake_db):
        fake_db([])

        result = query_movie_metadata("Film inconnu")

        assert "Aucun film trouvé" in result


# ---------------------------------------------------------------------------
# find_similar_horror_movies
# ---------------------------------------------------------------------------

class TestFindSimilarHorrorMovies:
    def test_no_retriever_returns_explicit_message(self):
        result = find_similar_horror_movies("Halloween", model=None, index=None, id_map=None)
        assert result == "Retriever FAISS non disponible."

    def test_source_film_not_found(self, fake_db):
        fake_db([])
        model, index, id_map = MagicMock(), MagicMock(), np.array([1, 2, 3])

        result = find_similar_horror_movies("Film inconnu", model=model, index=index, id_map=id_map)

        assert "introuvable dans la base de données" in result

    def test_returns_similar_films_excluding_source(self, fake_db):
        fake_db([
            {"id": 1, "title": "Halloween", "original_title": "Halloween",
             "overview": "A masked killer stalks babysitters.", "year": 1978,
             "genres": ["Horror"], "tmdb_score": 7.5},
            {"id": 2, "title": "Halloween II", "original_title": None,
             "overview": "", "year": 1981, "genres": ["Horror", "Thriller"], "tmdb_score": 6.0},
        ])
        model = MagicMock()
        model.encode.return_value = MagicMock(astype=lambda dtype: "vec")
        index = MagicMock()
        index.search.return_value = (None, [[0, 1, 2]])
        id_map = np.array([1, 2, 3])

        result = find_similar_horror_movies("Halloween", k=2, model=model, index=index, id_map=id_map)

        assert "Halloween II" in result
        assert result.startswith("Films similaires")


# ---------------------------------------------------------------------------
# horror_survival_simulator.get_survival_context
# ---------------------------------------------------------------------------

class TestSurvivalContext:
    def test_found_with_list_keywords(self, fake_db):
        fake_db([{
            "title": "Halloween", "original_title": None, "year": 1978,
            "overview": "A masked killer stalks babysitters.",
            "genres": ["Horror"], "horror_keywords": ["knife", "mask", "night"],
            "richness_score": 40,
        }])

        result = get_survival_context("Halloween")

        assert "Halloween" in result
        assert "knife, mask, night" in result
        assert "SIMULATEUR DE SURVIE" in result  # instruction créative bien injectée

    def test_found_with_json_string_keywords(self, fake_db):
        fake_db([{
            "title": "Halloween", "original_title": None, "year": 1978,
            "overview": "...", "genres": ["Horror"],
            "horror_keywords": '["knife", "mask"]', "richness_score": 40,
        }])

        result = get_survival_context("Halloween")

        assert "knife, mask" in result

    def test_not_found(self, fake_db):
        fake_db([])

        result = get_survival_context("Film inconnu")

        assert "introuvable en base" in result


# ---------------------------------------------------------------------------
# scrape_detailed_synopsis
# ---------------------------------------------------------------------------

class TestScrapeDetailedSynopsis:
    def _fake_requests_get(self, search_result=None, extract_text=None):
        def _get(url, params=None, headers=None, timeout=None):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            if params.get("action") == "query" and "srsearch" in params:
                resp.json.return_value = {
                    "query": {"search": [{"title": search_result}] if search_result else []}
                }
            else:
                resp.json.return_value = {
                    "query": {"pages": {"1": {"extract": extract_text or ""}}}
                }
            return resp
        return _get

    def test_success_returns_cleaned_extract(self, monkeypatch, fake_db):
        fake_db([{"title": "Halloween", "original_title": "Halloween"}])
        monkeypatch.setattr(
            "requests.get",
            self._fake_requests_get(search_result="Halloween (film)", extract_text="Un tueur masqué terrorise une petite ville."),
        )

        result = scrape_detailed_synopsis("Halloween")

        assert "Halloween (film)" in result
        assert "tueur masqué" in result

    def test_no_wikipedia_page_found(self, monkeypatch, fake_db):
        fake_db([{"title": "Film inconnu", "original_title": None}])
        monkeypatch.setattr(
            "requests.get",
            self._fake_requests_get(search_result=None),
        )

        result = scrape_detailed_synopsis("Film inconnu")

        assert "Aucune page Wikipedia trouvée" in result

    def test_page_found_but_empty_extract(self, monkeypatch, fake_db):
        fake_db([{"title": "Halloween", "original_title": "Halloween"}])
        monkeypatch.setattr(
            "requests.get",
            self._fake_requests_get(search_result="Halloween (film)", extract_text=""),
        )

        result = scrape_detailed_synopsis("Halloween")

        assert "contenu est vide" in result


# ---------------------------------------------------------------------------
# rag_tool.search_horror_movies
# ---------------------------------------------------------------------------

class TestSearchHorrorMovies:
    def test_formats_faiss_results(self, monkeypatch, fake_db):
        fake_db([{
            "id": 1, "title": "Halloween", "overview": "A masked killer...",
            "release_date": datetime.date(1978, 10, 25), "genres": ["Horror"], "vote_average": 7.5,
        }])
        model, index = MagicMock(), MagicMock()
        model.encode.return_value = MagicMock(astype=lambda dtype: "vec")
        index.search.return_value = (None, [[0]])
        monkeypatch.setattr(
            "tools.rag_tool._get_retriever",
            lambda: (model, index, np.array([1])),
        )

        result = search_horror_movies("un tueur masqué")

        assert "Halloween" in result
        assert "1978" in result

    def test_no_db_url_configured_returns_no_films(self, monkeypatch):
        monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        model, index = MagicMock(), MagicMock()
        model.encode.return_value = MagicMock(astype=lambda dtype: "vec")
        index.search.return_value = (None, [[0]])
        monkeypatch.setattr(
            "tools.rag_tool._get_retriever",
            lambda: (model, index, np.array([1])),
        )

        result = search_horror_movies("un tueur masqué")

        assert result == "Aucun film trouvé dans la base de données."

    def test_db_operational_error_returns_explicit_error_message(self, monkeypatch, fake_db):
        import psycopg2

        def raising_connect(*a, **k):
            raise psycopg2.OperationalError("connexion refusée")

        monkeypatch.setattr("psycopg2.connect", raising_connect)
        monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
        model, index = MagicMock(), MagicMock()
        model.encode.return_value = MagicMock(astype=lambda dtype: "vec")
        index.search.return_value = (None, [[0]])
        monkeypatch.setattr(
            "tools.rag_tool._get_retriever",
            lambda: (model, index, np.array([1])),
        )

        result = search_horror_movies("un tueur masqué")

        assert "[ERREUR BASE DE DONNÉES]" in result

    def test_no_films_found_returns_explicit_message(self, monkeypatch, fake_db):
        fake_db([])
        model, index = MagicMock(), MagicMock()
        model.encode.return_value = MagicMock(astype=lambda dtype: "vec")
        index.search.return_value = (None, [[0]])
        monkeypatch.setattr(
            "tools.rag_tool._get_retriever",
            lambda: (model, index, np.array([1])),
        )

        result = search_horror_movies("film totalement obscur")

        assert result == "Aucun film trouvé dans la base de données."


# ---------------------------------------------------------------------------
# scraper_tool wiring
# ---------------------------------------------------------------------------

class TestScraperTool:
    def test_dispatch_maps_detailed_synopsis_to_scraper(self, monkeypatch):
        monkeypatch.setattr(
            "tools.scraper_tool.scrape_detailed_synopsis",
            lambda movie_name: f"synopsis de {movie_name}",
        )

        result = SCRAPER_TOOL_DISPATCH["detailed_synopsis"]({"movie_name": "Halloween"})

        assert result == "synopsis de Halloween"

    def test_run_scraper_delegates_to_scrape_detailed_synopsis(self, monkeypatch):
        monkeypatch.setattr(
            "tools.scraper_tool.scrape_detailed_synopsis",
            lambda movie_name: f"synopsis de {movie_name}",
        )

        assert run_scraper("Halloween") == "synopsis de Halloween"
