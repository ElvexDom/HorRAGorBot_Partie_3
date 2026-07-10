# Création de la DB IMDB
from app.services.imdb_service import IMDBService

IMDBService.build_sqlite_from_tsv(
    basics_tsv="data/input/title.basics.tsv",
    ratings_tsv="data/input/title.ratings.tsv",
    db_path="data/input/imdb.db"
)