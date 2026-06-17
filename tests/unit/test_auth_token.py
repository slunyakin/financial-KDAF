"""Unit tests for POST /api/v1/auth/token and the user-store parser.

No live services required. Tests cover:
  - _parse_users: valid entries, empty string, malformed entries, pre-hashed passwords
  - _authenticate: correct password, wrong password, unknown user
  - token_endpoint: valid login returns JWT, invalid returns 401, missing fields
  - JWT payload: sub, roles, exp present and correct
"""
from __future__ import annotations

import time
from unittest.mock import patch

import jwt
import pytest
from fastapi import HTTPException

from finance_analytics.api.auth_token import (
    TokenRequest,
    _authenticate,
    _parse_users,
    token_endpoint,
)
from finance_analytics.config import get_settings


# ── _parse_users ──────────────────────────────────────────────────────────────

def test_parse_users_single_entry():
    users = _parse_users("alice:secret:analyst")
    assert "alice" in users
    assert users["alice"].roles == ["analyst"]


def test_parse_users_multiple_entries():
    users = _parse_users("alice:s1:analyst;bob:s2:knowledge_engineer,analyst")
    assert set(users.keys()) == {"alice", "bob"}
    assert "knowledge_engineer" in users["bob"].roles
    assert "analyst" in users["bob"].roles


def test_parse_users_empty_string():
    assert _parse_users("") == {}
    assert _parse_users("   ") == {}


def test_parse_users_malformed_entry_skipped():
    users = _parse_users("badentry;alice:secret:analyst")
    assert "alice" in users
    assert "badentry" not in users


def test_parse_users_no_roles():
    users = _parse_users("alice:secret")
    assert users["alice"].roles == []


def test_parse_users_plain_password_is_hashed():
    import bcrypt
    users = _parse_users("alice:plainpass:analyst")
    assert bcrypt.checkpw(b"plainpass", users["alice"].password_hash)


def test_parse_users_pre_hashed_password_accepted():
    import bcrypt
    hashed = bcrypt.hashpw(b"mypassword", bcrypt.gensalt()).decode()
    users = _parse_users(f"alice:{hashed}:analyst")
    assert bcrypt.checkpw(b"mypassword", users["alice"].password_hash)


# ── _authenticate ─────────────────────────────────────────────────────────────

def _store_with_user(username: str, password: str, roles: list[str]):
    users = _parse_users(f"{username}:{password}:{','.join(roles)}")
    return users


def test_authenticate_correct_password():
    store = _store_with_user("alice", "secret", ["analyst"])
    with patch("finance_analytics.api.auth_token._USER_STORE", store):
        result = _authenticate("alice", "secret")
    assert result is not None
    assert result.username == "alice"


def test_authenticate_wrong_password():
    store = _store_with_user("alice", "secret", ["analyst"])
    with patch("finance_analytics.api.auth_token._USER_STORE", store):
        result = _authenticate("alice", "wrong")
    assert result is None


def test_authenticate_unknown_user():
    store = _store_with_user("alice", "secret", ["analyst"])
    with patch("finance_analytics.api.auth_token._USER_STORE", store):
        result = _authenticate("nobody", "secret")
    assert result is None


# ── token_endpoint ────────────────────────────────────────────────────────────

def test_token_endpoint_valid_credentials():
    store = _store_with_user("alice", "secret", ["analyst"])
    with patch("finance_analytics.api.auth_token._USER_STORE", store):
        response = token_endpoint(TokenRequest(username="alice", password="secret"))
    assert response.token_type == "bearer"
    assert len(response.access_token) > 0
    assert response.expires_in == get_settings().JWT_EXPIRE_SECONDS


def test_token_endpoint_wrong_password_raises_401():
    store = _store_with_user("alice", "secret", ["analyst"])
    with patch("finance_analytics.api.auth_token._USER_STORE", store):
        with pytest.raises(HTTPException) as exc_info:
            token_endpoint(TokenRequest(username="alice", password="bad"))
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid credentials"


def test_token_endpoint_unknown_user_raises_401():
    store = _store_with_user("alice", "secret", ["analyst"])
    with patch("finance_analytics.api.auth_token._USER_STORE", store):
        with pytest.raises(HTTPException) as exc_info:
            token_endpoint(TokenRequest(username="nobody", password="secret"))
    assert exc_info.value.status_code == 401


def test_token_endpoint_jwt_payload():
    store = _store_with_user("alice", "secret", ["analyst", "knowledge_engineer"])
    settings = get_settings()
    before = int(time.time())

    with patch("finance_analytics.api.auth_token._USER_STORE", store):
        response = token_endpoint(TokenRequest(username="alice", password="secret"))

    payload = jwt.decode(
        response.access_token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
    )
    assert payload["sub"] == "alice"
    assert "analyst" in payload["roles"]
    assert "knowledge_engineer" in payload["roles"]
    assert payload["exp"] >= before + settings.JWT_EXPIRE_SECONDS - 2


def test_token_endpoint_jwt_accepted_by_existing_auth():
    """JWT from token_endpoint must be decodable by the existing auth dependency."""
    store = _store_with_user("alice", "secret", ["analyst"])
    settings = get_settings()

    with patch("finance_analytics.api.auth_token._USER_STORE", store):
        response = token_endpoint(TokenRequest(username="alice", password="secret"))

    from finance_analytics.api.auth import _decode_token
    payload = _decode_token(response.access_token)
    assert payload["sub"] == "alice"
