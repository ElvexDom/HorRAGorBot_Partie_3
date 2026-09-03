"""
Tests unitaires des outils appelés par les agents (tools/*.py).
La Couche Données (data_api_client), FAISS et Wikipedia sont mockés —
aucun appel réseau réel.
"""
from unittest.mock import MagicMock

import numpy as np
import pytest

from tools.calculate_movie_age import calculate_movie_age
from tools.horror_survival_simulator import get_survival_context
from tools.query_movie_metadata import query_movie_metadata
from tools.find_similar_horror_movies import find_similar_horror_movies
from tools.scrape_detailed_synopsis import _clean_and_truncate, scrape_detailed_synopsis
from tools.rag_tool import search_horror_movies
from tools.scraper_tool import SCRAPER_TOOL_DISPATCH, run_scraper


# ---------------------------------------------------------------------------
# calculate_movie_age
# ---------------------------------------------------------------------------

class TestCalculateMovieAge:
    def test_found_computes_exact_age(self, fake_data_api):
        import datetime
        release = datetime.date(1978, 10, 25)
        fake_data_api.set_film({"title": "Halloween", "original_title": None, "release_date": "1978-10-25"})

        result = calculate_movie_age("Halloween")

        today = datetime.date.today()
        expected_age = today.year - release.year - ((today.month, today.day) < (release.month, release.day))
        assert "Halloween" in result
        assert f"Il y a exactement {expected_age} an" in result

    def test_not_found_returns_clear_message(self, fake_data_api):
        fake_data_api.set_film(None)

        result = calculate_movie_age("Film inconnu")

        assert "introuvable dans la base de données" in result

    def test_missing_release_date(self, fake_data_api):
        fake_data_api.set_film({"title": "Film sans date", "original_title": None, "release_date": None})

        result = calculate_movie_age("Film sans date")

        assert "n'est pas renseignée" in result

    def test_data_api_error_returns_fallback_message(self, monkeypatch):
        def raising_search_film(title):
            raise RuntimeError("Data API inaccessible")

        monkeypatch.setattr("tools.data_api_client.search_film", raising_search_film)

        result = calculate_movie_age("Halloween")

        assert "Impossible de calculer l'âge" in result


# ---------------------------------------------------------------------------
# query_movie_metadata
# ---------------------------------------------------------------------------

class TestQueryMovieMetadata:
    def test_found_formats_all_fields(self, fake_data_api):
        fake_data_api.set_film({
            "title": "The Shining", "original_title": "The Shining", "release_date": "1980-05-23",
            "overview": "Un écrivain sombre dans la folie.",
            "genres": ["Horror", "Thriller"],
            "evaluations": {"tmdb": 8.4, "imdb": 8.4, "rt_critic": 84, "rt_audience": 88},
        })

        result = query_movie_metadata("The Shining")

        assert "The Shining" in result
        assert "1980" in result
        assert "Horror, Thriller" in result
        assert "TMDB : 8.4/10" in result

    def test_not_found_returns_clear_message(self, fake_data_api):
        fake_data_api.set_film(None)

        result = query_movie_metadata("Film inconnu")

        assert "Aucun film trouvé" in result


# ---------------------------------------------------------------------------
# find_similar_horror_movies
# ---------------------------------------------------------------------------

class TestFindSimilarHorrorMovies:
    def test_no_retriever_returns_explicit_message(self):
        result = find_similar_horror_movies("Halloween", model=None, index=None, id_map=None)
        assert result == "Retriever FAISS non disponible."

    def test_source_film_not_found(self, fake_data_api):
        fake_data_api.set_film(None)
        model, index, id_map = MagicMock(), MagicMock(), np.array([1, 2, 3])

        result = find_similar_horror_movies("Film inconnu", model=model, index=index, id_map=id_map)

        assert "introuvable dans la base de données" in result

    def test_returns_similar_films_excluding_source(self, fake_data_api):
        fake_data_api.set_film({"id": 1, "title": "Halloween", "overview": "A masked killer stalks babysitters."})
        fake_data_api.set_films([
            {"id": 2, "title": "Halloween II", "original_title": None, "overview": "",
             "release_date": "1981-10-30", "genres": ["Horror", "Thriller"],
             "evaluations": {"tmdb": 6.0}},
        ])
        model = MagicMock()
        model.encode.return_value = MagicMock(astype=lambda dtype: "vec")
        index = MagicMock()
        index.search.return_value = (None, [[0, 1, 2]])
        id_map = np.array([1, 2, 3])

        result = find_similar_horror_movies("Halloween", k=2, model=model, index=index, id_map=id_map)

        assert "Halloween II" in result
        assert result.startswith("Films similaires")

    def test_data_api_unreachable_falls_back_to_no_results_message(self, fake_data_api):
        fake_data_api.set_film({"id": 1, "title": "Halloween", "overview": "A masked killer..."})
        fake_data_api.unreachable()
        model = MagicMock()
        model.encode.return_value = MagicMock(astype=lambda dtype: "vec")
        index = MagicMock()
        index.search.return_value = (None, [[0, 1]])
        id_map = np.array([1, 2])

        result = find_similar_horror_movies("Halloween", model=model, index=index, id_map=id_map)

        assert "Aucun film similaire trouvé" in result


# ---------------------------------------------------------------------------
# horror_survival_simulator.get_survival_context
# ---------------------------------------------------------------------------

class TestSurvivalContext:
    def test_found_with_keywords(self, fake_data_api):
        fake_data_api.set_film({
            "title": "Halloween", "original_title": None, "release_date": "1978-10-25",
            "overview": "A masked killer stalks babysitters.",
            "genres": ["Horror"], "horror_keywords": ["knife", "mask", "night"],
            "richness_score": 40,
        })

        result = get_survival_context("Halloween")

        assert "Halloween" in result
        assert "knife, mask, night" in result
        assert "SIMULATEUR DE SURVIE" in result  # instruction créative bien injectée

    def test_not_found(self, fake_data_api):
        fake_data_api.set_film(None)

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

    def test_success_returns_cleaned_extract(self, monkeypatch, fake_data_api):
        fake_data_api.set_film({"title": "Halloween", "original_title": "Halloween"})
        monkeypatch.setattr(
            "requests.get",
            self._fake_requests_get(search_result="Halloween (film)", extract_text="Un tueur masqué terrorise une petite ville."),
        )

        result = scrape_detailed_synopsis("Halloween")

        assert "Halloween (film)" in result
        assert "tueur masqué" in result

    def test_no_wikipedia_page_found(self, monkeypatch, fake_data_api):
        fake_data_api.set_film({"title": "Film inconnu", "original_title": None})
        monkeypatch.setattr(
            "requests.get",
            self._fake_requests_get(search_result=None),
        )

        result = scrape_detailed_synopsis("Film inconnu")

        assert "Aucune page Wikipedia trouvée" in result

    def test_page_found_but_empty_extract(self, monkeypatch, fake_data_api):
        fake_data_api.set_film({"title": "Halloween", "original_title": "Halloween"})
        monkeypatch.setattr(
            "requests.get",
            self._fake_requests_get(search_result="Halloween (film)", extract_text=""),
        )

        result = scrape_detailed_synopsis("Halloween")

        assert "contenu est vide" in result

    def test_data_api_error_falls_back_to_raw_movie_name(self, monkeypatch):
        def raising_search_film(title):
            raise RuntimeError("Data API inaccessible")

        monkeypatch.setattr("tools.data_api_client.search_film", raising_search_film)
        monkeypatch.setattr("requests.get", self._fake_requests_get(search_result=None))

        result = scrape_detailed_synopsis("Halloween")

        assert "Aucune page Wikipedia trouvée" in result

    def test_wikipedia_network_error_returns_no_page_found(self, monkeypatch, fake_data_api):
        fake_data_api.set_film({"title": "Halloween", "original_title": "Halloween"})

        def raising_get(*a, **k):
            raise ConnectionError("réseau indisponible")

        monkeypatch.setattr("requests.get", raising_get)

        result = scrape_detailed_synopsis("Halloween")

        assert "Aucune page Wikipedia trouvée" in result

    def test_truncates_long_extract_and_strips_references_section(self):
        long_extract = ("Un tueur masqué terrorise une petite ville. " * 100) + "== Références ==\nDivers liens."

        cleaned = _clean_and_truncate(long_extract, max_chars=200)

        assert "Références" not in cleaned
        assert cleaned.endswith("[...] (résumé tronqué)")


# ---------------------------------------------------------------------------
# rag_tool.search_horror_movies
# ---------------------------------------------------------------------------

class TestSearchHorrorMovies:
    def test_formats_faiss_results(self, monkeypatch, fake_data_api):
        fake_data_api.set_films([{
            "id": 1, "title": "Halloween", "overview": "A masked killer...",
            "release_date": "1978-10-25", "genres": ["Horror"], "evaluations": {"tmdb": 7.5},
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

    def test_data_api_unreachable_returns_explicit_error_message(self, monkeypatch, fake_data_api):
        fake_data_api.unreachable()
        model, index = MagicMock(), MagicMock()
        model.encode.return_value = MagicMock(astype=lambda dtype: "vec")
        index.search.return_value = (None, [[0]])
        monkeypatch.setattr(
            "tools.rag_tool._get_retriever",
            lambda: (model, index, np.array([1])),
        )

        result = search_horror_movies("un tueur masqué")

        assert "[ERREUR BASE DE DONNÉES]" in result

    def test_no_films_found_returns_explicit_message(self, monkeypatch, fake_data_api):
        fake_data_api.set_films([])
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
