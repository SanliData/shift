"""Admin forgot / reset password via email (SMTP test capture)."""

from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.admin_reset_token_crypto import hash_password_reset_token
from app.database import SessionLocal
from app.email_smtp import clear_test_outbox, get_test_outbox
from app.config import ADMIN_BOOTSTRAP_TEMP_PASSWORD
from app.main import app
from app.models import AdminPasswordResetToken, AdminUser
from app.routes.admin_password_reset import clear_forgot_rate_limit
from tests.helpers_admin import ADMIN_TEST_EMAIL

_TOKEN_IN_LINK = re.compile(r"/admin-reset-password\?token=([^\"\s<>]+)")


@pytest.fixture(autouse=True)
def _reset_forgot_rate_and_outbox():
    clear_forgot_rate_limit()
    clear_test_outbox()
    yield
    clear_forgot_rate_limit()
    clear_test_outbox()


def _extract_token_from_last_email() -> str:
    box = get_test_outbox()
    assert box, "expected test outbox to contain an email"
    body = box[-1]["body"]
    m = _TOKEN_IN_LINK.search(body)
    assert m, body
    return m.group(1).strip()


def test_forgot_password_sends_capture_email_for_known_user():
    with TestClient(app) as client:
        r = client.post("/admin-forgot-password", data={"email": ADMIN_TEST_EMAIL}, follow_redirects=False)
        assert r.status_code == 200
        assert "kayıtlıysa" in r.text.lower() or "gönderilmiştir" in r.text.lower()
    box = get_test_outbox()
    assert len(box) >= 1
    assert box[-1]["to"].lower() == ADMIN_TEST_EMAIL.lower()
    assert "admin-reset-password" in box[-1]["body"]


def test_forgot_password_same_message_for_unknown_email():
    with TestClient(app) as client:
        r = client.post("/admin-forgot-password", data={"email": "not-a-real-user-xyz@example.com"}, follow_redirects=False)
        assert r.status_code == 200
        assert "kayıtlıysa" in r.text.lower()
    assert get_test_outbox() == []


def test_reset_password_valid_then_login():
    new_pw = "ResetOk9!" + "x" * 8
    with TestClient(app) as client:
        client.post("/admin-forgot-password", data={"email": ADMIN_TEST_EMAIL}, follow_redirects=False)
        raw = _extract_token_from_last_email()
        g = client.get(f"/admin-reset-password?token={raw}")
        assert g.status_code == 200
        assert "Yeni şifre" in g.text
        p = client.post(
            "/admin-reset-password",
            data={"token": raw, "new_password": new_pw, "confirm_password": new_pw},
            follow_redirects=False,
        )
        assert p.status_code == 303
        assert "reset=success" in (p.headers.get("location") or "")
        lg = client.post(
            "/admin/login",
            data={"email": ADMIN_TEST_EMAIL, "password": new_pw, "next": "/admin-time/reports"},
            follow_redirects=False,
        )
        assert lg.status_code == 303
    # restore bootstrap temp password for other tests
    with SessionLocal() as db:
        u = db.scalar(select(AdminUser).where(AdminUser.email == ADMIN_TEST_EMAIL))
        assert u is not None
        from app.admin_passwords import hash_password

        u.password_hash = hash_password(ADMIN_BOOTSTRAP_TEMP_PASSWORD)
        u.force_password_change = True
        db.commit()


def test_reset_password_reused_token_blocked():
    new_pw = "ReuseTst9!" + "y" * 8
    with TestClient(app) as client:
        client.post("/admin-forgot-password", data={"email": ADMIN_TEST_EMAIL}, follow_redirects=False)
        raw = _extract_token_from_last_email()
        p1 = client.post(
            "/admin-reset-password",
            data={"token": raw, "new_password": new_pw, "confirm_password": new_pw},
            follow_redirects=False,
        )
        assert p1.status_code == 303
        p2 = client.post(
            "/admin-reset-password",
            data={"token": raw, "new_password": new_pw + "2", "confirm_password": new_pw + "2"},
            follow_redirects=False,
        )
        assert p2.status_code == 400
    with SessionLocal() as db:
        u = db.scalar(select(AdminUser).where(AdminUser.email == ADMIN_TEST_EMAIL))
        from app.admin_passwords import hash_password

        u.password_hash = hash_password(ADMIN_BOOTSTRAP_TEMP_PASSWORD)
        u.force_password_change = True
        db.commit()


def test_reset_password_expired_token_blocked():
    with SessionLocal() as db:
        u = db.scalar(select(AdminUser).where(AdminUser.email == ADMIN_TEST_EMAIL))
        assert u is not None
        raw = "expired-test-token-raw-value-xyz"
        th = hash_password_reset_token(raw)
        now = datetime.now(timezone.utc)
        row = AdminPasswordResetToken(
            user_id=u.id,
            token_hash=th,
            expires_at=now - timedelta(minutes=1),
            used=False,
            created_at=now - timedelta(minutes=40),
        )
        db.add(row)
        db.commit()

    with TestClient(app) as client:
        g = client.get(f"/admin-reset-password?token={raw}")
        assert g.status_code == 400
        assert "geçersiz" in g.text.lower() or "Bağlantı" in g.text

    with SessionLocal() as db:
        tok_row = db.scalar(select(AdminPasswordResetToken).where(AdminPasswordResetToken.token_hash == th))
        if tok_row:
            db.delete(tok_row)
        db.commit()


def test_forgot_password_rate_limit():
    with TestClient(app) as client:
        for i in range(5):
            r = client.post("/admin-forgot-password", data={"email": ADMIN_TEST_EMAIL}, follow_redirects=False)
            assert r.status_code == 200, i
        r6 = client.post("/admin-forgot-password", data={"email": ADMIN_TEST_EMAIL}, follow_redirects=False)
        assert r6.status_code == 429
