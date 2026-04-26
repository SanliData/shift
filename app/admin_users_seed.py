"""Bootstrap owner admin accounts (idempotent)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin_passwords import hash_password
from .config import ADMIN_BOOTSTRAP_TEMP_PASSWORD
from .models import AdminUser
from .sqlite_migrations import ensure_admin_users_schema

logger = logging.getLogger(__name__)

# Stored lowercase; initial password = ADMIN_BOOTSTRAP_TEMP_PASSWORD (same for all seeded owners); first login forces change.
INITIAL_OWNER_EMAILS: tuple[str, ...] = (
    "sanlitiefundnetzbau@gmail.com",
    "isanli058@gmail.com",
    "isanli58@gmail.com",
)


def seed_owner_admin_users(db: Session) -> None:
    """Create owner accounts if missing. Initial password = shared temp (config); force_password_change=True."""
    ensure_admin_users_schema(db)
    now = datetime.now(timezone.utc)
    pw_plain = (ADMIN_BOOTSTRAP_TEMP_PASSWORD or "").strip() or "Damlacik242-28"
    pw_hash = hash_password(pw_plain)
    for raw in INITIAL_OWNER_EMAILS:
        email = (raw or "").strip().lower()
        if not email:
            continue
        existing = db.scalar(select(AdminUser).where(AdminUser.email == email))
        if existing:
            msg = f"admin bootstrap: already exists, skip ({email})"
            logger.info(msg)
            print(msg, flush=True)
            continue
        db.add(
            AdminUser(
                email=email,
                password_hash=pw_hash,
                role="owner",
                is_active=True,
                force_password_change=True,
                created_at=now,
            )
        )
        msg = f"admin bootstrap: created owner ({email}), shared temp password from config (forced change on login)"
        logger.info(msg)
        print(msg, flush=True)
    db.commit()
