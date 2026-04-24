import sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import Base, get_db
from app.main import DEVICE_COOKIE, app
from app.models import Device, Employee, Vehicle

BERLIN_TZ = ZoneInfo("Europe/Berlin")


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    session: Session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db_session: Session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def seeded_data(db_session: Session):
    employee = Employee(name="Mehmet Yilmaz", active=True)
    vehicle1 = Vehicle(name="vehicle-01", qr_code_slug="vehicle-01")
    vehicle2 = Vehicle(name="vehicle-02", qr_code_slug="vehicle-02")
    db_session.add_all([employee, vehicle1, vehicle2])
    db_session.commit()
    db_session.refresh(employee)
    db_session.refresh(vehicle1)
    db_session.refresh(vehicle2)
    return {"employee": employee, "vehicle1": vehicle1, "vehicle2": vehicle2}


@pytest.fixture()
def registered_device(db_session: Session, seeded_data):
    employee = seeded_data["employee"]
    token = "test_device_token_123"
    device = Device(
        employee_id=employee.id,
        device_token=token,
        created_at=datetime.now(BERLIN_TZ),
        active=True,
    )
    db_session.add(device)
    db_session.commit()
    db_session.refresh(device)
    return {"device": device, "token": token, "employee": employee}


def set_device_cookie(client: TestClient, token: str):
    client.cookies.set(DEVICE_COOKIE, token)
