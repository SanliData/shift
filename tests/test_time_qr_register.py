"""One-step vehicle QR registration → device bind → time tracking → admin approval."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.main import app
from app.models import Device, Employee, EmployeePhone, ProvisionalWorker, TimeEntry
from app.routes.time_routes import clear_time_qr_register_rate_limit
from tests.helpers_admin import login_admin


def _cleanup_phone(phone: str):
    with SessionLocal() as db:
        for pw in db.scalars(select(ProvisionalWorker).where(ProvisionalWorker.phone == phone)).all():
            db.execute(delete(TimeEntry).where(TimeEntry.provisional_worker_id == pw.id))
            db.execute(delete(Device).where(Device.provisional_worker_id == pw.id))
            db.delete(pw)
        emp = db.scalar(select(Employee).where(Employee.phone_number == phone))
        if emp:
            db.execute(delete(EmployeePhone).where(EmployeePhone.employee_id == emp.id))
            db.execute(delete(TimeEntry).where(TimeEntry.employee_id == emp.id))
            db.execute(delete(Device).where(Device.employee_id == emp.id))
            db.delete(emp)
        db.commit()


@pytest.fixture(autouse=True)
def _reset_qr_rate():
    clear_time_qr_register_rate_limit()
    yield
    clear_time_qr_register_rate_limit()


def test_time_qr_register_shows_form_without_cookie():
    with TestClient(app) as client:
        r = client.get("/time?vehicle=vehicle-01")
        assert r.status_code == 200
        assert "Cihazınızı kaydedin ve ön kayıt oluşturun" in r.text
        assert "/time/vehicle-01/register" in r.text


def test_time_qr_register_submit_binds_device_and_allows_time_start():
    phone = "+49 170 9998811"
    _cleanup_phone(phone)
    try:
        with TestClient(app) as client:
            g = client.get("/time/vehicle-01")
            assert g.status_code == 200
            p = client.post(
                "/time/vehicle-01/register",
                data={
                    "full_name": "QR Reg Worker",
                    "phone": phone,
                    "date_of_birth": "1988-04-12",
                    "secondary_phone": "",
                    "primary_phone_temporary": "",
                    "registration_note": "Test note",
                },
                follow_redirects=False,
            )
            assert p.status_code == 303, p.text
            assert client.cookies.get("device_token")
            loc = p.headers.get("location") or ""
            assert "/time/vehicle-01" in loc
            dash = client.get(loc, follow_redirects=False)
            assert dash.status_code == 200
            assert "Mesai Takip" in dash.text
            assert "QR Reg Worker" in dash.text
            st = client.post(
                "/time/start",
                data={"vehicle_slug": "vehicle-01"},
                follow_redirects=False,
            )
            assert st.status_code == 303
            sp = client.post("/time/stop", data={"vehicle_slug": "vehicle-01"}, follow_redirects=False)
            assert sp.status_code == 303
        with SessionLocal() as db:
            pw = db.scalar(select(ProvisionalWorker).where(ProvisionalWorker.phone == phone))
            assert pw is not None
            assert pw.status == "active"
            te = db.scalar(
                select(TimeEntry).where(
                    TimeEntry.provisional_worker_id == pw.id,
                    TimeEntry.status == "completed",
                )
            )
            assert te is not None
            assert te.employee_id is None
            pid = pw.id
        with TestClient(app) as admin_client:
            login_admin(admin_client)
            ap = admin_client.post(
                f"/admin-time/provisional-workers/{pid}/approve",
                data={
                    "hourly_rate": "21",
                    "overtime_multiplier": "1.5",
                    "active": "true",
                },
            )
            assert ap.status_code == 200
        with SessionLocal() as db:
            pw2 = db.get(ProvisionalWorker, pid)
            assert pw2 is not None and pw2.status == "deactivated"
            emp = db.scalar(select(Employee).where(Employee.phone_number == phone))
            assert emp is not None
            migrated = db.scalar(
                select(TimeEntry).where(TimeEntry.employee_id == emp.id, TimeEntry.status == "completed")
            )
            assert migrated is not None
    finally:
        _cleanup_phone(phone)


def test_time_qr_register_invalid_vehicle_404():
    with TestClient(app) as client:
        r = client.get("/time?vehicle=not-a-real-slug-zzz")
        assert r.status_code == 404
