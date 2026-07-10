"""
Script standalone — enrichissement Kaggle via SparkKaggleService.

Charge les fichiers splittés avec SparkKaggleService, fait le matching MDM
avec les films déjà en base, et met à jour UNIQUEMENT la table source
(traçabilité). Ne touche ni aux films ni aux évaluations RT.

Prérequis :
  python create_kaggle_splits.py   (si pas déjà fait)

Usage :
  python run_spark_kaggle.py
"""
import re
from typing import List, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config.config import settings
from app.utils.logger import logger
from app.models.database import Film, Source
from app.models.schema import MovieGold
from app.services.spark_kaggle_service import SparkKaggleService


engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=300)


# ---------------------------------------------------------------------------
# Helpers MDM (repris de main.py)
# ---------------------------------------------------------------------------

def _levenshtein(s1: str, s2: str) -> int:
    s1, s2 = s1.lower().strip(), s2.lower().strip()
    if s1 == s2:
        return 0
    if len(s1) < len(s2):
        s1, s2 = s2, s1
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (c1 != c2)))
        prev = curr
    return prev[-1]


def _find_match(target_tmdb_id, target_imdb_id, target_title, target_year,
                by_tmdb: dict, by_imdb: dict, all_kaggle: list,
                threshold: int = 2) -> Optional[MovieGold]:
    """Matching 3 niveaux MDM sur les données Kaggle."""
    if target_tmdb_id and target_tmdb_id in by_tmdb:
        return by_tmdb[target_tmdb_id]
    if target_imdb_id and target_imdb_id in by_imdb:
        return by_imdb[target_imdb_id]
    # Fuzzy
    best, best_dist = None, threshold + 1
    for c in all_kaggle:
        year_c = c.release_date[:4] if c.release_date else None
        if target_year and year_c and target_year != year_c:
            continue
        dist = _levenshtein(target_title or "", c.title or "")
        if dist < best_dist:
            best, best_dist = c, dist
    return best if best_dist <= threshold else None


# ---------------------------------------------------------------------------
# Script principal
# ---------------------------------------------------------------------------

def run() -> None:
    # 1. Charger les films Kaggle via SparkKaggleService
    svc = SparkKaggleService()
    if not svc.is_available():
        logger.error("Splits absents. Lance d'abord : python create_kaggle_splits.py")
        return

    logger.info("=== CHARGEMENT KAGGLE SPLITS (SparkKaggleService) ===")
    kaggle_movies = svc.get_all_movies()
    logger.info(f"  {len(kaggle_movies)} films Kaggle charges")

    # Index pour lookups O(1)
    by_tmdb = {m.tmdb_id: m for m in kaggle_movies if m.tmdb_id}
    by_imdb = {m.imdb_id: m for m in kaggle_movies if m.imdb_id}

    # 2. Charger tous les films de la DB
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        db_films = session.query(Film).all()
        logger.info(f"  {len(db_films)} films en base DB")
    finally:
        session.close()

    # 3. Matching + mise à jour table source
    logger.info("=== MATCHING MDM + MISE A JOUR TABLE SOURCE ===")
    matched = 0
    updated = 0

    # Traitement par batch de 100 pour éviter les timeouts Supabase
    BATCH = 100
    for i in range(0, len(db_films), BATCH):
        batch = db_films[i:i + BATCH]
        session = Session()
        try:
            for film in batch:
                year = str(film.release_date.year) if film.release_date else None
                kaggle_match = _find_match(
                    film.tmdb_id, film.imdb_id, film.title, year,
                    by_tmdb, by_imdb, kaggle_movies,
                )

                if not kaggle_match:
                    continue

                matched += 1

                # Déterminer les champs contribués par Kaggle
                fields = []
                if kaggle_match.overview:
                    fields.append("overview")
                if kaggle_match.vote_average is not None:
                    fields.append("vote_average")
                if kaggle_match.popularity is not None:
                    fields.append("popularity")
                if not fields:
                    fields = ["genres"]

                # Upsert dans la table source (source_name="Kaggle-Spark")
                existing = session.query(Source).filter(
                    Source.film_id == film.id,
                    Source.source_name == "Kaggle-Spark",
                ).first()

                if existing:
                    existing.contributed_fields = list(set(fields))
                else:
                    session.add(Source(
                        film_id=film.id,
                        source_name="Kaggle-Spark",
                        contributed_fields=list(set(fields)),
                    ))
                updated += 1

            session.commit()
            logger.info(f"  Batch {i//BATCH + 1} commite ({i + len(batch)}/{len(db_films)})")
        except Exception as e:
            session.rollback()
            logger.error(f"Erreur batch {i//BATCH + 1} : {e}")
            raise
        finally:
            session.close()

    logger.info(f"\n[OK] {matched}/{len(db_films)} films matches avec Kaggle splits")
    logger.info(f"     {updated} enregistrements source 'Kaggle-Spark' inseres/mis a jour")


if __name__ == "__main__":
    run()
