import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..config import BASE_URL, TIMEZONE, TIME_FALLBACK_URL
from ..database import get_db
from ..models import Device, Employee, TimeEntry, Vehicle

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

BERLIN_TZ = ZoneInfo(TIMEZONE)
DEVICE_COOKIE = "device_token"
FALLBACK_URL = TIME_FALLBACK_URL
logger = logging.getLogger(__name__)


def now_berlin() -> datetime:
    return datetime.now(BERLIN_TZ)


def as_berlin(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=BERLIN_TZ)
    return dt.astimezone(BERLIN_TZ)


def get_registered_device(db: Session, request: Request):
    token = request.cookies.get(DEVICE_COOKIE)
    if not token:
        return None
    return db.scalar(
        select(Device).where(Device.device_token == token, Device.active.is_(True))
    )


def get_active_entry(db: Session, employee_id: int):
    return db.scalar(
        select(TimeEntry)
        .where(TimeEntry.employee_id == employee_id, TimeEntry.status == "active")
        .order_by(desc(TimeEntry.start_time))
    )


def redirect_no_device_cookie():
    logger.debug("device_token cookie missing")
    return RedirectResponse(BASE_URL, status_code=302)


@router.get("/time", response_class=HTMLResponse)
def time_page(request: Request, vehicle: str, db: Session = Depends(get_db)):
    if not request.cookies.get(DEVICE_COOKIE):
        return redirect_no_device_cookie()
    device = get_registered_device(db, request)
    if not device:
        return RedirectResponse(FALLBACK_URL, status_code=302)

    vehicle_obj = db.scalar(select(Vehicle).where(Vehicle.qr_code_slug == vehicle, Vehicle.active.is_(True)))
    if not vehicle_obj:
        return RedirectResponse(FALLBACK_URL, status_code=302)

    active_entry = get_active_entry(db, device.employee_id)
    return templates.TemplateResponse(
        request=request,
        name="time.html",
        context={
            "request": request,
            "employee": device.employee,
            "vehicle": vehicle_obj,
            "active_entry": active_entry,
            "message": request.query_params.get("message", ""),
            "error": request.query_params.get("error", ""),
        },
    )


@router.post("/time/start")
def start_shift(request: Request, vehicle_slug: str = Form(...), db: Session = Depends(get_db)):
    if not request.cookies.get(DEVICE_COOKIE):
        return redirect_no_device_cookie()
    device = get_registered_device(db, request)
    if not device:
        return RedirectResponse(FALLBACK_URL, status_code=302)
    vehicle_obj = db.scalar(select(Vehicle).where(Vehicle.qr_code_slug == vehicle_slug, Vehicle.active.is_(True)))
    if not vehicle_obj:
        return RedirectResponse(FALLBACK_URL, status_code=302)

    if get_active_entry(db, device.employee_id):
        return RedirectResponse(
            f"/time?vehicle={vehicle_slug}&error=Aktif mesai zaten mevcut.",
            status_code=303,
        )

    db.add(
        TimeEntry(
            employee_id=device.employee_id,
            employee_name=device.employee.name,
            device_id=device.id,
            vehicle_id=vehicle_obj.id,
            start_time=now_berlin(),
            status="active",
        )
    )
    db.commit()
    return RedirectResponse(
        f"/time?vehicle={vehicle_slug}&message=Mesai başlatıldı.",
        status_code=303,
    )


@router.post("/time/stop")
def stop_shift(request: Request, vehicle_slug: str = Form(...), db: Session = Depends(get_db)):
    if not request.cookies.get(DEVICE_COOKIE):
        return redirect_no_device_cookie()
    device = get_registered_device(db, request)
    if not device:
        return RedirectResponse(FALLBACK_URL, status_code=302)
    vehicle_obj = db.scalar(select(Vehicle).where(Vehicle.qr_code_slug == vehicle_slug, Vehicle.active.is_(True)))
    if not vehicle_obj:
        return RedirectResponse(FALLBACK_URL, status_code=302)

    active = get_active_entry(db, device.employee_id)
    if not active:
        return RedirectResponse(
            f"/time?vehicle={vehicle_slug}&error=Aktif mesai bulunamadı.",
            status_code=303,
        )

    end = now_berlin()
    total_minutes = max(0, int((end - as_berlin(active.start_time)).total_seconds() // 60))
    employee = db.scalar(select(Employee).where(Employee.id == device.employee_id))
    hourly_rate = float(employee.hourly_rate or 0) if employee else 0.0
    overtime_multiplier = float(employee.overtime_multiplier or 1.5) if employee else 1.5
    overtime_hourly_rate = (
        float(employee.overtime_hourly_rate)
        if employee and employee.overtime_hourly_rate is not None
        else round(hourly_rate * overtime_multiplier, 2)
    )
    regular_minutes = min(total_minutes, 480)
    overtime_minutes = max(total_minutes - 480, 0)
    regular_cost = round((regular_minutes / 60) * hourly_rate, 2)
    overtime_cost = round((overtime_minutes / 60) * overtime_hourly_rate, 2)
    total_cost = round(regular_cost + overtime_cost, 2)

    active.end_time = end
    active.total_minutes = total_minutes
    active.regular_minutes = regular_minutes
    active.overtime_minutes = overtime_minutes
    active.regular_cost = regular_cost
    active.overtime_cost = overtime_cost
    active.total_cost = total_cost
    active.status = "completed"
    db.commit()

    return RedirectResponse(
        f"/time?vehicle={vehicle_slug}&message=Mesai bitirildi.",
        status_code=303,
    )
