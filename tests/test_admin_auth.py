"""Admin login, session cookie, forced password change, and protected /admin-time routes."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.admin_passwords import hash_password
from app.config import ADMIN_BOOTSTRAP_TEMP_PASSWORD
from app.database import SessionLocal
from app.main import app
from app.models import AdminUser
from tests.helpers_admin import ADMIN_TEST_EMAIL, admin_test_password, login_admin


def test_admin_time_redirects_to_login_without_session():
    with TestClient(app) as client:
        r = client.get("/admin-time/reports", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers.get("location", "").startswith("/admin/login")


def test_login_case_insensitive_email():
    with TestClient(app) as warm:
        login_admin(warm)
    with TestClient(app) as c2:
        r = c2.post(
            "/admin/login",
            data={
                "email": "IsAnLi058@Gmail.Com",
                "password": admin_test_password(),
                "next": "/admin-time/reports",
            },
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert c2.cookies.get("admin_session")


def test_login_then_admin_reports_ok():
    with TestClient(app) as client:
        login_admin(client)
        r = client.get("/admin-time/reports")
        assert r.status_code == 200
        assert "Günlük Mesai Detayı" in r.text


def test_logout_clears_session():
    with TestClient(app) as client:
        login_admin(client)
        assert client.cookies.get("admin_session")
        out = client.post("/admin/logout", follow_redirects=False)
        assert out.status_code == 303
        r = client.get("/admin-time", follow_redirects=False)
        assert r.status_code == 302


def test_login_rejects_bad_password():
    with TestClient(app) as client:
        r = client.post(
            "/admin/login",
            data={"email": ADMIN_TEST_EMAIL, "password": "not-the-real-password-xyz", "next": "/admin-time/reports"},
            follow_redirects=False,
        )
        assert r.status_code == 200
        assert "hatalı" in r.text.lower() or "E-posta" in r.text


def test_bootstrap_temp_password_login_forces_change_then_reports():
    """Bootstrap login (shared temp password) then /admin-change-password then /admin-time access."""
    em = "isanli58@gmail.com"
    boot = (ADMIN_BOOTSTRAP_TEMP_PASSWORD or "").strip() or "Damlacik242-28"
    new_pw = "Xy9!kLm2Qp" + "a" * 8  # distinct from email, length >= 8
    with SessionLocal() as db:
        u = db.scalar(select(AdminUser).where(AdminUser.email == em))
        assert u is not None
        u.password_hash = hash_password(boot)
        u.force_password_change = True
        db.commit()
    try:
        with TestClient(app) as client:
            r = client.post(
                "/admin/login",
                data={"email": em, "password": boot, "next": "/admin-time/reports"},
                follow_redirects=False,
            )
            assert r.status_code == 303
            assert "admin-change-password" in (r.headers.get("location") or "")
            block = client.get("/admin-time/reports", follow_redirects=False)
            assert block.status_code == 302
            assert "admin-change-password" in (block.headers.get("location") or "")
            ch = client.post(
                "/admin-change-password",
                data={
                    "current_password": boot,
                    "new_password": new_pw,
                    "new_password_confirm": new_pw,
                },
                follow_redirects=False,
            )
            assert ch.status_code == 303
            assert "/admin-time/reports" in (ch.headers.get("location") or "")
            ok = client.get("/admin-time/reports")
            assert ok.status_code == 200
    finally:
        with SessionLocal() as db:
            u = db.scalar(select(AdminUser).where(AdminUser.email == em))
            u.password_hash = hash_password(boot)
            u.force_password_change = True
            db.commit()


def test_new_password_cannot_equal_email():
    em = "isanli58@gmail.com"
    boot = (ADMIN_BOOTSTRAP_TEMP_PASSWORD or "").strip() or "Damlacik242-28"
    with SessionLocal() as db:
        u = db.scalar(select(AdminUser).where(AdminUser.email == em))
        assert u is not None
        u.password_hash = hash_password(boot)
        u.force_password_change = True
        db.commit()
    try:
        with TestClient(app) as client:
            client.post(
                "/admin/login",
                data={"email": em, "password": boot, "next": "/admin-time/reports"},
                follow_redirects=False,
            )
            bad = client.post(
                "/admin-change-password",
                data={
                    "current_password": boot,
                    "new_password": em,
                    "new_password_confirm": em,
                },
                follow_redirects=False,
            )
            assert bad.status_code == 200
            assert "aynı" in bad.text.lower() or "e-posta" in bad.text.lower()
    finally:
        with SessionLocal() as db:
            u = db.scalar(select(AdminUser).where(AdminUser.email == em))
            u.password_hash = hash_password(boot)
            u.force_password_change = True
            db.commit()
