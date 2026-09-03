"""
Accès base de données — Couche Données (HorRAGor 1).

Réutilise les modèles ORM déjà définis pour le pipeline d'ingestion
(app/models/database.py) plutôt que d'en dupliquer le schéma. Connexion
pilotée par `settings.DATABASE_URL` (app/config/config.py), compatible
SQLite (dev/tests) et PostgreSQL (production/Supabase).
"""
from collections.abc import Generator

from sqlalchemy import create_engine, func, or_
from sqlalchemy.orm import Session, sessionmaker

from app.config.config import settings
from app.models.database import AnalyseSpark, Film
from data_api.schemas import Evaluations, FilmDetail

engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def find_film_by_title(session: Session, title: str) -> Film | None:
    """Correspondance floue sur title/original_title. Ordre : correspondance
    exacte d'abord, puis popularité décroissante — réplique la logique
    dupliquée dans les 6 anciens tools SQL directs."""
    pattern = f"%{title}%"
    return (
        session.query(Film)
        .filter(or_(Film.title.ilike(pattern), Film.original_title.ilike(pattern)))
        .order_by(
            (func.lower(Film.title) == title.lower()).desc(),
            (func.lower(Film.original_title) == title.lower()).desc(),
            Film.popularity.desc().nulls_last(),
        )
        .first()
    )


def get_films_by_ids(session: Session, ids: list[int]) -> dict[int, Film]:
    films = session.query(Film).filter(Film.id.in_(ids)).all()
    return {film.id: film for film in films}


def to_film_detail(film: Film) -> FilmDetail:
    evaluations = Evaluations()
    for e in film.evaluations:
        if e.source_name == "TMDB":
            evaluations.tmdb = e.score_value
        elif e.source_name == "IMDB":
            evaluations.imdb = e.score_value
        elif e.source_name == "Rotten Tomatoes" and e.score_type == "Critic":
            evaluations.rt_critic = e.score_value
        elif e.source_name == "Rotten Tomatoes" and e.score_type == "Audience":
            evaluations.rt_audience = e.score_value

    analyse: AnalyseSpark | None = film.analyse_spark
    horror_keywords = list(analyse.horror_keywords) if analyse and analyse.horror_keywords else []
    richness_score = analyse.richness_score if analyse else None

    return FilmDetail(
        id=film.id,
        title=film.title,
        original_title=film.original_title,
        release_date=film.release_date,
        overview=film.overview,
        popularity=film.popularity,
        genres=[g.name for g in film.genres],
        evaluations=evaluations,
        horror_keywords=horror_keywords,
        richness_score=richness_score,
    )
