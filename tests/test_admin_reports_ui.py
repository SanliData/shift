"""Admin reports UI: navigation, profiles, manual time entry correction."""
from __future__ import annotations

import secrets
import sys
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
for key in list(sys.modules):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]

from app.database import SessionLocal
from app.main import app
from app.models import Device, Employee, TimeEntry, TimeEntryCorrection, Vehicle
from app.routes.admin_time import fmt_datetime_local, now_berlin


def _cleanup_entry_and_device(entry_id: int | None, device_token: str | None):
    if not entry_id and not device_token:
        return
    with SessionLocal() as db:
        if entry_id:
            db.execute(delete(TimeEntryCorrection).where(TimeEntryCorrection.time_entry_id == entry_id))
            db.execute(delete(TimeEntry).where(TimeEntry.id == entry_id))
        if device_token:
            db.execute(delete(Device).where(Device.device_token == device_token))
        db.commit()


def test_import_main_ok():
    import app.main as m

    assert hasattr(m, "app")


def test_admin_time_dashboard_redirect():
    with TestClient(app) as client:
        r = client.get("/admin-time/dashboard", follow_redirects=False)
        assert r.status_code in (301, 302)
        loc = r.headers.get("location", "")
        assert loc.endswith("/admin-time/reports")


def test_reports_page_loads():
    with TestClient(app) as client:
        r = client.get("/admin-time/reports")
        assert r.status_code == 200
        assert "Günlük Mesai Detayı" in r.text


def test_employee_profile_vehicle_profile_and_edit_flow():
    token = f"adm-ui-{secrets.token_hex(6)}"
    entry_id: int | None = None
    try:
        emp_id: int
        emp2_id: int
        veh_id: int
        emp_name: str
        emp2_name: str
        veh_name: str
        veh_slug: str
        with SessionLocal() as db:
            emp = db.scalar(select(Employee).order_by(Employee.id))
            emp2 = db.scalar(select(Employee).order_by(Employee.id.desc()))
            veh = db.scalar(select(Vehicle).order_by(Vehicle.id))
            assert emp and emp2 and veh
            emp_id, emp2_id, veh_id = emp.id, emp2.id, veh.id
            assert emp_id != emp2_id, "Need at least two employees in DB for this test"
            emp_name, emp2_name, veh_name = emp.name, emp2.name, veh.name
            veh_slug = veh.qr_code_slug
            dev = Device(
                employee_id=emp_id,
                provisional_worker_id=None,
                device_token=token,
                created_at=now_berlin(),
                active=True,
            )
            db.add(dev)
            db.flush()
            st = now_berlin().replace(microsecond=0) - timedelta(days=2)
            en = st + timedelta(hours=9)
            entry = TimeEntry(
                employee_id=emp_id,
                provisional_worker_id=None,
                employee_name=emp_name,
                device_id=dev.id,
                vehicle_id=veh_id,
                start_time=st,
                end_time=en,
                total_minutes=540,
                regular_minutes=480,
                overtime_minutes=60,
                regular_cost=180.0,
                overtime_cost=33.75,
                total_cost=213.75,
                status="completed",
            )
            db.add(entry)
            db.commit()
            db.refresh(entry)
            entry_id = entry.id

        with TestClient(app) as client:
            pr = client.get(f"/admin-time/employees/{emp_id}/profile")
            assert pr.status_code == 200
            assert emp_name in pr.text

            vr = client.get(f"/admin-time/vehicles/{veh_id}/profile")
            assert vr.status_code == 200
            assert veh_name in vr.text
            assert veh_slug in vr.text

            er = client.get(f"/admin-time/time-entries/{entry_id}/edit")
            assert er.status_code == 200
            assert "Kayıtlı değerler" in er.text
            assert "Bu işlem rapor ve ücret hesaplamalarını değiştirecektir." in er.text

            old_clock_in = fmt_datetime_local(st)
            old_clock_out = fmt_datetime_local(en)
            bad = client.post(
                f"/admin-time/time-entries/{entry_id}/edit",
                data={
                    "employee_id": str(emp2_id),
                    "vehicle_id": str(veh_id),
                    "clock_in": old_clock_in,
                    "clock_out": old_clock_out,
                    "normal_hours": "",
                    "overtime_hours": "",
                    "reason": "   ",
                },
            )
            assert bad.status_code == 200
            assert "Düzeltme nedeni zorunludur." in bad.text

            post = client.post(
                f"/admin-time/time-entries/{entry_id}/edit",
                data={
                    "employee_id": str(emp2_id),
                    "vehicle_id": str(veh_id),
                    "clock_in": old_clock_in,
                    "clock_out": old_clock_out,
                    "normal_hours": "",
                    "overtime_hours": "",
                    "reason": "Test correction: reassign employee for UI test",
                },
                follow_redirects=False,
            )
            assert post.status_code in (301, 302)
            assert post.headers.get("location", "").endswith("/admin-time/reports")

        with SessionLocal() as db:
            row = db.get(TimeEntry, entry_id)
            assert row is not None
            assert row.employee_id == emp2_id
            assert row.employee_name == emp2_name
            cor = db.scalar(
                select(TimeEntryCorrection).where(TimeEntryCorrection.time_entry_id == entry_id).order_by(TimeEntryCorrection.id.desc())
            )
            assert cor is not None
            assert cor.new_employee_id == emp2_id
            assert cor.old_employee_id == emp_id
            assert "Test correction" in (cor.reason or "")
            assert cor.corrected_by == "admin"
            assert cor.corrected_by_role == "admin"
            assert cor.corrected_by_ip is not None

        with TestClient(app) as client:
            pr2 = client.get(f"/admin-time/employees/{emp_id}/profile")
            assert pr2.status_code == 200
            assert "Manuel düzeltme geçmişi" in pr2.text
            assert "Test correction" in pr2.text
            pv2 = client.get(f"/admin-time/vehicles/{veh_id}/profile")
            assert pv2.status_code == 200
            assert "Manuel düzeltme geçmişi" in pv2.text
    finally:
        _cleanup_entry_and_device(entry_id, token)
