"""Admin TestClient login helper (shared by integration tests)."""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

from app.config import ADMIN_BOOTSTRAP_TEMP_PASSWORD

ADMIN_TEST_EMAIL = "isanli058@gmail.com"


def admin_test_password() -> str:
    """Stable password used after first forced change in tests (see login_admin)."""
    return os.environ.get("ADMIN_DEFAULT_PASSWORD", "TestAdminPw123!")


def _post_change_password(client: TestClient, current_pw: str, new_pw: str) -> None:
    ch = client.post(
        "/admin-change-password",
        data={
            "current_password": current_pw,
            "new_password": new_pw,
            "new_password_confirm": new_pw,
        },
        follow_redirects=False,
    )
    assert ch.status_code in (302, 303), ch.text
    assert "/admin-time/reports" in (ch.headers.get("location") or "")


def login_admin(client: TestClient, *, email: str | None = None, password: str | None = None) -> None:
    """
    Establish an admin session. New installs use ADMIN_BOOTSTRAP_TEMP_PASSWORD + forced change;
    after first change, ADMIN_DEFAULT_PASSWORD (default TestAdminPw123!) is used.
    """
    em = (email or ADMIN_TEST_EMAIL).strip().lower()
    next_url = "/admin-time/reports"
    stable = admin_test_password()
    boot = (ADMIN_BOOTSTRAP_TEMP_PASSWORD or "").strip() or "Damlacik242-28"

    if password is not None:
        r = client.post(
            "/admin/login",
            data={"email": em, "password": password, "next": next_url},
            follow_redirects=False,
        )
        assert r.status_code in (302, 303), r.text
        loc = r.headers.get("location", "")
        if "/admin-change-password" in loc:
            _post_change_password(client, password, stable)
        return

    r = client.post(
        "/admin/login",
        data={"email": em, "password": stable, "next": next_url},
        follow_redirects=False,
    )
    if r.status_code in (302, 303):
        loc = r.headers.get("location", "")
        if "/admin-change-password" not in loc:
            return
        _post_change_password(client, stable, stable)
        return

    r2 = client.post(
        "/admin/login",
        data={"email": em, "password": boot, "next": next_url},
        follow_redirects=False,
    )
    assert r2.status_code in (302, 303), r2.text
    loc2 = r2.headers.get("location", "")
    if "/admin-change-password" in loc2:
        _post_change_password(client, boot, stable)
