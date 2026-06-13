"""JWT authentication FastAPI dependencies.

FastAPI Depends pattern:
    get_current_user(credentials) → (user_id, user_roles)

This tuple is injected into the LangGraph chain state at request time:
    state["user_id"] = user_id
    state["user_roles"] = user_roles

user_roles drives KG cache key separation and future visibility filtering.
It is NOT stored in Question nodes (stale-role problem — per CEO plan decision).

JWT payload expected fields:
    sub   → user_id (str, required)
    roles → user_roles (List[str], defaults to [])
"""
from __future__ import annotations

from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from finance_analytics.config import get_settings

_bearer = HTTPBearer()


def _decode_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> tuple[str, list[str]]:
    """FastAPI dependency — returns (user_id, user_roles) from JWT Bearer token.

    Inject via: current_user: Tuple[str, List[str]] = Depends(get_current_user)
    """
    payload = _decode_token(credentials.credentials)
    user_id: str | None = payload.get("sub")
    user_roles: list[str] = payload.get("roles", [])
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing 'sub' field",
        )
    return user_id, user_roles


def require_role(role: str) -> Callable[..., tuple[str, list[str]]]:
    """FastAPI dependency factory — raises HTTP 403 if user lacks the required role.

    Usage:
        Depends(require_role("knowledge_engineer"))
    """
    def _check(current_user: tuple[str, list[str]] = Depends(get_current_user)) -> tuple[str, list[str]]:
        user_id, user_roles = current_user
        if role not in user_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{role}' required",
            )
        return current_user

    return _check
