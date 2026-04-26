#!/usr/bin/env python3
"""One-time / repeatable utility: reset known owner admin passwords to bootstrap temp (never prints it)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.admin_passwords import hash_password
from app.config import ADMIN_BOOTSTRAP_TEMP_PASSWORD
from app.database import SessionLocal
from app.models import AdminUser

TARGET_EMAILS: tuple[str, ...] = (
    "sanlitiefundnetzbau@gmail.com",
    "isanli058@gmail.com",
    "isanli58@gmail.com",
)


def main() -> None:
    pw_plain = (ADMIN_BOOTSTRAP_TEMP_PASSWORD or "").strip() or "Damlacik242-28"
    pw_hash = hash_password(pw_plain)
    updated: list[str] = []
    with SessionLocal() as db:
        for raw in TARGET_EMAILS:
            email = (raw or "").strip().lower()
            if not email:
                continue
            u = db.scalar(select(AdminUser).where(AdminUser.email == email))
            if u is None:
                continue
            u.password_hash = pw_hash
            u.force_password_change = True
            updated.append(u.email)
        db.commit()
    for em in updated:
        print(em)


if __name__ == "__main__":
    main()
