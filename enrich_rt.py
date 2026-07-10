"""
Script standalone d'enrichissement Rotten Tomatoes.

Ce script est indépendant du pipeline principal (main.py).
Il peut être relancé autant de fois que nécessaire : il détecte automatiquement
les films déjà enrichis en base et reprend là où il s'est arrêté.

Usage :
  python enrich_rt.py             # 50 films par défaut
  python enrich_rt.py --limit 500 --delay 2.5

Architecture de connexion DB :
  Contrairement à db_service.py qui garde une session ouverte,
  ce script utilise des sessions courtes (une par batch de 10 films)
  pour éviter les timeouts de connexion Supabase après ~40 min d'inactivité.
  pool_pre_ping=True teste la connexion avant chaque usage.
  pool_recycle=300 recycle les connexions toutes les 5 minutes.
"""
import argparse
import time

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config.config import settings
from app.utils.logger import logger
from app.models.database import Film, Evaluation
from app.scrapers.rotten_tomatoes import RottenTomatoesScraper


# Nombre de films réussis avant de flusher vers la DB
# Valeur = 10 : si RT bloque après 30 films, les 20 premiers sont déjà sauvegardés
BATCH_SIZE = 10


def _save_batch(engine, pending: list) -> int:
    """
    Persiste un batch de résultats RT dans une SESSION COURTE.

    Chaque appel ouvre et ferme sa propre session → la connexion
    Supabase ne reste jamais ouverte plus de quelques secondes.
    Cela évite le OperationalError "server closed the connection unexpectedly"
    qui survient quand une session reste idle pendant > 10 minutes.

    :param pending: liste de dicts {"film_id": int, "rt_data": RottenTomatoesData}
    :return: nombre de films sauvegardés
    """
    Session = sessionmaker(bind=engine)
    session = Session()
    saved = 0
    try:
        for item in pending:
            rt_data = item["rt_data"]
            film_id = item["film_id"]

            if rt_data.tomatometer_score is not None:
                session.add(Evaluation(
                    film_id=film_id,
                    source_name="Rotten Tomatoes",
                    score_type="Critic",
                    score_value=float(rt_data.tomatometer_score),
                    score_scale=100.0,
                    review_text=rt_data.critics_consensus,
                    source_url=rt_data.source_url,
                ))
            if rt_data.audience_score is not None:
                session.add(Evaluation(
                    film_id=film_id,
                    source_name="Rotten Tomatoes",
                    score_type="Audience",
                    score_value=float(rt_data.audience_score),
                    score_scale=100.0,
                    source_url=rt_data.source_url,
                ))
            saved += 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return saved


def enrich_rt(limit: int = 50, delay: float = 2.0) -> None:
    """
    Enrichit les films sans score RT en interrogeant Rotten Tomatoes.

    Mécanisme de reprise automatique :
      On sélectionne uniquement les films dont l'id n'est PAS dans
      la table evaluation avec source_name="Rotten Tomatoes".
      → Si le script est interrompu, la prochaine exécution reprend
        exactement là où il s'était arrêté.

    Ordre de traitement :
      Films triés par popularité décroissante (NULLSLAST).
      Les films les plus connus (plus susceptibles d'être sur RT) en premier.

    :param limit: Nombre de films à traiter dans cette session.
    :param delay: Pause en secondes entre chaque requête Selenium (scraping éthique).
    """
    # pool_pre_ping=True : teste "SELECT 1" avant chaque opération DB
    # pool_recycle=300   : ferme et recrée les connexions toutes les 5 min
    engine = create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=300,
    )

    def _fetch_films():
        """
        Ouvre une session courte pour récupérer la liste des films à traiter.
        La session est fermée immédiatement après → on ne garde pas de connexion
        ouverte pendant les 2-5 secondes de scraping par film.
        """
        Session = sessionmaker(bind=engine)
        session = Session()
        try:
            # Sous-requête : film_ids déjà dans evaluation RT
            already_done = session.query(Evaluation.film_id).filter(
                Evaluation.source_name == "Rotten Tomatoes"
            ).scalar_subquery()

            return (
                session.query(Film)
                .filter(~Film.id.in_(already_done))
                .order_by(Film.popularity.desc().nullslast())
                .limit(limit)
                .all()
            )
        finally:
            session.close()

    films = _fetch_films()
    logger.info(f"Films a enrichir : {len(films)} (limite={limit})")
    if not films:
        logger.info("Tous les films ont deja un score RT.")
        return

    enriched = 0
    pending  = []   # buffer des résultats en attente de flush

    with RottenTomatoesScraper() as rt:
        for i, film in enumerate(films):
            year = film.release_date.year if film.release_date else None
            label = (
                film.title
                if film.title == film.original_title or not film.original_title
                else f"{film.title} / {film.original_title}"
            )
            logger.info(f"  [{i+1}/{len(films)}] {label} ({year})")

            rt_data = rt.scrape_movie(film.title, year, original_title=film.original_title)

            if rt_data:
                pending.append({"film_id": film.id, "rt_data": rt_data})
                enriched += 1
                logger.info(f"    OK tomatometer={rt_data.tomatometer_score}% audience={rt_data.audience_score}%")
            else:
                logger.info(f"    Non trouve sur RT")

            # Flush vers DB toutes les BATCH_SIZE réussites (session courte = pas de timeout)
            if len(pending) >= BATCH_SIZE:
                _save_batch(engine, pending)
                pending.clear()
                logger.info(f"--- Progression : {enriched} films commites en DB ---")

            time.sleep(delay)

    # Flush final pour les résultats restants dans le buffer
    if pending:
        _save_batch(engine, pending)

    logger.info(f"[OK] Termine : {enriched}/{len(films)} films enrichis avec scores RT")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enrichissement Rotten Tomatoes standalone")
    parser.add_argument("--limit", type=int, default=50,
                        help="Nombre de films a scraper (defaut: 50)")
    parser.add_argument("--delay", type=float, default=2.0,
                        help="Delai entre requetes en secondes (defaut: 2.0)")
    args = parser.parse_args()
    enrich_rt(limit=args.limit, delay=args.delay)
