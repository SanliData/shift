"""Self-registration provisional worker → time tracking → admin approval."""
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.main import app
from app.models import Device, Employee, EmployeePhone, ProvisionalWorker, TimeEntry
from tests.helpers_admin import login_admin


def _cleanup_provisional_phone(phone: str):
    with SessionLocal() as db:
        for pw in db.scalars(select(ProvisionalWorker).where(ProvisionalWorker.phone == phone)).all():
            db.execute(delete(TimeEntry).where(TimeEntry.provisional_worker_id == pw.id))
            db.execute(delete(Device).where(Device.provisional_worker_id == pw.id))
            db.delete(pw)
        for emp in db.scalars(select(Employee).where(Employee.phone_number == phone)).all():
            db.execute(delete(EmployeePhone).where(EmployeePhone.employee_id == emp.id))
            db.execute(delete(TimeEntry).where(TimeEntry.employee_id == emp.id))
            db.execute(delete(Device).where(Device.employee_id == emp.id))
            db.delete(emp)
        db.commit()


def _worker_gate_token(client: TestClient) -> str:
    r = client.get("/register-self", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert "/worker-register/" in loc
    return loc.rstrip("/").split("/worker-register/")[-1]


def test_register_self_redirects_to_token_url():
    with TestClient(app) as client:
        r = client.get("/register-self", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"].startswith("/worker-register/")
        g = client.get(r.headers["location"])
        assert g.status_code == 200
        assert "Ön kayıt" in g.text


def test_worker_register_invalid_token():
    with TestClient(app) as client:
        bad = client.get("/worker-register/not-a-real-token-xyz")
        assert bad.status_code == 404


def test_admin_worker_qr_png():
    with TestClient(app) as client:
        login_admin(client)
        qr = client.get("/admin-time/worker-registration/qr")
        assert qr.status_code == 200
        assert qr.headers.get("content-type", "").startswith("image/png")


def test_admin_dashboard_shows_worker_register_link():
    with TestClient(app) as client:
        login_admin(client)
        p = client.get("/admin-time")
        assert p.status_code == 200
        assert "/worker-register/" in p.text


def test_worker_registration_regenerate_changes_token():
    with TestClient(app) as client:
        login_admin(client)
        a = _worker_gate_token(client)
        reg = client.post("/admin-time/worker-registration/regenerate", follow_redirects=False)
        assert reg.status_code == 303
        b = _worker_gate_token(client)
        assert a != b


def test_employee_profile_add_and_remove_extra_phone():
    extra = "+49 179 8889900"
    with SessionLocal() as db:
        emp = db.scalar(select(Employee).where(Employee.name == "Ali Demir"))
        assert emp is not None
        eid = emp.id
        for ep in db.scalars(select(EmployeePhone).where(EmployeePhone.employee_id == eid, EmployeePhone.phone == extra)).all():
            db.delete(ep)
        db.commit()
    try:
        with TestClient(app) as client:
            login_admin(client)
            add = client.post(
                f"/admin-time/employees/{eid}/phones/add",
                data={"phone": extra},
                follow_redirects=False,
            )
            assert add.status_code == 303
            prof = client.get(f"/admin-time/employees/{eid}/profile")
            assert prof.status_code == 200
            assert extra in prof.text
        with SessionLocal() as db:
            ep = db.scalar(select(EmployeePhone).where(EmployeePhone.employee_id == eid, EmployeePhone.phone == extra))
            assert ep is not None
            pid = ep.id
        with TestClient(app) as client:
            login_admin(client)
            rm = client.post(
                f"/admin-time/employees/{eid}/phones/{pid}/delete",
                follow_redirects=False,
            )
            assert rm.status_code == 303
    finally:
        with SessionLocal() as db:
            ep = db.scalar(select(EmployeePhone).where(EmployeePhone.employee_id == eid, EmployeePhone.phone == extra))
            if ep:
                db.delete(ep)
            db.commit()


def test_provisional_register_confirm_and_time_page():
    phone = "+49 170 8887701"
    _cleanup_provisional_phone(phone)
    try:
        with TestClient(app) as client:
            tok = _worker_gate_token(client)
            r = client.post(
                f"/worker-register/{tok}/start",
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


def test_duplicate_permanent_phone_on_worker_form():
    with TestClient(app) as client:
        tok = _worker_gate_token(client)
        r = client.post(
            f"/worker-register/{tok}/start",
            data={
                "full_name": "Dup Test",
                "phone": "+49 170 0000001",
            },
            follow_redirects=False,
        )
        assert r.status_code == 200
        assert "Geçici telefon" in r.text or "başka bir çalışanda" in r.text


def test_secondary_and_temporary_provisional():
    phone = "+49 170 8887703"
    sec = "+49 170 8887704"
    _cleanup_provisional_phone(phone)
    _cleanup_provisional_phone(sec)
    try:
        with TestClient(app) as client:
            tok = _worker_gate_token(client)
            r = client.post(
                f"/worker-register/{tok}/start",
                data={
                    "full_name": "İkinci Tel User",
                    "phone": phone,
                    "secondary_phone": sec,
                    "primary_phone_temporary": "true",
                    "date_of_birth": "",
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
            assert sec.replace(" ", "") in g.text.replace(" ", "") or sec in g.text
            assert "Geçici" in g.text
        with SessionLocal() as db:
            pw = db.scalar(select(ProvisionalWorker).where(ProvisionalWorker.id == pid))
            assert pw.secondary_phone and sec in pw.secondary_phone
            assert pw.primary_phone_is_temporary is True
    finally:
        _cleanup_provisional_phone(phone)
        _cleanup_provisional_phone(sec)


def test_provisional_approve_migrates_to_employee():
    phone = "+49 170 8887702"
    _cleanup_provisional_phone(phone)
    try:
        with TestClient(app) as client:
            tok = _worker_gate_token(client)
            r = client.post(
                f"/worker-register/{tok}/start",
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
            login_admin(client)
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
