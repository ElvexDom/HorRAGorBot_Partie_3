"""
Authentification par Refresh Tokens — verrouille les échanges entre l'IHM
Streamlit et l'API Intelligence (main_api.py).

Compte de service unique (APP_USERNAME/APP_PASSWORD_HASH, via .env), pas de
table Utilisateur : les refresh tokens sont bien liés à un compte (le `sub`
du JWT), sans système d'inscription multi-utilisateurs.

Le registre des refresh tokens valides est en mémoire (process du conteneur
`api`) — ne survit pas à un redémarrage, ne se partage pas entre répliques.
Suffisant pour un unique conteneur `api` ; un store partagé (Redis, table
dédiée) serait l'évolution naturelle en cas de réplication.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# Idempotent et sans effet si déjà chargé ailleurs (main_api.py) — mais
# auth.py peut être importé en premier (ordre d'import, tests unitaires),
# donc ne dépend pas d'un load_dotenv() fait par un autre module.
load_dotenv()

JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev-secret-change-me")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.environ.get("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

# {username: {jti valides}} — un jti retiré = token révoqué ou déjà tourné.
_valid_refresh_jtis: dict[str, set[str]] = {}

_bearer_scheme = HTTPBearer(auto_error=True)


def get_env_password_hash() -> str | None:
    """Lit APP_PASSWORD_HASH depuis l'environnement.

    `docker compose` (contrairement à `docker run --env-file`) interpole les
    `$VAR`/`${VAR}` trouvés dans les fichiers chargés via `env_file:` — un
    hash bcrypt (format `$2b$12$...`) doit donc y être écrit avec chaque `$`
    doublé (`$$`) pour survivre au passage en conteneur. En local (uvicorn,
    pytest), `python-dotenv` ne fait aucune interpolation : `$$` resterait
    tel quel sans ce dé-échappement, donc on l'applique dans tous les cas."""
    value = os.environ.get("APP_PASSWORD_HASH")
    return value.replace("$$", "$") if value else value


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def _encode(username: str, token_type: str, expires_delta: timedelta, jti: str | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    if jti is not None:
        payload["jti"] = jti
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_access_token(username: str) -> str:
    return _encode(username, "access", timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))


def create_refresh_token(username: str) -> str:
    jti = str(uuid.uuid4())
    _valid_refresh_jtis.setdefault(username, set()).add(jti)
    return _encode(username, "refresh", timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS), jti=jti)


def decode_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expiré.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalide.")

    if payload.get("type") != expected_type:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Type de token inattendu.")
    return payload


def rotate_refresh_token(old_token: str) -> tuple[str, str]:
    """Valide et fait tourner un refresh token : l'ancien jti est invalidé,
    un nouveau couple (access, refresh) est émis. Lève 401 si le refresh
    token est expiré, invalide, ou déjà utilisé/révoqué."""
    payload = decode_token(old_token, "refresh")
    username, jti = payload["sub"], payload.get("jti")

    if jti is None or jti not in _valid_refresh_jtis.get(username, set()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token invalide ou déjà utilisé.")

    _valid_refresh_jtis[username].discard(jti)
    return create_access_token(username), create_refresh_token(username)


def revoke_refresh_token(token: str) -> None:
    try:
        payload = decode_token(token, "refresh")
    except HTTPException:
        return
    _valid_refresh_jtis.get(payload["sub"], set()).discard(payload.get("jti"))


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme)) -> str:
    payload = decode_token(credentials.credentials, "access")
    return payload["sub"]
