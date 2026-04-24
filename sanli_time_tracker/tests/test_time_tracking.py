from datetime import timedelta

from app.main import DEVICE_COOKIE, EXTERNAL_REDIRECT_URL, as_berlin, now_berlin
from app.models import TimeEntry


def set_device_cookie(client, token: str):
    client.cookies.set(DEVICE_COOKIE, token)


def test_unregistered_device_redirects_from_time_page(client, seeded_data):
    response = client.get("/time?vehicle=vehicle-01", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == EXTERNAL_REDIRECT_URL


def test_registered_device_can_access_time_page(client, registered_device):
    set_device_cookie(client, registered_device["token"])
    response = client.get("/time?vehicle=vehicle-01")
    assert response.status_code == 200
    assert "Mesai Ekranı" in response.text
    assert registered_device["employee"].name in response.text


def test_start_shift_creates_active_entry(client, db_session, registered_device):
    set_device_cookie(client, registered_device["token"])
    response = client.post(
        "/time/start",
        data={"vehicle_slug": "vehicle-01"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    entry = db_session.query(TimeEntry).filter_by(employee_id=registered_device["employee"].id).first()
    assert entry is not None
    assert entry.status == "active"
    assert entry.start_time is not None


def test_second_start_is_blocked_when_active_exists(client, db_session, registered_device):
    set_device_cookie(client, registered_device["token"])
    first = client.post("/time/start", data={"vehicle_slug": "vehicle-01"}, follow_redirects=False)
    assert first.status_code == 303
    second = client.post("/time/start", data={"vehicle_slug": "vehicle-01"}, follow_redirects=False)
    assert second.status_code == 303
    assert "error=" in second.headers["location"]
    entries = db_session.query(TimeEntry).filter_by(employee_id=registered_device["employee"].id).all()
    assert len(entries) == 1


def test_stop_shift_completes_active_entry(client, db_session, registered_device):
    set_device_cookie(client, registered_device["token"])
    client.post("/time/start", data={"vehicle_slug": "vehicle-01"}, follow_redirects=False)
    response = client.post("/time/stop", data={"vehicle_slug": "vehicle-01"}, follow_redirects=False)
    assert response.status_code == 303

    entry = db_session.query(TimeEntry).filter_by(employee_id=registered_device["employee"].id).first()
    assert entry.status == "completed"
    assert entry.end_time is not None
    assert (entry.total_minutes or 0) >= 0


def test_stop_without_active_entry_is_blocked(client, db_session, registered_device):
    set_device_cookie(client, registered_device["token"])
    response = client.post("/time/stop", data={"vehicle_slug": "vehicle-01"}, follow_redirects=False)
    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    count = db_session.query(TimeEntry).count()
    assert count == 0


def test_overtime_calculated_over_8_hours(client, db_session, registered_device):
    set_device_cookie(client, registered_device["token"])
    client.post("/time/start", data={"vehicle_slug": "vehicle-01"}, follow_redirects=False)

    entry = db_session.query(TimeEntry).filter_by(employee_id=registered_device["employee"].id).first()
    # 9 saat önce başlatılmış gibi simüle et
    entry.start_time = as_berlin(now_berlin()) - timedelta(hours=9)
    db_session.commit()

    client.post("/time/stop", data={"vehicle_slug": "vehicle-01"}, follow_redirects=False)
    db_session.refresh(entry)
    assert entry.status == "completed"
    assert (entry.total_minutes or 0) >= 540
    assert (entry.overtime_minutes or 0) >= 60


def test_admin_panel_shows_records(client, registered_device):
    set_device_cookie(client, registered_device["token"])
    client.post("/time/start", data={"vehicle_slug": "vehicle-01"}, follow_redirects=False)
    client.post("/time/stop", data={"vehicle_slug": "vehicle-01"}, follow_redirects=False)
    response = client.get("/admin")
    assert response.status_code == 200
    assert "Admin Paneli" in response.text
    assert registered_device["employee"].name in response.text
    assert "Tamamlanan Mesailer" in response.text
