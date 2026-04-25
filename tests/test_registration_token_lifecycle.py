from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Device, Employee, RegistrationToken


def test_registration_token_lifecycle():
    with SessionLocal() as db:
        emp = Employee(
            name="Lifecycle Test User",
            phone_number="+49 170 1234567",
            hourly_rate=10,
            overtime_multiplier=1.5,
            overtime_hourly_rate=15,
            active=True,
        )
        db.add(emp)
        db.commit()
        db.refresh(emp)
        employee_id = emp.id

    with TestClient(app) as client:
        # generate link -> used=0
        r1 = client.get(f"/admin-time/employees/{employee_id}/device-link")
        assert r1.status_code == 200
        payload1 = r1.json()
        token1 = payload1["token"]
        assert payload1["used"] is False

    with SessionLocal() as db:
        row1 = db.scalar(select(RegistrationToken).where(RegistrationToken.token == token1))
        assert row1 is not None
        assert row1.used is False

    with TestClient(app) as client:
        # open register link once -> device created + used=1
        first_open = client.get(f"/register-device?token={token1}")
        assert "Cihaz başarıyla kaydedildi" in first_open.text
        # open same link second time -> invalid/used
        second_open = client.get(f"/register-device?token={token1}")
        assert "Geçersiz veya kullanılmış token" in second_open.text
        # regenerate -> new used=0 token
        regen = client.post(f"/admin-time/employees/{employee_id}/regenerate-link", data={})
        assert regen.status_code == 200
        r2 = client.get(f"/admin-time/employees/{employee_id}/device-link")
        payload2 = r2.json()
        token2 = payload2["token"]
        assert token2 != token1

    with SessionLocal() as db:
        row1 = db.scalar(select(RegistrationToken).where(RegistrationToken.token == token1))
        row2 = db.scalar(select(RegistrationToken).where(RegistrationToken.token == token2))
        assert row1 is not None and row1.used is True
        assert row2 is not None and row2.used is False
        db.query(Device).filter(Device.employee_id == employee_id).delete()
        db.query(RegistrationToken).filter(RegistrationToken.employee_id == employee_id).delete()
        emp = db.scalar(select(Employee).where(Employee.id == employee_id))
        if emp:
            db.delete(emp)
        db.commit()


def test_device_link_skips_used_tokens_even_if_active_true():
    with SessionLocal() as db:
        emp = Employee(
            name="Used Token Guard User",
            phone_number="+49 170 1239999",
            hourly_rate=10,
            overtime_multiplier=1.5,
            overtime_hourly_rate=15,
            active=True,
        )
        db.add(emp)
        db.commit()
        db.refresh(emp)
        employee_id = emp.id
        # Simulate inconsistent production row.
        bad = RegistrationToken(
            employee_id=employee_id,
            token="bad-used-token-row",
            active=True,
            used=True,
            created_at=datetime.now(ZoneInfo("Europe/Berlin")),
        )
        db.add(bad)
        db.commit()

    with TestClient(app) as client:
        r = client.get(f"/admin-time/employees/{employee_id}/device-link")
        assert r.status_code == 200
        payload = r.json()
        assert payload["used"] is False
        assert payload["token"] != "bad-used-token-row"

    with SessionLocal() as db:
        db.query(RegistrationToken).filter(RegistrationToken.employee_id == employee_id).delete()
        db.query(Device).filter(Device.employee_id == employee_id).delete()
        emp = db.scalar(select(Employee).where(Employee.id == employee_id))
        if emp:
            db.delete(emp)
        db.commit()
