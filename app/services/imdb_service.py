"""
Service IMDB — extraction depuis la base SQLite locale.

La base SQLite est construite depuis les fichiers TSV officiels IMDB
(title.basics.tsv + title.ratings.tsv) via le script create_imdb_db.py.
Taille : ~2 GB, ~10 millions de titres au total.

Rôle dans le pipeline MDM :
  Source d'enrichissement n°4 — fournit les identifiants IMDB (tconst)
  et les notes de la communauté IMDB (averageRating, numVotes).

Filtre qualité : numVotes >= 1000 pour exclure les films obscurs
sans audience réelle. Cela ramène le corpus de ~100 000 films à ~3 000.

Fichier attendu : data/input/imdb.db
Construction : python create_imdb_db.py
"""
import sqlite3
from pathlib import Path
from typing import List, Optional

from app.config.config import settings
from app.utils.logger import logger
from app.models.schema import MovieGold


class IMDBService:
    """
    Extrait les films d'horreur depuis la base SQLite IMDB.
    Utilise une connexion en lecture seule (mode=ro) pour la sécurité.
    """

    HORROR_GENRE = "Horror"
    MIN_VOTES    = 1000   # Seuil qualité : films avec moins de votes ignorés

    # Jointure SQL entre title_basics (métadonnées) et title_ratings (notes)
    # Filtres : type=movie (excluX les séries), genre=Horror, votes >= seuil
    QUERY = """
        SELECT
            tb.tconst,
            tb.primaryTitle,
            tb.originalTitle,
            tb.startYear,
            tb.runtimeMinutes,
            tb.genres,
            tr.averageRating,
            tr.numVotes
        FROM title_basics AS tb
        INNER JOIN title_ratings AS tr
            ON tb.tconst = tr.tconst
        WHERE
            tb.titleType = 'movie'
            AND tb.genres LIKE '%Horror%'
            AND tr.numVotes >= :min_votes
        ORDER BY tr.numVotes DESC
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        :param db_path: Chemin vers imdb.db. Défaut : data/input/imdb.db
        """
        if db_path:
            self.db_path = Path(db_path)
        else:
            self.db_path = Path(settings.DATA_INPUT_DIR) / "imdb.db"

    def _connect(self) -> sqlite3.Connection:
        """
        Ouvre une connexion SQLite en lecture seule (uri=True + mode=ro).
        Lecture seule = protection contre toute écriture accidentelle sur un fichier de 2 GB.
        row_factory=sqlite3.Row permet d'accéder aux colonnes par nom (row["tconst"]).
        """
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"Base SQLite introuvable : {self.db_path}\n"
                "Téléchargez title.basics.tsv.gz et title.ratings.tsv.gz "
                "depuis https://datasets.imdbws.com/ puis exécutez : python create_imdb_db.py"
            )
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # Normalisation des données IMDB
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_date(year_value) -> Optional[str]:
        """
        Convertit l'année IMDB (entier ou str) en ISO 8601 YYYY-01-01.
        IMDB stocke startYear comme un entier (ex: 1982 → "1982-01-01").
        Validation : années entre 1888 (premier film) et 2100.
        """
        if year_value is None:
            return None
        try:
            year = int(str(year_value).strip())
            if 1888 <= year <= 2100:
                return f"{year}-01-01"
        except (ValueError, TypeError):
            pass
        return None

    @staticmethod
    def _parse_genres(genres_str: Optional[str]) -> List[str]:
        """
        Convertit la colonne genres IMDB en liste.
        Format IMDB : "Horror,Thriller" → ["Horror", "Thriller"]
        La valeur "\N" indique une donnée manquante dans IMDB.
        """
        if not genres_str or genres_str == r"\N":
            return ["Horror"]
        return [g.strip() for g in genres_str.split(",") if g.strip()]

    @staticmethod
    def _safe_float(value) -> Optional[float]:
        """Conversion sécurisée en float. Retourne None si valeur invalide."""
        try:
            return float(value) if value is not None else None
        except (ValueError, TypeError):
            return None

    # ------------------------------------------------------------------
    # Extraction principale
    # ------------------------------------------------------------------

    def get_horror_movies(self, min_votes: int = MIN_VOTES) -> List[MovieGold]:
        """
        Exécute la requête SQL et retourne ~3 000 films d'horreur IMDB.

        Les films sont triés par numVotes DESC, donc les plus connus arrivent
        en premier — avantage lors du fuzzy matching (plus de chances de trouver
        le bon film si les plus populaires sont traités en priorité).

        :param min_votes: Seuil minimum de votes (défaut 1000).
        :return: Liste de MovieGold avec imdb_id et vote_average remplis.
        """
        try:
            conn = self._connect()
        except FileNotFoundError as e:
            logger.warning(str(e))
            return []

        movies = []
        try:
            cursor = conn.execute(self.QUERY, {"min_votes": min_votes})
            rows = cursor.fetchall()
            logger.info(f"SQLite IMDB : {len(rows)} films extraits (min_votes={min_votes})")

            for row in rows:
                try:
                    movie = MovieGold(
                        imdb_id=str(row["tconst"]).strip(),         # Ex: "tt0078748"
                        title=str(row["primaryTitle"]).strip(),
                        original_title=row["originalTitle"] if row["originalTitle"] != r"\N" else None,
                        release_date=self._normalize_date(row["startYear"]),
                        vote_average=self._safe_float(row["averageRating"]),  # Note /10
                        genres=self._parse_genres(row["genres"]),
                        source_system="HorRAGor-Pipeline/IMDB-SQLite",
                    )
                    movies.append(movie)
                except Exception as e:
                    logger.debug(f"Ligne IMDB ignorée ({row['tconst']}) : {e}")

        except sqlite3.OperationalError as e:
            logger.error(
                f"Erreur SQL IMDB : {e}\n"
                "Vérifiez que les tables title_basics et title_ratings existent dans imdb.db."
            )
        finally:
            conn.close()

        logger.info(f"IMDBService : {len(movies)} films chargés")
        return movies

    # ------------------------------------------------------------------
    # Utilitaire de construction de la base SQLite (usage unique)
    # ------------------------------------------------------------------

    @staticmethod
    def build_sqlite_from_tsv(basics_tsv: str, ratings_tsv: str, db_path: str) -> None:
        """
        Importe les fichiers TSV IMDB dans une base SQLite locale.
        À exécuter une seule fois via create_imdb_db.py.

        Les fichiers TSV font ~1 GB chacun → l'import prend ~10 minutes.
        Les données sont insérées par batches de 10 000 lignes pour limiter
        la consommation mémoire.

        Téléchargement des TSV :
          wget https://datasets.imdbws.com/title.basics.tsv.gz
          wget https://datasets.imdbws.com/title.ratings.tsv.gz
          gunzip *.gz

        :param basics_tsv:  Chemin vers title.basics.tsv
        :param ratings_tsv: Chemin vers title.ratings.tsv
        :param db_path:     Chemin de sortie du fichier .db
        """
        import csv

        logger.info("Création de la base SQLite IMDB...")
        conn = sqlite3.connect(db_path)
        cur  = conn.cursor()

        # --- Table title_basics ---
        cur.execute("DROP TABLE IF EXISTS title_basics")
        cur.execute("""
            CREATE TABLE title_basics (
                tconst          TEXT PRIMARY KEY,
                titleType       TEXT,
                primaryTitle    TEXT,
                originalTitle   TEXT,
                isAdult         INTEGER,
                startYear       TEXT,
                endYear         TEXT,
                runtimeMinutes  TEXT,
                genres          TEXT
            )
        """)

        logger.info(f"  Import {basics_tsv} ...")
        with open(basics_tsv, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            batch = []
            for row in reader:
                batch.append((
                    row["tconst"], row["titleType"],
                    row["primaryTitle"], row["originalTitle"],
                    row.get("isAdult", 0), row["startYear"],
                    row.get("endYear"), row.get("runtimeMinutes"),
                    row["genres"],
                ))
                if len(batch) >= 10_000:
                    cur.executemany("INSERT OR IGNORE INTO title_basics VALUES (?,?,?,?,?,?,?,?,?)", batch)
                    batch = []
            if batch:
                cur.executemany("INSERT OR IGNORE INTO title_basics VALUES (?,?,?,?,?,?,?,?,?)", batch)

        # --- Table title_ratings ---
        cur.execute("DROP TABLE IF EXISTS title_ratings")
        cur.execute("""
            CREATE TABLE title_ratings (
                tconst          TEXT PRIMARY KEY,
                averageRating   REAL,
                numVotes        INTEGER
            )
        """)

        logger.info(f"  Import {ratings_tsv} ...")
        with open(ratings_tsv, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            batch = []
            for row in reader:
                batch.append((row["tconst"], row["averageRating"], row["numVotes"]))
                if len(batch) >= 10_000:
                    cur.executemany("INSERT OR IGNORE INTO title_ratings VALUES (?,?,?)", batch)
                    batch = []
            if batch:
                cur.executemany("INSERT OR IGNORE INTO title_ratings VALUES (?,?,?)", batch)

        # Index pour accélérer la jointure et les requêtes filtrées
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tb_genres ON title_basics(genres)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tb_type   ON title_basics(titleType)")

        conn.commit()
        conn.close()
        logger.info(f"Base SQLite créée : {db_path}")
