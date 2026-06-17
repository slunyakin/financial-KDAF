"""Token-issue endpoint: POST /api/v1/auth/token.

User store is driven by the KDAF_USERS env var:
    KDAF_USERS=alice:bcrypt_hash:analyst,finance;bob:bcrypt_hash:knowledge_engineer

Passwords are stored as bcrypt hashes. Plain-text passwords in KDAF_USERS are
supported for dev convenience — they are hashed on first parse and compared via
bcrypt.checkpw so that $2b$ prefixed strings are treated as pre-hashed.

The issued JWT is identical in structure to manually-crafted tokens and is
accepted by the existing get_current_user dependency without changes.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

import bcrypt
import jwt
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from finance_analytics.config import get_settings

router = APIRouter(prefix="/api/v1/auth")


# ── User store ────────────────────────────────────────────────────────────────

@dataclass
class _User:
    username: str
    password_hash: bytes
    roles: list[str] = field(default_factory=list)


def _parse_users(raw: str) -> dict[str, _User]:
    """Parse KDAF_USERS into a username → _User map.

    Format: "user1:password_or_hash:role1,role2;user2:..."
    Plain-text passwords are bcrypt-hashed on first parse (dev convenience).
    """
    users: dict[str, _User] = {}
    if not raw.strip():
        return users
    for entry in raw.strip().split(";"):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":", 2)
        if len(parts) < 2:
            continue
        username, password_or_hash = parts[0].strip(), parts[1].strip()
        roles = [r.strip() for r in parts[2].split(",")] if len(parts) == 3 else []

        if password_or_hash.startswith("$2b$") or password_or_hash.startswith("$2a$"):
            password_hash = password_or_hash.encode()
        else:
            password_hash = bcrypt.hashpw(password_or_hash.encode(), bcrypt.gensalt())

        users[username] = _User(username=username, password_hash=password_hash, roles=roles)
    return users


_USER_STORE: dict[str, _User] = {}


def init_user_store() -> None:
    """Called at app startup to populate the in-memory user store."""
    global _USER_STORE
    _USER_STORE = _parse_users(get_settings().KDAF_USERS)


def _authenticate(username: str, password: str) -> _User | None:
    user = _USER_STORE.get(username)
    if user is None:
        return None
    if not bcrypt.checkpw(password.encode(), user.password_hash):
        return None
    return user


# ── Schemas ───────────────────────────────────────────────────────────────────

class TokenRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/token", response_model=TokenResponse)
def token_endpoint(request: TokenRequest) -> TokenResponse:
    """Issue a signed JWT for valid credentials.

    Returns HTTP 401 for both bad username and bad password
    (no username enumeration).
    """
    user = _authenticate(request.username, request.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    settings = get_settings()
    expires_in = settings.JWT_EXPIRE_SECONDS
    payload = {
        "sub": user.username,
        "roles": user.roles,
        "exp": int(time.time()) + expires_in,
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return TokenResponse(access_token=token, expires_in=expires_in)
