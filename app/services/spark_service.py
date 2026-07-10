"""
HorRAGor - SparkService
Analyses textuelles lourdes sur le Gold Layer via PySpark (mode local).
Input  : data/output/horragor_gold.json
Output : data/output/horragor_spark.json
"""
import json
import re
from pathlib import Path
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.schema import MovieGold

# Chemins (compatibles Docker volume et local)
BASE_DIR = Path(__file__).resolve().parents[2]
INPUT_PATH  = BASE_DIR / "data" / "output" / "horragor_gold.json"
OUTPUT_PATH = BASE_DIR / "data" / "output" / "horragor_spark.json"


# ---------------------------------------------------------------------------
# Analyse PySpark
# ---------------------------------------------------------------------------

def run_spark_analysis(input_path: Path, output_path: Path) -> dict:
    """
    Charge le Gold Layer JSON, applique des transformations Spark et
    retourne un dict de résultats (stats + données enrichies).
    """
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F
    from pyspark.sql.types import StringType, IntegerType, FloatType

    print("🔥 Démarrage SparkSession (mode local)...")
    spark = (
        SparkSession.builder
        .appName("HorRAGor-TextAnalysis")
        .master("local[*]")
        .config("spark.driver.memory", "2g")
        .config("spark.sql.shuffle.partitions", "8")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    # ------------------------------------------------------------------
    # Chargement du Gold Layer
    # ------------------------------------------------------------------
    print(f"📂 Chargement : {input_path}")
    df = spark.read.option("multiline", "true").json(str(input_path))
    total = df.count()
    print(f"   {total} films chargés")

    # ------------------------------------------------------------------
    # Nettoyage & normalisation texte
    # ------------------------------------------------------------------

    # Suppression balises HTML résiduelles dans overview
    clean_html_udf = F.udf(
        lambda text: re.sub(r"<[^>]+>", "", text).strip() if text else None,
        StringType()
    )
    df = df.withColumn("overview", clean_html_udf(F.col("overview")))

    # Normalisation whitespace
    df = df.withColumn(
        "overview",
        F.regexp_replace(F.col("overview"), r"\s+", " ")
    )

    # ------------------------------------------------------------------
    # Analyses textuelles sur les overviews
    # ------------------------------------------------------------------

    # Longueur du synopsis (nb mots)
    df = df.withColumn(
        "overview_word_count",
        F.when(
            F.col("overview").isNotNull(),
            F.size(F.split(F.trim(F.col("overview")), r"\s+"))
        ).otherwise(0).cast(IntegerType())
    )

    # Langue détectée (heuristique simple : présence de mots FR/EN)
    detect_lang_udf = F.udf(
        lambda text: _detect_language(text),
        StringType()
    )
    df = df.withColumn("detected_language", detect_lang_udf(F.col("overview")))

    # Mots-clés horreur extraits de l'overview
    extract_keywords_udf = F.udf(
        lambda text: _extract_horror_keywords(text),
        StringType()  # JSON list sérialisée
    )
    df = df.withColumn("horror_keywords", extract_keywords_udf(F.col("overview")))

    # Score de "richesse" du synopsis (0-100)
    df = df.withColumn(
        "overview_richness_score",
        F.least(
            F.lit(100),
            (F.col("overview_word_count") * F.lit(2)).cast(IntegerType())
        )
    )

    # ------------------------------------------------------------------
    # Stats globales (loggées)
    # ------------------------------------------------------------------
    print("\n📊 Statistiques du Gold Layer :")

    films_with_overview = df.filter(F.col("overview").isNotNull()).count()
    print(f"   Films avec overview    : {films_with_overview}/{total}")

    avg_words = df.agg(F.avg("overview_word_count")).collect()[0][0]
    print(f"   Moy. mots/synopsis     : {avg_words:.1f}" if avg_words else "   Moy. mots/synopsis : N/A")

    lang_dist = df.groupBy("detected_language").count().orderBy(F.desc("count"))
    print("   Distribution langues   :")
    for row in lang_dist.collect():
        print(f"     {row['detected_language'] or 'unknown':<10} : {row['count']} films")

    top_keywords = _get_top_keywords(df)
    print(f"   Top mots-clés horreur  : {', '.join(top_keywords[:10])}")

    vote_stats = df.agg(
        F.avg("vote_average").alias("avg"),
        F.min("vote_average").alias("min"),
        F.max("vote_average").alias("max"),
    ).collect()[0]
    print(f"   Vote average           : avg={vote_stats['avg']:.2f}, min={vote_stats['min']}, max={vote_stats['max']}")

    # ------------------------------------------------------------------
    # Sauvegarde enrichie
    # ------------------------------------------------------------------
    print(f"\n💾 Sauvegarde : {output_path}")

    # Convertir en JSON via Pandas (plus simple que Spark writer pour un seul fichier)
    enriched_df = df.select(
        "tmdb_id", "imdb_id", "title", "release_date",
        "overview", "vote_average", "popularity", "genres",
        "overview_word_count", "detected_language",
        "horror_keywords", "overview_richness_score",
        "source_system",
    )

    records = [row.asDict() for row in enriched_df.collect()]
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2, default=str)

    print(f"✅ {len(records)} films sauvegardés dans {output_path.name}")
    spark.stop()

    return {
        "total": total,
        "with_overview": films_with_overview,
        "avg_words": avg_words,
        "top_keywords": top_keywords,
    }


# ---------------------------------------------------------------------------
# UDFs helpers
# ---------------------------------------------------------------------------

# Mots-clés Horror référence
HORROR_KEYWORDS = [
    "blood", "murder", "kill", "death", "dead", "ghost", "demon", "evil",
    "monster", "terror", "fear", "haunted", "curse", "supernatural", "dark",
    "nightmare", "scream", "horror", "zombie", "vampire", "witch", "creature",
    "possessed", "asylum", "survivor", "stalker", "slasher", "gore", "cult",
    "sacrifice", "ritual", "apparition", "specter", "poltergeist", "undead",
    "plague", "infection", "virus", "madness", "insane", "psycho", "killer",
    "meurtre", "sang", "mort", "fantôme", "démon", "maléfique", "cauchemar",
    "horreur", "zombie", "vampire", "sorcière", "hantée", "malédiction",
]

def _detect_language(text: str) -> str:
    """Heuristique simple de détection de langue (EN/FR/autres)."""
    if not text:
        return "unknown"
    text_lower = text.lower()
    fr_words = ["le ", "la ", "les ", "un ", "une ", "des ", "est ", "sont ", "dans "]
    en_words = ["the ", "a ", "an ", "is ", "are ", "in ", "of ", "and ", "to "]
    fr_score = sum(text_lower.count(w) for w in fr_words)
    en_score = sum(text_lower.count(w) for w in en_words)
    if fr_score > en_score:
        return "fr"
    elif en_score > 0:
        return "en"
    return "other"

def _extract_horror_keywords(text: str) -> str:
    """Extrait les mots-clés horreur présents dans le texte. Retourne JSON list."""
    if not text:
        return "[]"
    text_lower = text.lower()
    found = [kw for kw in HORROR_KEYWORDS if kw in text_lower]
    return json.dumps(list(set(found)))

def _get_top_keywords(df) -> List[str]:
    """Calcule les mots-clés les plus fréquents dans tout le corpus."""
    from pyspark.sql import functions as F
    rows = df.select("horror_keywords").filter(
        F.col("horror_keywords") != "[]"
    ).collect()
    freq = {}
    for row in rows:
        try:
            kws = json.loads(row["horror_keywords"])
            for kw in kws:
                freq[kw] = freq.get(kw, 0) + 1
        except Exception:
            pass
    return sorted(freq, key=freq.get, reverse=True)


# ---------------------------------------------------------------------------
# Enrichissement IN-PLACE pour main.py (appel local sans Docker)
# ---------------------------------------------------------------------------

def enrich_movies_local(movies: List) -> None:
    """
    Enrichit IN-PLACE une liste de MovieGold avec les analyses textuelles.
    Implémentation Python pure pour compatibilité Windows (sans UDFs Spark).
    La version Docker/Linux utilisera run_spark_analysis() avec les UDFs natives.
    """
    print(f"  -> Analyse textuelle Python pure sur {len(movies)} films...")
    for i, movie in enumerate(movies):
        overview = movie.overview or ""
        words = overview.split() if overview else []
        
        movie.__dict__["horror_keywords"]     = _extract_horror_keywords(overview)
        movie.__dict__["detected_language"]   = _detect_language(overview)
        movie.__dict__["overview_word_count"] = len(words)
    
    print(f"  [OK] Analyse textuelle terminee ({len(movies)} films traites)")


class SparkService:
    """Interface appelée par main.py.
    
    Sur Windows (local) : utilise Python pur pour éviter les problèmes de workers Spark.
    Sur Linux/Docker    : utilise run_spark_analysis() avec les UDFs Spark natives.
    """
    def enrich_movies(self, movies: List) -> None:
        enrich_movies_local(movies)


# ---------------------------------------------------------------------------
# Entrypoint Docker
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not INPUT_PATH.exists():
        print(f"❌ Gold Layer introuvable : {INPUT_PATH}")
        print("   Lance d'abord : python main.py")
        exit(1)

    stats = run_spark_analysis(INPUT_PATH, OUTPUT_PATH)
    print(f"\n✅ Spark terminé : {stats['total']} films analysés")