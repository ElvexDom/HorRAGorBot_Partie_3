"""
Métriques Prometheus de la Couche Présentation (Streamlit).

Streamlit n'expose pas de route /metrics stable/documentée entre versions —
plutôt que de dépendre d'un comportement interne non garanti, ce module
démarre son propre petit serveur HTTP Prometheus (port 8502) au niveau
module. Le cache d'import Python garantit qu'il ne démarre qu'une seule
fois par processus, malgré le fait que Streamlit ré-exécute app.py à
chaque interaction utilisateur (ce module, lui, n'est importé qu'une fois).
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

try:
    start_http_server(8502)
except OSError:
    # Déjà démarré dans ce process (ne devrait pas arriver vu le cache
    # d'import, mais reste inoffensif si un rechargement forcé le déclenche).
    logger.warning("Serveur de métriques déjà démarré sur le port 8502.")
