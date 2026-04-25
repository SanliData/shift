from datetime import datetime
from pathlib import Path
import sys
from urllib.parse import unquote
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
for key in list(sys.modules):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]

from app.database import SessionLocal
from app.main import app
from app.models import Device, Employee, RegistrationToken
from app.routes.admin_time import build_whatsapp_link


def _create_employee(name: str) -> int:
    with SessionLocal() as db:
        emp = Employee(
            name=name,
            phone_number="+49 170 1234567",
            hourly_rate=10,
            overtime_multiplier=1.5,
            overtime_hourly_rate=15,
            active=True,
        )
        db.add(emp)
        db.commit()
        db.refresh(emp)
        return emp.id


def _cleanup_employee(employee_id: int):
    with SessionLocal() as db:
        db.query(Device).filter(Device.employee_id == employee_id).delete()
        db.query(RegistrationToken).filter(RegistrationToken.employee_id == employee_id).delete()
        emp = db.scalar(select(Employee).where(Employee.id == employee_id))
        if emp:
            db.delete(emp)
        db.commit()


def test_device_link_returns_only_unused_tokens_and_register_link_is_gone():
    employee_id = _create_employee("Token Source User")
    try:
        with TestClient(app) as client:
            p1 = client.get(f"/admin-time/employees/{employee_id}/device-link").json()
            dep = client.post("/admin-time/register-link", data={"employee_id": employee_id})
            assert dep.status_code == 410
            assert "device-link" in (dep.json().get("detail") or "")
            p3 = client.get(f"/admin-time/employees/{employee_id}/device-link").json()
        assert p1["used"] is False
        assert p1["active"] is True
        assert p3["used"] is False
        assert p3["active"] is True
        assert p1["token"] == p3["token"]
        assert "created_at" in p3 and p3["created_at"] is not None
    finally:
        _cleanup_employee(employee_id)


def test_whatsapp_helper_includes_register_link_from_device_link():
    employee_id = _create_employee("WA Link User")
    try:
        with TestClient(app) as client:
            payload = client.get(f"/admin-time/employees/{employee_id}/device-link").json()
        reg_link = payload["register_link"]
        assert payload["active"] is True and payload["used"] is False
        wa = build_whatsapp_link("491701234567", reg_link)
        assert reg_link in unquote(wa)
    finally:
        _cleanup_employee(employee_id)


def test_device_link_ignores_used_true_active_true_legacy_token():
    employee_id = _create_employee("Used Token Guard User")
    try:
        with SessionLocal() as db:
            db.add(
                RegistrationToken(
                    employee_id=employee_id,
                    token="bad-used-token-row",
                    active=True,
                    used=True,
                    created_at=datetime.now(ZoneInfo("Europe/Berlin")),
                )
            )
            db.commit()
        with TestClient(app) as client:
            payload = client.get(f"/admin-time/employees/{employee_id}/device-link").json()
        assert payload["used"] is False
        assert payload["token"] != "bad-used-token-row"
    finally:
        _cleanup_employee(employee_id)


def test_regenerate_disables_old_and_creates_new_valid_token():
    employee_id = _create_employee("Regenerate User")
    try:
        with TestClient(app) as client:
            first = client.get(f"/admin-time/employees/{employee_id}/device-link").json()
            client.post(f"/admin-time/employees/{employee_id}/regenerate-link", data={})
            second = client.get(f"/admin-time/employees/{employee_id}/device-link").json()
        assert first["token"] != second["token"]
        assert second["used"] is False and second["active"] is True
        with SessionLocal() as db:
            first_row = db.scalar(select(RegistrationToken).where(RegistrationToken.token == first["token"]))
            second_row = db.scalar(select(RegistrationToken).where(RegistrationToken.token == second["token"]))
            assert first_row is not None and first_row.active is False
            assert second_row is not None and second_row.used is False and second_row.active is True
    finally:
        _cleanup_employee(employee_id)


def test_register_device_success_then_second_use_rejected():
    employee_id = _create_employee("Register Device User")
    try:
        with TestClient(app) as client:
            payload = client.get(f"/admin-time/employees/{employee_id}/device-link").json()
            token = payload["token"]
            first = client.get(f"/register-device?token={token}")
            confirm = client.post("/register-device/confirm", data={"token": token})
            second = client.post("/register-device/confirm", data={"token": token})
        assert "Cihazı kaydet" in first.text
        assert "Cihaz başarıyla kaydedildi" in confirm.text
        assert "Geçersiz veya kullanılmış token" in second.text
        with SessionLocal() as db:
            row = db.scalar(select(RegistrationToken).where(RegistrationToken.token == token))
            assert row is not None and row.used is True and row.active is False
    finally:
        _cleanup_employee(employee_id)


def test_register_device_failure_does_not_consume_valid_token():
    employee_id = _create_employee("Failure Guard User")
    try:
        with TestClient(app) as client:
            payload = client.get(f"/admin-time/employees/{employee_id}/device-link").json()
            token = payload["token"]
            bad = client.get("/register-device?token=this-token-does-not-exist")
        assert "Geçersiz veya kullanılmış token" in bad.text
        with SessionLocal() as db:
            row = db.scalar(select(RegistrationToken).where(RegistrationToken.token == token))
            assert row is not None and row.used is False and row.active is True
    finally:
        _cleanup_employee(employee_id)


def test_link_preview_does_not_consume_token():
    employee_id = _create_employee("Preview User")
    try:
        with TestClient(app) as client:
            payload = client.get(f"/admin-time/employees/{employee_id}/device-link").json()
            token = payload["token"]
            preview = client.get(
                f"/register-device?token={token}",
                headers={"user-agent": "WhatsApp/2.24"},
            )
            assert "Kayıt linki hazır. Lütfen linke tıklayın." in preview.text
            with SessionLocal() as db:
                row = db.scalar(select(RegistrationToken).where(RegistrationToken.token == token))
                assert row is not None and row.used is False and row.active is True
            confirm = client.post("/register-device/confirm", data={"token": token})
            assert "Cihaz başarıyla kaydedildi" in confirm.text
    finally:
        _cleanup_employee(employee_id)
