"""
Schémas de réponse — Couche Données (HorRAGor 1).

Un unique schéma riche (`FilmDetail`) sert les 6 anciens sites d'appel SQL
direct des tools de la Couche Intelligence : chaque appelant ne lit que le
sous-ensemble de champs qui l'intéresse.
"""
from datetime import date

from pydantic import BaseModel


class Evaluations(BaseModel):
    tmdb: float | None = None
    imdb: float | None = None
    rt_critic: float | None = None
    rt_audience: float | None = None


class FilmDetail(BaseModel):
    id: int
    title: str
    original_title: str | None = None
    release_date: date | None = None
    overview: str | None = None
    popularity: float | None = None
    genres: list[str] = []
    evaluations: Evaluations = Evaluations()
    horror_keywords: list[str] = []
    richness_score: int | None = None
