"""Self-registration provisional worker → time tracking → admin approval."""
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse

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
from app.models import Device, Employee, ProvisionalWorker, TimeEntry


def _cleanup_provisional_phone(phone: str):
    with SessionLocal() as db:
        for pw in db.scalars(select(ProvisionalWorker).where(ProvisionalWorker.phone == phone)).all():
            db.execute(delete(TimeEntry).where(TimeEntry.provisional_worker_id == pw.id))
            db.execute(delete(Device).where(Device.provisional_worker_id == pw.id))
            db.delete(pw)
        for emp in db.scalars(select(Employee).where(Employee.phone_number == phone)).all():
            db.execute(delete(TimeEntry).where(TimeEntry.employee_id == emp.id))
            db.execute(delete(Device).where(Device.employee_id == emp.id))
            db.delete(emp)
        db.commit()


def test_provisional_register_confirm_and_time_page():
    phone = "+49 170 8887701"
    _cleanup_provisional_phone(phone)
    try:
        with TestClient(app) as client:
            r = client.post(
                "/register-self/start",
                data={
                    "full_name": "Prov Flow User",
                    "phone": phone,
                    "date_of_birth": "1992-06-01",
                },
                follow_redirects=False,
            )
            assert r.status_code == 303
            loc = r.headers["location"]
            q = parse_qs(urlparse(loc).query)
            pid = int(q["pid"][0])
            key = q["key"][0]
            g = client.get(f"/register-self/device?pid={pid}&key={key}")
            assert g.status_code == 200
            assert "Bu cihazı kaydet" in g.text
            c = client.post("/register-self/confirm", data={"pid": str(pid), "key": key})
            assert c.status_code == 200
            assert "Mesai ekranına git" in c.text or "Cihaz kaydedildi" in c.text
            assert client.cookies.get("device_token")
            t = client.get("/time?vehicle=vehicle-01")
            assert t.status_code == 200
            assert "Prov Flow User" in t.text
    finally:
        _cleanup_provisional_phone(phone)


def test_provisional_approve_migrates_to_employee():
    phone = "+49 170 8887702"
    _cleanup_provisional_phone(phone)
    try:
        with TestClient(app) as client:
            r = client.post(
                "/register-self/start",
                data={
                    "full_name": "Onay Test Kişi",
                    "phone": phone,
                    "date_of_birth": "1991-05-05",
                },
                follow_redirects=False,
            )
            q = parse_qs(urlparse(r.headers["location"]).query)
            pid = int(q["pid"][0])
            key = q["key"][0]
            client.post("/register-self/confirm", data={"pid": str(pid), "key": key})
            ap = client.post(
                f"/admin-time/provisional-workers/{pid}/approve",
                data={
                    "hourly_rate": "18.5",
                    "overtime_multiplier": "1.5",
                    "active": "true",
                },
            )
            assert ap.status_code == 200
        with SessionLocal() as db:
            pw = db.scalar(select(ProvisionalWorker).where(ProvisionalWorker.id == pid))
            assert pw is not None and pw.status == "deactivated"
            emp = db.scalar(select(Employee).where(Employee.phone_number == phone))
            assert emp is not None
            dev = db.scalar(select(Device).where(Device.employee_id == emp.id))
            assert dev is not None and dev.provisional_worker_id is None
    finally:
        _cleanup_provisional_phone(phone)
