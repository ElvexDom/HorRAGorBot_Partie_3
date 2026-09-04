"""
Tests unitaires de auth.py — authentification par refresh tokens.
Aucun appel réseau : tout est local (bcrypt, JWT signés en mémoire).
"""
import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

import auth


@pytest.fixture(autouse=True)
def _clean_registry():
    """Le registre des jti valides est un dict module-level — on l'isole
    entre tests pour éviter toute fuite d'état."""
    auth._valid_refresh_jtis.clear()
    yield
    auth._valid_refresh_jtis.clear()


class TestPasswordHashing:
    def test_verify_password_correct(self):
        hashed = auth.hash_password("s3cret")
        assert auth.verify_password("s3cret", hashed) is True

    def test_verify_password_incorrect(self):
        hashed = auth.hash_password("s3cret")
        assert auth.verify_password("wrong", hashed) is False

    def test_verify_password_malformed_hash_returns_false(self):
        assert auth.verify_password("s3cret", "not-a-bcrypt-hash") is False


class TestTokenCreationAndDecoding:
    def test_access_token_round_trips(self):
        token = auth.create_access_token("admin")
        payload = auth.decode_token(token, "access")
        assert payload["sub"] == "admin"
        assert payload["type"] == "access"

    def test_refresh_token_round_trips_and_registers_jti(self):
        token = auth.create_refresh_token("admin")
        payload = auth.decode_token(token, "refresh")
        assert payload["jti"] in auth._valid_refresh_jtis["admin"]

    def test_decode_wrong_type_raises_401(self):
        access = auth.create_access_token("admin")
        with pytest.raises(HTTPException) as exc_info:
            auth.decode_token(access, "refresh")
        assert exc_info.value.status_code == 401

    def test_decode_invalid_signature_raises_401(self):
        forged = jwt.encode({"sub": "admin", "type": "access"}, "wrong-secret", algorithm="HS256")
        with pytest.raises(HTTPException) as exc_info:
            auth.decode_token(forged, "access")
        assert exc_info.value.status_code == 401

    def test_decode_expired_token_raises_401(self, monkeypatch):
        monkeypatch.setattr(auth, "ACCESS_TOKEN_EXPIRE_MINUTES", -1)
        expired = auth.create_access_token("admin")
        with pytest.raises(HTTPException) as exc_info:
            auth.decode_token(expired, "access")
        assert exc_info.value.status_code == 401

    def test_decode_garbage_token_raises_401(self):
        with pytest.raises(HTTPException) as exc_info:
            auth.decode_token("not-a-jwt-at-all", "access")
        assert exc_info.value.status_code == 401


class TestRefreshRotation:
    def test_rotate_returns_new_valid_tokens(self):
        refresh = auth.create_refresh_token("admin")

        new_access, new_refresh = auth.rotate_refresh_token(refresh)

        assert auth.decode_token(new_access, "access")["sub"] == "admin"
        assert auth.decode_token(new_refresh, "refresh")["sub"] == "admin"

    def test_rotate_invalidates_old_jti_single_use(self):
        refresh = auth.create_refresh_token("admin")
        auth.rotate_refresh_token(refresh)

        with pytest.raises(HTTPException) as exc_info:
            auth.rotate_refresh_token(refresh)  # rejeu du même token déjà tourné
        assert exc_info.value.status_code == 401

    def test_rotate_with_unknown_jti_raises_401(self):
        forged = jwt.encode(
            {"sub": "admin", "type": "refresh", "jti": "never-issued",
             "iat": 0, "exp": 9999999999},
            auth.JWT_SECRET_KEY, algorithm=auth.JWT_ALGORITHM,
        )
        with pytest.raises(HTTPException) as exc_info:
            auth.rotate_refresh_token(forged)
        assert exc_info.value.status_code == 401


class TestRevocation:
    def test_revoke_then_rotate_fails(self):
        refresh = auth.create_refresh_token("admin")
        auth.revoke_refresh_token(refresh)

        with pytest.raises(HTTPException) as exc_info:
            auth.rotate_refresh_token(refresh)
        assert exc_info.value.status_code == 401

    def test_revoke_invalid_token_is_a_noop(self):
        auth.revoke_refresh_token("not-a-jwt")  # ne doit jamais lever


class TestGetCurrentUser:
    def test_valid_access_token_returns_username(self):
        token = auth.create_access_token("admin")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        assert auth.get_current_user(creds) == "admin"

    def test_refresh_token_rejected_as_access(self):
        token = auth.create_refresh_token("admin")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        with pytest.raises(HTTPException) as exc_info:
            auth.get_current_user(creds)
        assert exc_info.value.status_code == 401
