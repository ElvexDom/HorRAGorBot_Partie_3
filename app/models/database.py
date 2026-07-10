"""
Modèles SQLAlchemy ORM — Structure de la base de données PostgreSQL (Supabase).

Architecture Hub & Spoke :
  - FILM            : table centrale (Hub), clé tmdb_id
  - EVALUATION      : tous les scores multi-sources dans une table unifiée (Spoke)
  - ANALYSE_SPARK   : résultats NLP PySpark, relation 1-1 avec FILM (Spoke)
  - SOURCE          : traçabilité MDM — quelle source a contribué quels champs (Spoke)
  - GENRE           : référentiel de genres (18 genres uniques)
  - FILM_GENRE      : table de liaison N-N entre FILM et GENRE

Avantage du pattern Evaluation unifié :
  Plutôt que d'avoir tmdb_score, imdb_score, rt_score comme colonnes dans FILM
  (avec beaucoup de NULL), on stocke chaque score comme une ligne séparée dans
  EVALUATION avec source_name et score_type. Extensible à n'importe quelle
  nouvelle source sans modifier le schéma.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Date, Float, Text, ForeignKey, TIMESTAMP, JSON, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSONB

Base = declarative_base()

# JSONB est le type PostgreSQL natif pour JSON (indexable, plus performant que JSON)
# with_variant() permet de garder JSON pour les tests en SQLite
CustomJSON = JSON().with_variant(JSONB, 'postgresql')


class FilmGenreAssociation(Base):
    """
    Table de liaison N-N entre FILM et GENRE.
    Un film peut avoir plusieurs genres (Horror + Thriller + Mystery).
    Un genre peut appartenir à plusieurs films.
    Clé primaire composite : (film_id, genre_id).
    """
    __tablename__ = "film_genre"

    film_id  = Column(Integer, ForeignKey("film.id",  ondelete="CASCADE"), primary_key=True)
    genre_id = Column(Integer, ForeignKey("genre.id", ondelete="CASCADE"), primary_key=True)


class Genre(Base):
    """
    Référentiel des genres cinématographiques.
    18 genres uniques dans la base (Horror, Thriller, Mystery...).
    Relation N-N avec Film via film_genre.
    """
    __tablename__ = "genre"

    id   = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)   # Ex: "Horror"

    films = relationship("Film", secondary="film_genre", back_populates="genres")


class Film(Base):
    """
    Table centrale (Hub) — un enregistrement par film unique.
    Clé de déduplication : tmdb_id (unique, jamais NULL).
    imdb_id est unique mais peut être NULL pour les films très récents ou obscurs.

    Relations :
      - genres       : N-N via film_genre
      - evaluations  : 1-N (TMDB + IMDB + RT par film)
      - analyse_spark: 1-1 (une analyse NLP par film)
      - sources      : 1-N (une ligne par source ayant contribué)
    """
    __tablename__ = "film"

    id             = Column(Integer, primary_key=True, index=True)
    tmdb_id        = Column(Integer, unique=True, nullable=False, index=True)   # Clé MDM principale
    imdb_id        = Column(String,  unique=True, nullable=True,  index=True)   # Ex: "tt0078748"
    title          = Column(String,  nullable=False)                             # Titre localisé (FR)
    original_title = Column(String,  nullable=True)                              # Titre original
    release_date   = Column(Date,    nullable=True)                              # Format date SQL
    overview       = Column(Text,    nullable=True)                              # Synopsis
    popularity     = Column(Float,   nullable=True)                              # Score TMDB
    source_system  = Column(String,  nullable=False)                             # "HorRAGor-Pipeline/TMDB"
    last_updated   = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    genres        = relationship("Genre",        secondary="film_genre", back_populates="films")
    evaluations   = relationship("Evaluation",   back_populates="film",  cascade="all, delete-orphan")
    analyse_spark = relationship("AnalyseSpark",  back_populates="film",  uselist=False, cascade="all, delete-orphan")
    sources       = relationship("Source",        back_populates="film",  cascade="all, delete-orphan")


class Evaluation(Base):
    """
    Table unifiée pour tous les scores multi-sources.

    Une ligne par (film, source, type_de_score). Exemples :
      film_id=42, source_name="TMDB",           score_type="User",     score_value=6.5, scale=10
      film_id=42, source_name="IMDB",           score_type="User",     score_value=7.1, scale=10
      film_id=42, source_name="Rotten Tomatoes",score_type="Critic",   score_value=89,  scale=100
      film_id=42, source_name="Rotten Tomatoes",score_type="Audience", score_value=72,  scale=100

    score_scale permet de normaliser les comparaisons inter-sources.
    review_text stocke le critics_consensus de RT.
    """
    __tablename__ = "evaluation"

    id          = Column(Integer, primary_key=True, index=True)
    film_id     = Column(Integer, ForeignKey("film.id", ondelete="CASCADE"), nullable=False, index=True)
    source_name = Column(String,  nullable=False)    # "TMDB" | "IMDB" | "Rotten Tomatoes"
    score_type  = Column(String,  nullable=False)    # "User" | "Critic" | "Audience"
    score_value = Column(Float,   nullable=False)    # Valeur brute dans l'échelle native
    score_scale = Column(Float,   nullable=False)    # 10.0 (TMDB/IMDB) ou 100.0 (RT)
    num_votes   = Column(Integer, nullable=True)     # Nombre de votes (si disponible)
    review_text = Column(Text,    nullable=True)     # Critics consensus RT
    source_url  = Column(String,  nullable=True)     # URL de la page source
    evaluated_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    film = relationship("Film", back_populates="evaluations")


class AnalyseSpark(Base):
    """
    Résultats des analyses textuelles PySpark sur les synopsis.
    Relation 1-1 avec Film (unique=True sur film_id).

    horror_keywords : liste JSON des mots-clés horreur trouvés dans le synopsis.
      Ex: ["blood", "death", "ghost", "ritual"]
    richness_score  : proxy de richesse = min(100, word_count * 2)
    """
    __tablename__ = "analyse_spark"

    id                  = Column(Integer, primary_key=True, index=True)
    film_id             = Column(Integer, ForeignKey("film.id", ondelete="CASCADE"), unique=True, nullable=False)
    detected_language   = Column(String,  nullable=True)    # "fr" | "en" | "other" | "unknown"
    overview_word_count = Column(Integer, nullable=True)    # Nombre de mots du synopsis
    horror_keywords     = Column(CustomJSON, nullable=True) # Liste JSON de mots-clés
    richness_score      = Column(Integer, nullable=True)    # Score 0-100
    analysed_at         = Column(TIMESTAMP(timezone=True), server_default=func.now())

    film = relationship("Film", back_populates="analyse_spark")


class Source(Base):
    """
    Traçabilité MDM — enregistre quelle source a contribué quels champs pour chaque film.
    Permet d'auditer la provenance des données et de rejouer un enrichissement partiel.

    Exemple :
      film_id=42, source_name="Kaggle",  contributed_fields=["overview", "budget"]
      film_id=42, source_name="TMDB",    contributed_fields=["title", "release_date", "genres"]
      film_id=42, source_name="Spark",   contributed_fields=["horror_keywords", "detected_language"]
    """
    __tablename__ = "source"

    id                  = Column(Integer, primary_key=True, index=True)
    film_id             = Column(Integer, ForeignKey("film.id", ondelete="CASCADE"), nullable=False, index=True)
    source_name         = Column(String,  nullable=False)        # "TMDB" | "Kaggle" | "IMDB" | "Spark" | "Rotten Tomatoes"
    contributed_fields  = Column(CustomJSON, nullable=False)     # Liste des champs contribués
    ingested_at         = Column(TIMESTAMP(timezone=True), server_default=func.now())

    film = relationship("Film", back_populates="sources")
