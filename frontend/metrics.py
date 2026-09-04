"""
Métriques Prometheus de la Couche Présentation (Streamlit).

Streamlit n'exécute app.py que paresseusement — au premier navigateur qui se
connecte (session WebSocket), jamais au démarrage du conteneur. Démarrer le
serveur /metrics depuis app.py le rendrait donc invisible de Prometheus tant
qu'aucun utilisateur n'a ouvert la page. C'est pour ça que start_metrics_server()
est appelée explicitement depuis frontend/bootstrap.py (le point d'entrée du
conteneur), avant même de lancer Streamlit — dans le même process, pour que
les Counter/Histogram définis ici restent partagés avec ceux incrémentés
depuis app.py (le registre prometheus_client est global au process).
"""
import logging

from prometheus_client import Counter, Histogram, start_http_server

logger = logging.getLogger(__name__)

CHAT_REQUESTS_TOTAL = Counter(
    "horragor_frontend_chat_requests_total",
    "Requêtes /chat envoyées depuis l'IHM, par statut (success/error)",
    ["status"],
)

CHAT_REQUEST_DURATION_SECONDS = Histogram(
    "horragor_frontend_chat_request_duration_seconds",
    "Durée observée côté IHM d'une requête /chat (aller-retour complet)",
)

LOGIN_ATTEMPTS_TOTAL = Counter(
    "horragor_frontend_login_attempts_total",
    "Tentatives de connexion depuis l'écran de login, par résultat",
    ["success"],
)


def start_metrics_server(port: int = 8502) -> None:
    try:
        start_http_server(port, addr="0.0.0.0")
    except OSError:
        logger.warning(f"Serveur de métriques déjà démarré sur le port {port}.")
