"""
Service Kaggle — lecture et nettoyage du dataset horror_movies.csv avec Polars.

Polars est utilisé à la place de Pandas pour ses performances sur les gros volumes
(14 MB de CSV, ~35 000 lignes) et sa gestion mémoire plus efficace.

Rôle dans le pipeline MDM :
  Source d'enrichissement n°3 — comble les synopsis et données financières
  manquantes dans les films TMDB.

Dataset source : https://www.kaggle.com/datasets/PromptCloudHQ/imdb-horror-movie-dataset
Fichier attendu : data/input/horror_movies.csv
"""
import polars as pl
from typing import List, Optional
from pathlib import Path
import re

from app.config.config import settings
from app.utils.logger import logger
from app.models.schema import MovieGold


class KaggleService:
    """
    Lit horror_movies.csv avec Polars, nettoie les données,
    et retourne une liste de MovieGold pour le matching MDM.

    Colonnes utilisées du CSV :
      id, title, original_title, release_date, overview,
      vote_average, popularity, genre_names, budget, revenue, runtime
    """

    # Correspondance colonnes CSV → champs MovieGold
    HORROR_MOVIES_COLS = {
        "id": "tmdb_id",
        "title": "title",
        "original_title": "original_title",
        "release_date": "release_date",
        "overview": "overview",
        "vote_average": "vote_average",
        "popularity": "popularity",
        "genre_names": "genres",
        "budget": "budget",
        "revenue": "revenue",
        "runtime": "runtime",
    }

    def __init__(self):
        self.input_dir = Path(settings.DATA_INPUT_DIR)
        self.horror_csv = self.input_dir / "horror_movies.csv"

        # Fallback : chercher aussi à la racine si data/input/ absent
        if not self.horror_csv.exists():
            root = Path(settings.BASE_DIR)
            if (root / "horror_movies.csv").exists():
                self.horror_csv = root / "horror_movies.csv"

    # ------------------------------------------------------------------
    # Utilitaires de nettoyage
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_html(text: Optional[str]) -> Optional[str]:
        """
        Supprime les balises HTML et normalise les espaces.
        Certains synopsis Kaggle contiennent du HTML résiduel
        (ex: "<p>A family moves...</p>" → "A family moves...")
        """
        if not text:
            return None
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text or None

    @staticmethod
    def _normalize_date(value: Optional[str]) -> Optional[str]:
        """
        Normalise vers ISO 8601.
        Kaggle stocke parfois juste l'année (ex: "1968") → "1968-01-01".
        """
        if not value:
            return None
        value = str(value).strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            return value
        match = re.match(r"^(\d{4})", value)
        if match:
            return f"{match.group(1)}-01-01"
        return None

    @staticmethod
    def _parse_genres(value) -> List[str]:
        """
        Convertit la colonne genres en liste Python.
        Formats rencontrés : "Horror, Thriller", "Horror|Mystery", liste Python.
        Si vide → ["Horror"] par défaut (tous les films du CSV sont horreur).
        """
        if not value:
            return ["Horror"]
        if isinstance(value, list):
            return [g.strip() for g in value if g.strip()]
        genres = re.split(r"[,|/]", str(value))
        genres = [g.strip() for g in genres if g.strip()]
        return genres if genres else ["Horror"]

    # ------------------------------------------------------------------
    # Lecture principale
    # ------------------------------------------------------------------

    def get_all_movies(self) -> List[MovieGold]:
        """
        Charge horror_movies.csv avec Polars et retourne une liste de MovieGold.

        Étapes de traitement :
          1. Lecture CSV avec gestion des valeurs nulles ("", "NA", "None")
          2. Renommage des colonnes selon HORROR_MOVIES_COLS
          3. Filtrage thématique : garde uniquement les lignes avec genre "Horror"
          4. Déduplication sur (title, release_date)
          5. Conversion ligne par ligne en MovieGold avec nettoyage
        """
        if not self.horror_csv.exists():
            logger.warning(f"Fichier introuvable : {self.horror_csv}")
            return []

        logger.info(f"Chargement Polars : {self.horror_csv}")
        try:
            df = pl.read_csv(
                self.horror_csv,
                infer_schema_length=1000,
                null_values=["", "NA", "N/A", "null", "None"],
                ignore_errors=True,
            )
        except Exception as e:
            logger.error(f"Erreur lecture CSV horror_movies : {e}")
            return []

        logger.info(f"  → {df.shape[0]} lignes, colonnes : {df.columns}")

        # Renommage des colonnes pour correspondre au modèle MovieGold
        rename_map = {k: v for k, v in self.HORROR_MOVIES_COLS.items() if k in df.columns}
        df = df.rename(rename_map)

        # Filtre thématique : ne garder que les films Horror
        if "genres" in df.columns:
            df = df.filter(
                pl.col("genres").cast(pl.Utf8).str.to_lowercase().str.contains("horror")
            )

        # Déduplication : même film en double sur (title + release_date) → garder le premier
        if "title" in df.columns and "release_date" in df.columns:
            df = df.unique(subset=["title", "release_date"], keep="first")

        movies = []
        for row in df.iter_rows(named=True):
            try:
                movie = MovieGold(
                    tmdb_id=self._safe_int(row.get("tmdb_id")),
                    title=str(row.get("title", "")).strip() or "Unknown",
                    original_title=row.get("original_title"),
                    release_date=self._normalize_date(row.get("release_date")),
                    overview=self._clean_html(row.get("overview")),
                    vote_average=self._safe_float(row.get("vote_average")),
                    popularity=self._safe_float(row.get("popularity")),
                    genres=self._parse_genres(row.get("genres")),
                    source_system="HorRAGor-Pipeline/Kaggle",
                )
                movies.append(movie)
            except Exception as e:
                logger.debug(f"Ligne ignorée : {e}")

        logger.info(f"  → {len(movies)} films chargés depuis horror_movies.csv")
        return movies

    # ------------------------------------------------------------------
    # Helpers de conversion de types sécurisés
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_int(value) -> Optional[int]:
        """Conversion sécurisée vers int. Retourne None si impossible."""
        try:
            return int(float(value)) if value is not None else None
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _safe_float(value) -> Optional[float]:
        """Conversion sécurisée vers float. Retourne None si impossible."""
        try:
            return float(value) if value is not None else None
        except (ValueError, TypeError):
            return None
