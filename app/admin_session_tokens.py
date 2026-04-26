"""Signed session tokens (JWT) for admin UI."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt

from .config import ADMIN_SESSION_SECRET

ADMIN_JWT_ALG = "HS256"
SESSION_DAYS = 14


def issue_admin_session_token(*, user_id: int, email: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": now + timedelta(days=SESSION_DAYS),
    }
    return jwt.encode(payload, ADMIN_SESSION_SECRET, algorithm=ADMIN_JWT_ALG)


def decode_admin_session_token(token: str) -> dict | None:
    if not token or not str(token).strip():
        return None
    try:
        return jwt.decode(
            str(token).strip(),
            ADMIN_SESSION_SECRET,
            algorithms=[ADMIN_JWT_ALG],
        )
    except jwt.PyJWTError:
        return None
