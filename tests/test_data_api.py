"""
Tests d'intégration de la Couche Données (data_api/), contre une vraie base
SQLite temporaire (pas de mock) : ces tests exercent la vraie logique de
recherche floue, de tri et de jointures SQLAlchemy — complètent l'approche
"tout mocké" utilisée côté Couche Intelligence (tests/test_tools.py).
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.database import AnalyseSpark, Base, Evaluation, Film, Genre
from data_api.db import get_session
from data_api.main import app


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "test_data_api.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    TestSessionLocal = sessionmaker(bind=engine)

    def override_get_session():
        session = TestSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    try:
        yield TestClient(app), TestSessionLocal
    finally:
        app.dependency_overrides.clear()


def _seed_film(Session, **overrides) -> Film:
    session = Session()
    try:
        genre = session.query(Genre).filter_by(name="Horror").first()
        if not genre:
            genre = Genre(name="Horror")
            session.add(genre)
            session.flush()

        defaults = dict(
            tmdb_id=overrides.pop("tmdb_id", 1),
            title="Halloween",
            original_title="Halloween",
            release_date=date(1978, 10, 25),
            overview="A masked killer stalks babysitters.",
            popularity=7.5,
            source_system="test",
        )
        defaults.update(overrides)
        film = Film(**defaults, genres=[genre])
        session.add(film)
        session.commit()
        session.refresh(film)
        return film
    finally:
        session.close()


def _seed_evaluation(Session, film_id: int, **kwargs):
    session = Session()
    try:
        session.add(Evaluation(film_id=film_id, **kwargs))
        session.commit()
    finally:
        session.close()


def _seed_analyse(Session, film_id: int, **kwargs):
    session = Session()
    try:
        session.add(AnalyseSpark(film_id=film_id, **kwargs))
        session.commit()
    finally:
        session.close()


class TestGetSessionGenerator:
    def test_yields_a_session_and_closes_it(self, monkeypatch):
        """Exercise data_api.db.get_session() directement (les tests HTTP
        ci-dessous le remplacent via dependency_overrides pour pointer sur
        une base de test, donc son vrai corps n'est autrement jamais couvert)."""
        closed = {"value": False}

        class FakeSession:
            def close(self):
                closed["value"] = True

        import data_api.db as db_module
        monkeypatch.setattr(db_module, "SessionLocal", lambda: FakeSession())

        gen = db_module.get_session()
        session = next(gen)
        assert isinstance(session, FakeSession)
        assert closed["value"] is False

        with pytest.raises(StopIteration):
            next(gen)
        assert closed["value"] is True


class TestHealth:
    def test_health_check(self, client):
        c, _ = client
        response = c.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestSearchFilm:
    def test_returns_404_when_no_match(self, client):
        c, _ = client
        response = c.get("/films/search", params={"title": "Film inconnu"})
        assert response.status_code == 404

    def test_exact_match_preferred_over_partial(self, client):
        c, Session = client
        _seed_film(Session, tmdb_id=1, title="Halloween", popularity=1.0)
        _seed_film(Session, tmdb_id=2, title="Halloween II", popularity=99.0)

        response = c.get("/films/search", params={"title": "Halloween"})

        assert response.status_code == 200
        assert response.json()["title"] == "Halloween"  # exact match, malgré une popularité plus faible

    def test_falls_back_to_most_popular_partial_match(self, client):
        c, Session = client
        _seed_film(Session, tmdb_id=1, title="Halloween II", popularity=1.0)
        _seed_film(Session, tmdb_id=2, title="Halloween III", popularity=99.0)

        response = c.get("/films/search", params={"title": "Halloween"})

        assert response.status_code == 200
        assert response.json()["title"] == "Halloween III"

    def test_response_includes_genres_evaluations_and_keywords(self, client):
        c, Session = client
        film = _seed_film(Session, tmdb_id=1, title="Halloween")
        _seed_evaluation(Session, film.id, source_name="TMDB", score_type="User", score_value=7.5, score_scale=10.0)
        _seed_evaluation(Session, film.id, source_name="IMDB", score_type="User", score_value=7.7, score_scale=10.0)
        _seed_evaluation(Session, film.id, source_name="Rotten Tomatoes", score_type="Critic", score_value=96.0, score_scale=100.0)
        _seed_evaluation(Session, film.id, source_name="Rotten Tomatoes", score_type="Audience", score_value=88.0, score_scale=100.0)
        _seed_analyse(Session, film.id, horror_keywords=["knife", "mask"], richness_score=40)

        data = c.get("/films/search", params={"title": "Halloween"}).json()

        assert data["genres"] == ["Horror"]
        assert data["evaluations"] == {"tmdb": 7.5, "imdb": 7.7, "rt_critic": 96.0, "rt_audience": 88.0}
        assert data["horror_keywords"] == ["knife", "mask"]
        assert data["richness_score"] == 40


class TestBatchFilms:
    def test_preserves_requested_order(self, client):
        c, Session = client
        f1 = _seed_film(Session, tmdb_id=1, title="Halloween")
        f2 = _seed_film(Session, tmdb_id=2, title="Halloween II")
        f3 = _seed_film(Session, tmdb_id=3, title="Halloween III")

        response = c.get("/films/batch", params={"ids": f"{f3.id},{f1.id},{f2.id}"})

        assert response.status_code == 200
        titles = [f["title"] for f in response.json()]
        assert titles == ["Halloween III", "Halloween", "Halloween II"]

    def test_skips_missing_ids_silently(self, client):
        c, Session = client
        f1 = _seed_film(Session, tmdb_id=1, title="Halloween")

        response = c.get("/films/batch", params={"ids": f"{f1.id},9999"})

        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_empty_ids_list_returns_empty(self, client):
        c, _ = client
        response = c.get("/films/batch", params={"ids": ""})
        assert response.status_code == 200
        assert response.json() == []

    def test_invalid_ids_returns_422(self, client):
        c, _ = client
        response = c.get("/films/batch", params={"ids": "abc,def"})
        assert response.status_code == 422
