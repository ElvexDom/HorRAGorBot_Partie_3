"""
Configuration centralisée de l'application HorRAGor.

Utilise pydantic-settings pour charger les variables depuis le fichier .env
et les exposer sous forme d'attributs typés et validés.

Fichier .env requis à la racine du projet :
  TMDB_API_KEY=votre_cle_ici
  DATABASE_URL=postgresql://postgres:<pass>@<host>:5432/postgres

Les chemins DATA_INPUT_DIR, DATA_OUTPUT_DIR et LOGS_DIR sont créés
automatiquement s'ils n'existent pas (fin du fichier).
"""
import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Paramètres globaux chargés depuis l'environnement (.env).
    Pydantic valide les types automatiquement et lève une erreur claire
    si une variable obligatoire est absente.
    """

    APP_NAME: str  = "HorRAGor-BOT"
    DEBUG:    bool = True

    # --- API TMDB ---
    TMDB_API_KEY:  str = ""                               # Obtenir sur https://www.themoviedb.org/
    TMDB_BASE_URL: str = "https://api.themoviedb.org/3"

    # --- Chemins locaux ---
    # BASE_DIR pointe vers la racine du projet (2 niveaux au-dessus de ce fichier)
    BASE_DIR:        str = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    DATA_INPUT_DIR:  str = os.path.join(BASE_DIR, "data", "input")    # CSV, TSV, SQLite
    DATA_OUTPUT_DIR: str = os.path.join(BASE_DIR, "data", "output")   # JSON Gold Layer
    LOGS_DIR:        str = os.path.join(BASE_DIR, "data", "logs")

    # --- Selenium ---
    SELENIUM_HEADLESS: bool = True   # False pour voir le navigateur (debug)

    # --- Base de données ---
    # Défaut SQLite local pour les tests sans Supabase.
    # En production, remplacer par l'URL PostgreSQL Supabase dans .env.
    DATABASE_URL: str = "sqlite:///./horragor.db"

    # env_file : fichier à charger (relatif au répertoire de travail)
    # extra="ignore" : ignore les variables .env inconnues sans erreur
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

# Création des dossiers de données au démarrage (idempotent)
for path in [settings.DATA_INPUT_DIR, settings.DATA_OUTPUT_DIR, settings.LOGS_DIR]:
    os.makedirs(path, exist_ok=True)
