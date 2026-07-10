"""
Service de persistance — Gold Layer → Supabase (PostgreSQL).

Sauvegarde les 6 tables dans cet ordre :
  1. Genre       → upsert global des genres avant tout
  2. Film        → upsert sur tmdb_id (création ou mise à jour)
  3. Evaluation  → delete + re-insert (scores TMDB, IMDB, RT)
  4. AnalyseSpark→ upsert sur film_id (analyses textuelles Spark)
  5. Source      → delete + re-insert (traçabilité MDM)

Stratégie upsert :
  On query d'abord, on crée si absent, sinon on met à jour.
  Pas d'ON CONFLICT SQL car SQLAlchemy ORM gère mieux les relations.
"""
import json
import datetime
from typing import List

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from app.config.config import settings
from app.utils.logger import logger
from app.models.schema import MovieGold
from app.models.database import Base, Film, Genre, Evaluation, AnalyseSpark, Source

# Connexion persistante au niveau module (réutilisée pour tous les appels)
engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """
    Crée toutes les tables (Film, Genre, Evaluation, etc.) si elles n'existent pas.
    Idempotent : sans effet si les tables existent déjà (CREATE TABLE IF NOT EXISTS).
    """
    logger.info("Initialisation de la base de données...")
    Base.metadata.create_all(bind=engine)
    logger.info("Tables prêtes.")


def parse_date(date_str: str) -> datetime.date | None:
    """
    Convertit une chaîne de date en objet Python datetime.date.
    Gère deux formats :
      "YYYY"       → 1er janvier de l'année (ex: "1982" → date(1982, 1, 1))
      "YYYY-MM-DD" → date exacte (ex: "2018-06-07" → date(2018, 6, 7))
    Retourne None si la chaîne est absente ou invalide.
    """
    if not date_str:
        return None
    try:
        if len(date_str) == 4:
            return datetime.date(int(date_str), 1, 1)
        return datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None


def save_movies_to_db(movies: List[MovieGold]) -> None:
    """
    Persiste le Gold Layer complet dans Supabase.

    Flux pour chaque film :
      1. Upsert Film (création ou mise à jour si tmdb_id existe déjà)
      2. Delete + re-insert Evaluations (TMDB / IMDB / RT)
      3. Upsert AnalyseSpark si données Spark disponibles
      4. Delete + re-insert Sources (traçabilité MDM)

    Tout est commité en une seule transaction par appel.
    En cas d'erreur → rollback complet.
    """
    init_db()
    db = SessionLocal()
    try:
        logger.info(f"Ingestion de {len(movies)} films en base...")

        # ------------------------------------------------------------------
        # Étape 1 : Upsert global des genres
        # On collecte tous les genres de tous les films avant de commencer,
        # pour éviter des requêtes répétées en boucle sur la table genre.
        # ------------------------------------------------------------------
        all_genre_names: set = set()
        for movie in movies:
            all_genre_names.update(movie.genres)

        # genre_map : dict nom → objet Genre ORM (pour affecter les relations)
        genre_map: dict = {}
        for name in all_genre_names:
            g = db.query(Genre).filter(Genre.name == name).first()
            if not g:
                g = Genre(name=name)
                db.add(g)
                db.flush()   # flush pour obtenir l'id sans commit
            genre_map[name] = g

        # ------------------------------------------------------------------
        # Étape 2 : Films + dépendants
        # ------------------------------------------------------------------
        for movie in movies:

            # --- Upsert Film ---
            db_film = db.query(Film).filter(Film.tmdb_id == movie.tmdb_id).first()
            if not db_film:
                db_film = Film(tmdb_id=movie.tmdb_id, source_system=movie.source_system)
                db.add(db_film)

            # Mise à jour des champs (même si le film existait déjà)
            db_film.imdb_id        = movie.imdb_id
            db_film.title          = movie.title
            db_film.original_title = movie.original_title
            db_film.release_date   = parse_date(movie.release_date)
            db_film.overview       = movie.overview
            db_film.popularity     = movie.popularity
            db_film.genres         = [genre_map[g] for g in movie.genres]
            db.flush()

            # --- Évaluations : delete + re-insert ---
            # On repart de zéro pour éviter les doublons lors des relances du pipeline
            db.query(Evaluation).filter(Evaluation.film_id == db_film.id).delete()

            # source_fields accumule les champs contribués par chaque source
            # pour alimenter ensuite la table Source (traçabilité MDM)
            source_fields: dict = {}

            # Score TMDB (toujours présent si le film vient de TMDB)
            if movie.vote_average is not None:
                db.add(Evaluation(
                    film_id=db_film.id,
                    source_name="TMDB",
                    score_type="User",
                    score_value=movie.vote_average,
                    score_scale=10.0,
                ))
                source_fields["TMDB"] = ["title", "overview", "release_date",
                                         "vote_average", "popularity", "genres"]

            # Score IMDB (stocké dans __dict__ par enrich_with_imdb dans main.py)
            imdb_rating = movie.__dict__.get("imdb_rating")
            if imdb_rating is not None:
                db.add(Evaluation(
                    film_id=db_film.id,
                    source_name="IMDB",
                    score_type="User",
                    score_value=float(imdb_rating),
                    score_scale=10.0,
                ))
                source_fields["IMDB"] = ["imdb_id", "imdb_rating"]

            # Tomatometer Rotten Tomatoes (stocké dans __dict__ par enrich_with_rt ou enrich_rt.py)
            rt_tomatometer = movie.__dict__.get("rt_tomatometer")
            if rt_tomatometer is not None:
                db.add(Evaluation(
                    film_id=db_film.id,
                    source_name="Rotten Tomatoes",
                    score_type="Critic",
                    score_value=float(rt_tomatometer),
                    score_scale=100.0,
                    review_text=movie.__dict__.get("rt_critics_consensus"),
                    source_url=movie.__dict__.get("rt_url"),
                ))
                source_fields.setdefault("Rotten Tomatoes", []).append("tomatometer_score")
                source_fields.setdefault("Rotten Tomatoes", []).append("critics_consensus")

            # Audience Score Rotten Tomatoes
            rt_audience = movie.__dict__.get("rt_audience_score")
            if rt_audience is not None:
                db.add(Evaluation(
                    film_id=db_film.id,
                    source_name="Rotten Tomatoes",
                    score_type="Audience",
                    score_value=float(rt_audience),
                    score_scale=100.0,
                    source_url=movie.__dict__.get("rt_url"),
                ))
                source_fields.setdefault("Rotten Tomatoes", []).append("audience_score")

            # --- AnalyseSpark : upsert sur film_id ---
            # Les résultats Spark sont stockés dans __dict__ par SparkService.enrich_movies()
            horror_kw  = movie.__dict__.get("horror_keywords")
            detected   = movie.__dict__.get("detected_language")
            word_count = movie.__dict__.get("overview_word_count")

            if horror_kw is not None or detected is not None:
                existing = db.query(AnalyseSpark).filter(
                    AnalyseSpark.film_id == db_film.id
                ).first()
                if not existing:
                    existing = AnalyseSpark(film_id=db_film.id)
                    db.add(existing)

                existing.detected_language   = detected
                existing.overview_word_count = word_count
                existing.richness_score      = min(100, (word_count or 0) * 2)
                # horror_keywords est une str JSON produite par _extract_horror_keywords()
                try:
                    existing.horror_keywords = json.loads(horror_kw) if horror_kw else []
                except (json.JSONDecodeError, TypeError):
                    existing.horror_keywords = []

                source_fields["Spark"] = [
                    "detected_language", "overview_word_count",
                    "horror_keywords", "richness_score",
                ]

            # --- Source (traçabilité MDM) : delete + re-insert ---
            db.query(Source).filter(Source.film_id == db_film.id).delete()
            for src_name, fields in source_fields.items():
                db.add(Source(
                    film_id=db_film.id,
                    source_name=src_name,
                    contributed_fields=list(set(fields)),   # dédoublonner les champs
                ))

        db.commit()
        logger.info("Ingestion terminée avec succès.")

    except Exception as e:
        db.rollback()
        logger.error(f"Erreur lors de l'insertion en base : {e}")
        raise
    finally:
        db.close()
