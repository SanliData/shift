"""HMAC digest for password reset tokens (raw token never stored in DB)."""

from __future__ import annotations

import hashlib
import hmac

from .config import REGISTRATION_SIGNING_SECRET


def hash_password_reset_token(raw: str) -> str:
    return hmac.new(
        REGISTRATION_SIGNING_SECRET.encode("utf-8"),
        (raw or "").encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
