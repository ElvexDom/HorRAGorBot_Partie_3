"""
Découpe horror_movies.csv en N parties pour le traitement PySpark distribué.

PySpark est conçu pour traiter des dossiers de fichiers en parallèle,
pas un seul gros fichier. Ce script prépare les données pour SparkKaggleService.

À exécuter une seule fois (comme create_imdb_db.py) :
  python create_kaggle_splits.py

Résultat : data/input/kaggle_splits/
  horror_movies_part_01.csv  (~6 500 lignes)
  horror_movies_part_02.csv  (~6 500 lignes)
  horror_movies_part_03.csv  (~6 500 lignes)
  horror_movies_part_04.csv  (~6 500 lignes)
  horror_movies_part_05.csv  (~6 500 lignes)
"""
import math
from pathlib import Path

import polars as pl

# --- Configuration ---
N_SPLITS    = 5
INPUT_CSV   = Path("data/input/horror_movies.csv")
OUTPUT_DIR  = Path("data/input/kaggle_splits")


def create_splits(n_splits: int = N_SPLITS) -> None:
    if not INPUT_CSV.exists():
        print(f"[ERREUR] Fichier introuvable : {INPUT_CSV}")
        print("  Téléchargez horror_movies.csv depuis Kaggle et placez-le dans data/input/")
        return

    print(f"Lecture de {INPUT_CSV} ...")
    df = pl.read_csv(
        INPUT_CSV,
        ignore_errors=True,
        null_values=["", "NA", "N/A", "null", "None"],
    )
    total = df.shape[0]
    print(f"  {total} lignes, {df.shape[1]} colonnes")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    chunk_size = math.ceil(total / n_splits)

    for i in range(n_splits):
        start  = i * chunk_size
        end    = min(start + chunk_size, total)
        chunk  = df.slice(start, end - start)
        out    = OUTPUT_DIR / f"horror_movies_part_{i+1:02d}.csv"
        chunk.write_csv(out)
        print(f"  Part {i+1:02d} : {len(chunk):>6} lignes -> {out.name}")

    print(f"\n[OK] {total} lignes decoupees en {n_splits} fichiers dans {OUTPUT_DIR}/")
    print(f"     Pret pour : python main.py  (SparkKaggleService lira ces fichiers)")


if __name__ == "__main__":
    create_splits()
