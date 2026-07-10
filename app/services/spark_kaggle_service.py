"""
SparkKaggleService — lecture des fichiers Kaggle splittés via PySpark.

C'est ici que PySpark est utilisé pour son usage prévu : traiter un dossier
de fichiers CSV en parallèle, comme dans un vrai environnement Big Data.

Flux :
  1. create_kaggle_splits.py divise horror_movies.csv en N parties
  2. SparkKaggleService lit TOUT le dossier kaggle_splits/ en une commande Spark
     → Spark distribue la lecture sur plusieurs workers/partitions
  3. Les transformations (filtre, dédup, nettoyage) s'exécutent en parallèle
  4. Le résultat est collecté et converti en List[MovieGold]

Compatibilité Windows :
  PySpark en mode local[*] peut être instable sur Windows (JVM, Hadoop winutils).
  Si l'initialisation Spark échoue, on bascule automatiquement sur le fallback
  Polars qui lit les mêmes fichiers splits un par un (moins parallèle mais fiable).

Prérequis :
  python create_kaggle_splits.py  (à exécuter une fois pour créer les splits)
"""
import re
import json
from pathlib import Path
from typing import List, Optional

from app.config.config import settings
from app.utils.logger import logger
from app.models.schema import MovieGold


# Dossier contenant les fichiers splittés
SPLITS_DIR = Path(settings.DATA_INPUT_DIR) / "kaggle_splits"


# ---------------------------------------------------------------------------
# Analyse PySpark sur les fichiers splittés
# ---------------------------------------------------------------------------

def run_kaggle_spark(splits_dir: Path) -> List[MovieGold]:
    """
    Lit le dossier de splits Kaggle avec PySpark et retourne une liste de MovieGold.

    La commande clé : spark.read.csv("data/input/kaggle_splits/")
    Spark détecte automatiquement tous les .csv du dossier et les lit en parallèle,
    chaque fichier devenant une partition distribuée.

    Transformations appliquées via l'API DataFrame Spark :
      - Renommage des colonnes
      - Filtre thématique : genre doit contenir "horror"
      - Nettoyage HTML via UDF
      - Normalisation des dates vers ISO 8601
      - Déduplication sur (title, release_date)
    """
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F
    from pyspark.sql.types import StringType

    logger.info(f"[Spark] Démarrage SparkSession (mode local[*])...")
    spark = (
        SparkSession.builder
        .appName("HorRAGor-KaggleSplits")
        .master("local[*]")
        .config("spark.driver.memory", "2g")
        .config("spark.sql.shuffle.partitions", "4")
        # Désactiver les logs Spark verbeux
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    # ------------------------------------------------------------------
    # Lecture parallèle de TOUS les fichiers CSV du dossier
    # C'est la force de Spark : un seul appel lit N fichiers en parallèle
    # ------------------------------------------------------------------
    logger.info(f"[Spark] Lecture du dossier : {splits_dir}/")
    df = (
        spark.read
        .option("header", "true")
        .option("inferSchema", "false")     # tout en String pour éviter les erreurs de type
        .option("mode", "DROPMALFORMED")    # ignorer les lignes malformées
        .option("encoding", "UTF-8")
        .csv(str(splits_dir))
    )
    total_raw = df.count()
    logger.info(f"[Spark] {total_raw} lignes chargées depuis {splits_dir.name}/")

    # ------------------------------------------------------------------
    # Renommage des colonnes (CSV Kaggle → noms MovieGold)
    # ------------------------------------------------------------------
    rename_map = {
        "id":           "tmdb_id",
        "genre_names":  "genres",
    }
    for old, new in rename_map.items():
        if old in df.columns:
            df = df.withColumnRenamed(old, new)

    # ------------------------------------------------------------------
    # Filtre thématique : garder uniquement les films Horror
    # ------------------------------------------------------------------
    if "genres" in df.columns:
        df = df.filter(
            F.lower(F.col("genres")).contains("horror")
        )
        logger.info(f"[Spark] Après filtre Horror : {df.count()} films")

    # ------------------------------------------------------------------
    # Nettoyage HTML dans overview (UDF = User Defined Function Spark)
    # ------------------------------------------------------------------
    @F.udf(StringType())
    def clean_html(text):
        """Supprime les balises HTML et normalise les espaces."""
        if not text:
            return None
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text or None

    if "overview" in df.columns:
        df = df.withColumn("overview", clean_html(F.col("overview")))

    # ------------------------------------------------------------------
    # Normalisation des dates vers ISO 8601
    # ------------------------------------------------------------------
    @F.udf(StringType())
    def normalize_date(value):
        """YYYY → YYYY-01-01, YYYY-MM-DD → inchangé, autres → None."""
        if not value:
            return None
        value = str(value).strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            return value
        m = re.match(r"^(\d{4})", value)
        if m:
            return f"{m.group(1)}-01-01"
        return None

    if "release_date" in df.columns:
        df = df.withColumn("release_date", normalize_date(F.col("release_date")))

    # ------------------------------------------------------------------
    # Déduplication sur (title, release_date) — même logique que Polars
    # ------------------------------------------------------------------
    cols_for_dedup = [c for c in ["title", "release_date"] if c in df.columns]
    if cols_for_dedup:
        before = df.count()
        df = df.dropDuplicates(cols_for_dedup)
        after = df.count()
        logger.info(f"[Spark] Déduplication : {before} → {after} films ({before - after} doublons supprimés)")

    # ------------------------------------------------------------------
    # Collecte et conversion en MovieGold
    # ------------------------------------------------------------------
    cols_to_select = [c for c in [
        "tmdb_id", "title", "original_title", "release_date",
        "overview", "vote_average", "popularity", "genres",
    ] if c in df.columns]

    rows = df.select(cols_to_select).collect()
    spark.stop()

    movies = []
    for row in rows:
        try:
            movie = MovieGold(
                tmdb_id=_safe_int(row.get("tmdb_id") if hasattr(row, "get") else getattr(row, "tmdb_id", None)),
                title=str(row["title"] or "").strip() or "Unknown",
                original_title=row["original_title"] if "original_title" in cols_to_select else None,
                release_date=row["release_date"] if "release_date" in cols_to_select else None,
                overview=row["overview"] if "overview" in cols_to_select else None,
                vote_average=_safe_float(row["vote_average"]) if "vote_average" in cols_to_select else None,
                popularity=_safe_float(row["popularity"]) if "popularity" in cols_to_select else None,
                genres=_parse_genres(row["genres"] if "genres" in cols_to_select else None),
                source_system="HorRAGor-Pipeline/Kaggle-Spark",
            )
            movies.append(movie)
        except Exception as e:
            logger.debug(f"[Spark] Ligne ignorée : {e}")

    logger.info(f"[Spark] {len(movies)} MovieGold construits")
    return movies


# ---------------------------------------------------------------------------
# Fallback Polars : lit les splits un par un si Spark échoue
# ---------------------------------------------------------------------------

def _read_splits_with_polars(splits_dir: Path) -> List[MovieGold]:
    """
    Fallback Polars : lit chaque fichier split séquentiellement.
    Même résultat que Spark mais sans parallélisme.
    Utilisé automatiquement si PySpark échoue (ex: problème JVM sur Windows).
    """
    import polars as pl

    logger.info(f"[Polars fallback] Lecture des splits dans {splits_dir}/")

    from app.services.kaggle_service import KaggleService
    svc = KaggleService()

    all_movies: List[MovieGold] = []
    seen: set = set()   # clé (title, release_date) pour déduplication inter-fichiers

    for csv_file in sorted(splits_dir.glob("*.csv")):
        svc.horror_csv = csv_file
        chunk = svc.get_all_movies()
        for m in chunk:
            key = (m.title, m.release_date)
            if key not in seen:
                seen.add(key)
                all_movies.append(m)
        logger.info(f"  {csv_file.name} → {len(chunk)} films (total cumulé: {len(all_movies)})")

    logger.info(f"[Polars fallback] {len(all_movies)} films chargés depuis {splits_dir.name}/")
    return all_movies


# ---------------------------------------------------------------------------
# Interface publique
# ---------------------------------------------------------------------------

class SparkKaggleService:
    """
    Service principal pour lire les fichiers Kaggle splittés.

    Utilisation dans main.py (remplace KaggleService) :
      svc = SparkKaggleService()
      if svc.is_available():
          movies = svc.get_all_movies()
      else:
          # pas de splits → utiliser KaggleService classique (fichier unique)

    Ordre de priorité :
      1. PySpark sur kaggle_splits/ (lecture distribuée — comportement voulu)
      2. Polars sur kaggle_splits/  (fallback si Spark échoue sur Windows)
      3. KaggleService classique    (si les splits n'existent pas)
    """

    def __init__(self):
        self.splits_dir = SPLITS_DIR

    def is_available(self) -> bool:
        """Retourne True si le dossier de splits existe et contient des CSV."""
        return self.splits_dir.exists() and any(self.splits_dir.glob("*.csv"))

    def get_all_movies(self) -> List[MovieGold]:
        """
        Lit les splits Kaggle. Essaie Spark, bascule sur Polars si nécessaire.
        """
        if not self.is_available():
            logger.warning(
                f"[SparkKaggle] Dossier absent : {self.splits_dir}\n"
                "  Exécutez d'abord : python create_kaggle_splits.py"
            )
            return []

        split_files = list(self.splits_dir.glob("*.csv"))
        logger.info(f"[SparkKaggle] {len(split_files)} fichiers splits détectés")

        # Essai PySpark
        try:
            return run_kaggle_spark(self.splits_dir)
        except Exception as e:
            logger.warning(f"[SparkKaggle] PySpark indisponible ({e}), fallback Polars")
            return _read_splits_with_polars(self.splits_dir)


# ---------------------------------------------------------------------------
# Helpers de conversion de types
# ---------------------------------------------------------------------------

def _safe_int(value) -> Optional[int]:
    try:
        return int(float(value)) if value is not None else None
    except (ValueError, TypeError):
        return None


def _safe_float(value) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def _parse_genres(value) -> List[str]:
    if not value:
        return ["Horror"]
    if isinstance(value, list):
        return [g.strip() for g in value if g.strip()]
    genres = re.split(r"[,|/]", str(value))
    genres = [g.strip() for g in genres if g.strip()]
    return genres if genres else ["Horror"]


# ---------------------------------------------------------------------------
# Entrypoint standalone (test / debug)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    svc = SparkKaggleService()
    if not svc.is_available():
        print(f"Dossier splits absent. Lance d'abord : python create_kaggle_splits.py")
    else:
        movies = svc.get_all_movies()
        print(f"\n[OK] {len(movies)} films chargés depuis les splits Kaggle")
        if movies:
            print(f"  Exemple : {movies[0].title} ({movies[0].release_date})")
