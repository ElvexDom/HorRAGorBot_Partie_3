"""
Point d'entrée du conteneur frontend — démarre le serveur de métriques
Prometheus (port 8502) immédiatement, PUIS lance Streamlit dans le même
process. Streamlit n'exécute app.py que paresseusement (à la première
connexion navigateur) : lancer les métriques depuis app.py les rendrait
invisibles de Prometheus tant qu'aucun utilisateur ne s'est connecté.
"""
import sys
from pathlib import Path

from metrics import start_metrics_server

start_metrics_server()

from streamlit.web import cli as stcli  # noqa: E402 — après le démarrage des métriques

if __name__ == "__main__":
    app_path = str(Path(__file__).parent / "app.py")
    sys.argv = [
        "streamlit", "run", app_path,
        "--server.address", "0.0.0.0",
        "--server.port", "8501",
    ]
    sys.exit(stcli.main())
