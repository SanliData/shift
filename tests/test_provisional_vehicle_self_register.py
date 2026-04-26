"""Self-service vehicle registration → admin approval."""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.main import app
from app.models import ProvisionalVehicle, PV_VEHICLE_PENDING, Vehicle
from app.sqlite_migrations import ensure_provisional_vehicle_schema
from tests.helpers_admin import login_admin


def _cleanup_by_name(name: str):
    with SessionLocal() as db:
        ensure_provisional_vehicle_schema(db)
        for pv in db.scalars(select(ProvisionalVehicle).where(ProvisionalVehicle.name == name)).all():
            vid = pv.vehicle_id
            db.delete(pv)
            if vid:
                db.execute(delete(Vehicle).where(Vehicle.id == vid))
        db.commit()


def test_register_self_vehicle_form_and_pending_flow():
    marker = "TestVehicleSelfRegXYZ"
    _cleanup_by_name(marker)
    try:
        with TestClient(app) as client:
            g = client.get("/register-self-vehicle")
            assert g.status_code == 200
            assert "ön kayıt" in g.text.lower() or "Araç" in g.text

            r = client.post(
                "/register-self-vehicle/start",
                data={"name": marker, "type": "truck", "notes": "e2e", "qr_slug_hint": ""},
                follow_redirects=False,
            )
            assert r.status_code == 303
            assert "/register-self-vehicle/done" in (r.headers.get("location") or "")

            d = client.get("/register-self-vehicle/done")
            assert d.status_code == 200

            login_admin(client)
            qr = client.get("/admin-time/register-self-vehicle/qr")
            assert qr.status_code == 200
            assert qr.headers.get("content-type", "").startswith("image/png")

        with SessionLocal() as db:
            pv = db.scalar(select(ProvisionalVehicle).where(ProvisionalVehicle.name == marker))
            assert pv is not None
            assert pv.status == PV_VEHICLE_PENDING
            pv_id = pv.id

        with TestClient(app) as client:
            login_admin(client)
            ap = client.post(f"/admin-time/provisional-vehicles/{pv_id}/approve", data={"qr_code_slug": ""})
            assert ap.status_code == 200

        with SessionLocal() as db:
            pv2 = db.scalar(select(ProvisionalVehicle).where(ProvisionalVehicle.name == marker))
            assert pv2 is not None
            assert pv2.vehicle_id is not None
            veh = db.get(Vehicle, pv2.vehicle_id)
            assert veh is not None
            assert veh.name == marker
            db.delete(pv2)
            db.delete(veh)
            db.commit()
    finally:
        _cleanup_by_name(marker)
