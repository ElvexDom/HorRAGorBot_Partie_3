"""
HorRAGor BOT — Pipeline d'ingestion MDM (Master Data Management)

Principe :
  TMDB est la SOURCE MAÎTRESSE. Elle fournit la liste des films et leurs
  identifiants de référence (tmdb_id, imdb_id).
  Les 4 autres sources ENRICHISSENT les films existants (jamais de création).

Ordre d'exécution :
  1. TMDB   → construit la base maîtresse (~1000 films)
  2. RT     → ajoute tomatometer / audience score / consensus (optionnel, lent)
  3. Kaggle → comble les synopsis et données financières manquantes
  4. IMDB   → comble les imdb_id et notes manquantes
  5. Spark  → analyse textuelle : langue, mots-clés horreur, richesse synopsis
  6. DB     → persiste tout dans Supabase (PostgreSQL)
"""
import json
import re
from pathlib import Path
from typing import List, Optional

from app.config.config import settings
from app.utils.logger import logger
from app.models.schema import MovieGold

from app.services.tmdb_api import TMDBService
from app.services.kaggle_service import KaggleService
from app.services.spark_kaggle_service import SparkKaggleService
from app.services.imdb_service import IMDBService
from app.services.db_service import save_movies_to_db


# ---------------------------------------------------------------------------
# Helpers MDM — algorithmes de réconciliation
# ---------------------------------------------------------------------------

def _levenshtein(s1: str, s2: str) -> int:
    """
    Calcule la distance de Levenshtein entre deux chaînes.
    Distance = nombre minimal d'insertions/suppressions/substitutions
    pour passer de s1 à s2.
    Ex : levenshtein("Scream", "Screams") = 1
    """
    s1, s2 = s1.lower().strip(), s2.lower().strip()
    if s1 == s2:
        return 0
    # On travaille toujours avec s1 >= s2 en longueur pour optimiser la mémoire
    if len(s1) < len(s2):
        s1, s2 = s2, s1
    # Algorithme DP ligne par ligne (O(n) mémoire au lieu de O(n²))
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (c1 != c2)))
        prev = curr
    return prev[-1]


def _get_year(movie: MovieGold) -> Optional[str]:
    """Extrait l'année (4 premiers caractères) de release_date. Ex: '2018-06-07' → '2018'."""
    return movie.release_date[:4] if movie.release_date else None


def _find_match(
    target: MovieGold,
    candidates: List[MovieGold],
    by_tmdb: dict,
    by_imdb: dict,
    threshold: int = 2,
) -> Optional[MovieGold]:
    """
    Cherche le meilleur candidat correspondant à target selon 3 niveaux MDM.

    Niveau 1 — Correspondance exacte sur tmdb_id (O(1) via dict)
    Niveau 2 — Correspondance exacte sur imdb_id (O(1) via dict)
    Niveau 3 — Fuzzy matching titre + année (Levenshtein ≤ threshold)

    Le threshold=2 tolère les fautes de frappe mineures et variations
    orthographiques (ex: "Scream 2" vs "Scream II" → distance 3, rejeté).
    """
    # Niveau 1 : ID TMDB exact — le plus fiable
    if target.tmdb_id and target.tmdb_id in by_tmdb:
        return by_tmdb[target.tmdb_id]

    # Niveau 2 : ID IMDB exact — très fiable aussi
    if target.imdb_id and target.imdb_id in by_imdb:
        return by_imdb[target.imdb_id]

    # Niveau 3 : fuzzy sur titre + filtre sur année (évite les remakes)
    year_t = _get_year(target)
    best, best_dist = None, threshold + 1
    for c in candidates:
        year_c = _get_year(c)
        # Si les deux films ont une année ET qu'elles différent → pas le même film
        if year_t and year_c and year_t != year_c:
            continue
        dist = _levenshtein(target.title, c.title)
        if dist < best_dist:
            best, best_dist = c, dist
    return best if best_dist <= threshold else None


def _enrich(base: MovieGold, enricher: MovieGold) -> None:
    """
    Enrichit base avec les champs de enricher, UNIQUEMENT si base.champ est vide.
    Règle MDM fondamentale : une source de priorité inférieure ne peut pas
    écraser une donnée déjà présente.
    """
    if not base.imdb_id and enricher.imdb_id:
        base.imdb_id = enricher.imdb_id
    if not base.overview and enricher.overview:
        base.overview = enricher.overview
    if not base.vote_average and enricher.vote_average:
        base.vote_average = enricher.vote_average
    if not base.popularity and enricher.popularity:
        base.popularity = enricher.popularity
    # Enrichir les genres seulement si TMDB n'a renvoyé que ["Horror"]
    if base.genres == ["Horror"] and enricher.genres not in [[], ["Horror"]]:
        base.genres = enricher.genres


def _build_indexes(movies: List[MovieGold]) -> tuple:
    """
    Construit deux index (dicts) pour des lookups O(1) lors du matching.
    Appelé une seule fois par source avant de boucler sur les 1000+ films.
    """
    by_tmdb = {m.tmdb_id: m for m in movies if m.tmdb_id}
    by_imdb = {m.imdb_id: m for m in movies if m.imdb_id}
    return by_tmdb, by_imdb


# ---------------------------------------------------------------------------
# Étape 1 : Base maîtresse TMDB
# ---------------------------------------------------------------------------

def build_tmdb_master(pages: int = 25) -> List[MovieGold]:
    """
    Interroge l'API TMDB pour récupérer les films d'horreur triés par popularité.
    20 films par page → pages=25 donne ~500 films, pages=59 donne ~1 179 films.

    Deux appels API par film :
      - /discover/movie  → liste paginée avec métadonnées de base
      - /movie/{id}      → détails complets (imdb_id, genres précis)
    """
    logger.info(f"=== SOURCE MAÎTRESSE : TMDB ({pages} pages × 20 films) ===")
    tmdb = TMDBService()
    movies: List[MovieGold] = []

    for page in range(1, pages + 1):
        data = tmdb.discover_horror_movies(page=page)
        if not data or "results" not in data:
            break
        for result in data["results"]:
            # Appel détaillé pour récupérer imdb_id et la liste complète des genres
            details = tmdb.get_movie_details(result["id"])
            movie = MovieGold(
                tmdb_id=result["id"],
                imdb_id=details.get("imdb_id") if details else None,
                title=result["title"],
                original_title=result.get("original_title"),
                release_date=result.get("release_date"),
                overview=result.get("overview"),
                vote_average=result.get("vote_average"),
                popularity=result.get("popularity"),
                genres=[g["name"] for g in details.get("genres", [])] if details else ["Horror"],
                source_system="HorRAGor-Pipeline/TMDB",
            )
            movies.append(movie)
        if page % 5 == 0:
            logger.info(f"  → {len(movies)} films ({page}/{pages} pages)")

    logger.info(f"TMDB master : {len(movies)} films")
    return movies


# ---------------------------------------------------------------------------
# Étape 2 : Enrichissement 1 — Rotten Tomatoes (optionnel, lent)
# ---------------------------------------------------------------------------

def enrich_with_rt(master: List[MovieGold], max_movies: int = 50, delay: float = 3.0) -> None:
    """
    Enrichit IN-PLACE le top max_movies films les plus populaires avec RT.
    Récupère : tomatometer_score, audience_score, critics_consensus.

    Note : cette fonction est utilisée dans le pipeline principal pour
    un petit lot. Pour scraper toute la base, utiliser enrich_rt.py
    qui gère la reprise automatique depuis la DB.

    delay : pause en secondes entre chaque requête (scraping éthique).
    """
    logger.info(f"=== ENRICHISSEMENT 1 : ROTTEN TOMATOES (top {max_movies} films) ===")
    from app.scrapers.rotten_tomatoes import RottenTomatoesScraper
    import time

    # On prend les films les plus populaires en priorité
    targets = sorted(
        [m for m in master if m.popularity],
        key=lambda m: m.popularity or 0,
        reverse=True,
    )[:max_movies]

    enriched = 0
    with RottenTomatoesScraper() as rt:
        for movie in targets:
            year = None
            if movie.release_date:
                match = re.match(r"(\d{4})", movie.release_date)
                year = int(match.group(1)) if match else None

            rt_data = rt.scrape_movie(movie.title, year)
            if rt_data:
                # On stocke dans __dict__ car MovieGold (Pydantic) n'a pas ces champs
                movie.__dict__["rt_tomatometer"] = rt_data.tomatometer_score
                movie.__dict__["rt_audience_score"] = rt_data.audience_score
                movie.__dict__["rt_critics_consensus"] = rt_data.critics_consensus
                movie.__dict__["rt_url"] = rt_data.source_url
                enriched += 1
            time.sleep(delay)

    logger.info(f"RT : {enriched}/{len(targets)} films enrichis")


# ---------------------------------------------------------------------------
# Étape 3 : Enrichissement 2 — Kaggle CSV
# ---------------------------------------------------------------------------

def enrich_with_kaggle(master: List[MovieGold]) -> None:
    """
    Enrichit IN-PLACE les films avec le dataset Kaggle.
    Comble principalement les synopsis (overview) manquants dans TMDB.
    Utilise les 3 niveaux de matching MDM pour trouver les correspondances.

    Ordre de priorité pour la lecture Kaggle :
      1. SparkKaggleService : lit les fichiers splittés en parallèle via PySpark
         (nécessite d'avoir exécuté create_kaggle_splits.py au préalable)
      2. KaggleService : lit horror_movies.csv en fichier unique via Polars
         (fallback si les splits n'existent pas)
    """
    logger.info("=== ENRICHISSEMENT 2 : KAGGLE ===")

    # Priorité 1 : fichiers splittés → PySpark (comportement Big Data attendu)
    spark_svc = SparkKaggleService()
    if spark_svc.is_available():
        kaggle_movies = spark_svc.get_all_movies()
    else:
        # Priorité 2 : fichier unique → Polars (fallback si splits absents)
        logger.info("  Splits absents — fallback KaggleService (fichier unique)")
        kaggle_movies = KaggleService().get_all_movies()

    by_tmdb, by_imdb = _build_indexes(kaggle_movies)

    enriched = 0
    for movie in master:
        match = _find_match(movie, kaggle_movies, by_tmdb, by_imdb)
        if match:
            had_overview = bool(movie.overview)
            _enrich(movie, match)
            if not had_overview and movie.overview:
                enriched += 1

    logger.info(f"Kaggle : {enriched} synopsis récupérés sur films TMDB sans overview")


# ---------------------------------------------------------------------------
# Étape 4 : Enrichissement 3 — IMDB SQLite
# ---------------------------------------------------------------------------

def enrich_with_imdb(master: List[MovieGold]) -> None:
    """
    Enrichit IN-PLACE les films avec les données IMDB extraites de la base SQLite.
    Récupère : imdb_id (tconst), note moyenne IMDB, nombre de votes.

    Important : on stocke la note IMDB dans movie.__dict__["imdb_rating"]
    AVANT l'appel à _enrich(), car _enrich() écrase vote_average avec la note
    IMDB si TMDB n'a pas de note — ce qui ferait perdre l'information de la source.
    La note est ensuite sauvegardée en base comme Evaluation séparée (source=IMDB).
    """
    logger.info("=== ENRICHISSEMENT 3 : IMDB SQLite ===")
    imdb = IMDBService()
    imdb_movies = imdb.get_horror_movies()

    if not imdb_movies:
        logger.warning("IMDB : aucun film chargé (base SQLite absente ?)")
        return

    by_tmdb, by_imdb = _build_indexes(imdb_movies)

    enriched = 0
    for movie in master:
        match = _find_match(movie, imdb_movies, by_tmdb, by_imdb)
        if match:
            had_imdb = bool(movie.imdb_id)
            _enrich(movie, match)
            # Sauvegarder la note brute IMDB avant qu'elle soit perdue dans l'enrichissement
            if match.vote_average is not None:
                movie.__dict__["imdb_rating"] = match.vote_average
            if not had_imdb and movie.imdb_id:
                enriched += 1

    logger.info(f"IMDB : {enriched} imdb_id récupérés sur films TMDB")


# ---------------------------------------------------------------------------
# Étape 5 : Enrichissement 4 — PySpark
# ---------------------------------------------------------------------------

def enrich_with_spark(master: List[MovieGold]) -> None:
    """
    Enrichit IN-PLACE les films avec les analyses textuelles Spark.
    Sur Windows : utilise Python pur (pas de JVM nécessaire).
    Sur Linux/Docker : utilise PySpark natif avec UDFs.

    Analyses produites : detected_language, overview_word_count,
    horror_keywords (liste JSON), richness_score.
    """
    logger.info("=== ENRICHISSEMENT 4 : PYSPARK ===")
    try:
        from app.services.spark_service import SparkService
        SparkService().enrich_movies(master)
    except ImportError:
        logger.warning("SparkService non disponible — skip enrichissement Spark")


# ---------------------------------------------------------------------------
# Sauvegarde Gold Layer JSON
# ---------------------------------------------------------------------------

def save_gold(master: List[MovieGold], path: Path) -> None:
    """
    Sérialise le Gold Layer en JSON.
    Les champs RT et Spark sont stockés dans __dict__ (hors modèle Pydantic),
    on les ajoute manuellement au dump JSON.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    output = []
    for m in master:
        data = m.model_dump(mode="json")
        # Ajouter les champs extra stockés dans __dict__ (RT, Spark)
        for field in ["rt_tomatometer", "rt_audience_score", "rt_critics_consensus", "rt_url"]:
            if field in m.__dict__:
                data[field] = m.__dict__[field]
        output.append(data)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"Gold layer sauvegardé : {path} ({len(master)} films)")


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def run_pipeline(
    tmdb_pages: int = 25,
    scrape_rt: bool = False,
    rt_max_movies: int = 50,
    save_output: bool = True,
    push_to_db: bool = True,
) -> List[MovieGold]:
    """
    Orchestre le pipeline MDM complet dans l'ordre MDM :
      1. TMDB   → base maîtresse
      2. RT     → enrichissement scores (optionnel, scrape_rt=True)
      3. Kaggle → enrichissement synopsis/budget
      4. IMDB   → enrichissement imdb_id/ratings
      5. Spark  → analyse textuelle
      6. JSON   → sauvegarde Gold Layer local
      7. DB     → persistance Supabase

    Paramètres :
      tmdb_pages    : nb de pages TMDB (20 films/page). 59 pages = ~1179 films.
      scrape_rt     : activer le scraping RT temps réel (False par défaut car lent).
      rt_max_movies : nb de films à scraper sur RT si scrape_rt=True.
      save_output   : sauvegarder horragor_gold.json.
      push_to_db    : envoyer vers Supabase.
    """
    master = build_tmdb_master(pages=tmdb_pages)

    if scrape_rt:
        enrich_with_rt(master, max_movies=rt_max_movies)

    enrich_with_kaggle(master)
    enrich_with_imdb(master)
    enrich_with_spark(master)

    # Rapport de qualité du Gold Layer
    with_overview = sum(1 for m in master if m.overview)
    with_imdb    = sum(1 for m in master if m.imdb_id)
    with_rt      = sum(1 for m in master if m.__dict__.get("rt_tomatometer") is not None)
    logger.info(f"=== GOLD LAYER FINAL : {len(master)} films ===")
    logger.info(f"  Avec overview  : {with_overview}/{len(master)}")
    logger.info(f"  Avec imdb_id   : {with_imdb}/{len(master)}")
    logger.info(f"  Avec RT scores : {with_rt}/{len(master)}")

    if save_output:
        save_gold(master, Path(settings.DATA_OUTPUT_DIR) / "horragor_gold.json")

    if push_to_db:
        save_movies_to_db(master)

    return master


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    movies = run_pipeline(
        tmdb_pages=50,
        scrape_rt=False,
        rt_max_movies=50,
        save_output=True,
        push_to_db=True,
    )
    print(f"\n[OK] Pipeline MDM termine : {len(movies)} films dans le Gold Layer")
    print(f"   Sortie : {Path(settings.DATA_OUTPUT_DIR) / 'horragor_gold.json'}")
