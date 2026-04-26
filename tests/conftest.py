"""Pytest defaults: admin env and DB bootstrap (startup runs once)."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ADMIN_DEFAULT_PASSWORD", "TestAdminPw123!")
os.environ.setdefault("ADMIN_SESSION_SECRET", "pytest-admin-session-secret-not-for-prod")
os.environ.setdefault("SMTP_HOST", "__test__")


@pytest.fixture(scope="session", autouse=True)
def _ensure_app_startup():
    """Trigger FastAPI lifespan/startup so admin_users and migrations exist before tests."""
    from app.main import app

    with TestClient(app) as client:
        client.get("/admin/login")
    yield
