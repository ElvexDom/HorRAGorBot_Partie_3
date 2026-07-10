"""
Modèles Pydantic — Schémas de données du pipeline HorRAGor.

Pydantic assure la validation automatique des types à la création des objets.
MovieGold est le modèle central qui circule dans tout le pipeline.
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class MovieBase(BaseModel):
    """Champs minimaux communs à toutes les représentations d'un film."""
    title: str
    original_title: Optional[str] = None
    release_date: Optional[str] = None   # Format ISO 8601 : "YYYY-MM-DD"


class RottenTomatoesData(BaseModel):
    """
    Données extraites de Rotten Tomatoes pour un film.
    Retourné par RottenTomatoesScraper.scrape_movie().
    """
    tomatometer_score: Optional[int] = Field(None, ge=0, le=100)   # % critiques positifs
    audience_score: Optional[int] = Field(None, ge=0, le=100)       # % audience positive
    critics_consensus: Optional[str] = None                          # Texte du consensus
    source_url: str                                                   # URL de la page RT
    scraped_at: datetime = Field(default_factory=datetime.now)       # Timestamp du scraping


class MovieGold(MovieBase):
    """
    Modèle "Gold Layer" — représentation finale et enrichie d'un film.

    Ce modèle est créé par TMDB (source maîtresse) et enrichi progressivement
    par les 4 autres sources. Les champs RT et Spark sont stockés dans __dict__
    car Pydantic ne les connaît pas (ils sont ajoutés dynamiquement).

    Champs core (TMDB) :
      tmdb_id, imdb_id, title, original_title, release_date,
      overview, vote_average, popularity, genres

    Champs extra ajoutés en cours de pipeline (via movie.__dict__) :
      rt_tomatometer, rt_audience_score, rt_critics_consensus, rt_url
      imdb_rating, horror_keywords, detected_language, overview_word_count
    """
    tmdb_id: Optional[int] = None            # Identifiant TMDB (clé de référence)
    imdb_id: Optional[str] = None            # Identifiant IMDB (ex: "tt0078748")
    overview: Optional[str] = None           # Synopsis en français (TMDB) ou anglais
    vote_average: Optional[float] = None     # Note TMDB (0-10)
    popularity: Optional[float] = None       # Score de popularité TMDB
    genres: List[str] = []                   # Ex: ["Horror", "Thriller"]

    # Traçabilité — indique quelle source a créé cet objet
    source_system: str = "HorRAGor-Pipeline"
    last_updated: datetime = Field(default_factory=datetime.now)
