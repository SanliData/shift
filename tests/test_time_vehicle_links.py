"""Vehicle QR time entry URLs: query and path forms."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from urllib.parse import parse_qs, urlparse

from app.database import SessionLocal
from app.main import app
from app.models import Device, ProvisionalWorker, TimeEntry


def _worker_gate_token(client: TestClient) -> str:
    r = client.get("/register-self", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert "/worker-register/" in loc
    return loc.rstrip("/").split("/worker-register/")[-1]


def _cleanup_provisional_phone(phone: str):
    with SessionLocal() as db:
        for pw in db.scalars(select(ProvisionalWorker).where(ProvisionalWorker.phone == phone)).all():
            db.execute(delete(TimeEntry).where(TimeEntry.provisional_worker_id == pw.id))
            db.execute(delete(Device).where(Device.provisional_worker_id == pw.id))
            db.delete(pw)
        db.commit()


def _device_client_after_provisional_register(phone: str) -> TestClient:
    """Reuse self-registration flow to obtain device_token cookie."""
    client = TestClient(app)
    tok = _worker_gate_token(client)
    r = client.post(
        f"/worker-register/{tok}/start",
        data={
            "full_name": "Time Link Tester",
            "phone": phone,
            "date_of_birth": "1990-01-15",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    loc = r.headers["location"]
    q = parse_qs(urlparse(loc).query)
    pid = int(q["pid"][0])
    key = q["key"][0]
    client.get(f"/register-self/device?pid={pid}&key={key}")
    c = client.post("/register-self/confirm", data={"pid": str(pid), "key": key})
    assert c.status_code == 200
    assert client.cookies.get("device_token")
    return client


def test_time_query_and_path_vehicle_slugs_load():
    phone = "+49 170 8889901"
    _cleanup_provisional_phone(phone)
    try:
        client = _device_client_after_provisional_register(phone)
        for slug in ("vehicle-01", "vehicle-02", "kamyon1"):
            r = client.get(f"/time?vehicle={slug}")
            assert r.status_code == 200, slug
            assert "Mesai Takip" in r.text
            assert slug in r.text
        p = client.get("/time/vehicle-01")
        assert p.status_code == 200
        assert "vehicle-01" in p.text
    finally:
        _cleanup_provisional_phone(phone)


def test_time_unknown_vehicle_returns_404_message():
    phone = "+49 170 8889902"
    _cleanup_provisional_phone(phone)
    try:
        client = _device_client_after_provisional_register(phone)
        r = client.get("/time?vehicle=no-such-vehicle-slug-xyz")
        assert r.status_code == 404
        assert "Araç QR kodu bulunamadı" in r.text
        r2 = client.get("/time/no-such-vehicle-slug-xyz")
        assert r2.status_code == 404
        assert "Araç QR kodu bulunamadı" in r2.text
    finally:
        _cleanup_provisional_phone(phone)


def test_time_valid_vehicle_no_cookie_shows_device_required_page():
    with TestClient(app) as client:
        r = client.get("/time?vehicle=vehicle-01")
        assert r.status_code == 200
        assert "Cihazınızı kaydedin ve ön kayıt oluşturun" in r.text
        assert "/time/vehicle-01/register" in r.text


def test_register_device_vehicle_query_without_token_shows_help_page():
    with TestClient(app) as client:
        r = client.get("/register-device?vehicle=vehicle-01")
        assert r.status_code == 200
        assert "Cihaz kaydı için link gerekli" in r.text
        assert "vehicle-01" in r.text
