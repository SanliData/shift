import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from ..config import TIMEZONE, TIME_FALLBACK_URL
from ..database import get_db
from ..models import Device, Employee, ProvisionalWorker, TimeEntry, Vehicle
from ..models import PW_STATUS_ACTIVE

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
        select(Device)
        .options(selectinload(Device.employee), selectinload(Device.provisional_worker))
        .where(Device.device_token == token, Device.active.is_(True))
    )


def get_active_entry_for_device(db: Session, device: Device) -> TimeEntry | None:
    if device.employee_id is not None:
        return db.scalar(
            select(TimeEntry)
            .where(TimeEntry.employee_id == device.employee_id, TimeEntry.status == "active")
            .order_by(desc(TimeEntry.start_time))
        )
    if device.provisional_worker_id is not None:
        return db.scalar(
            select(TimeEntry)
            .where(
                TimeEntry.provisional_worker_id == device.provisional_worker_id,
                TimeEntry.status == "active",
            )
            .order_by(desc(TimeEntry.start_time))
        )
    return None


def redirect_no_device_cookie():
    logger.debug("device_token cookie missing")
    return RedirectResponse(FALLBACK_URL, status_code=302)


def get_valid_vehicle(db: Session, vehicle_slug: str | None):
    clean_slug = (vehicle_slug or "").strip()
    if not clean_slug:
        return None
    return db.scalar(select(Vehicle).where(Vehicle.qr_code_slug == clean_slug, Vehicle.active.is_(True)))


def _device_identity_valid(device: Device) -> bool:
    e = device.employee_id is not None
    p = device.provisional_worker_id is not None
    return e ^ p


@router.get("/time", response_class=HTMLResponse)
def time_page(request: Request, vehicle: str | None = None, db: Session = Depends(get_db)):
    if not request.cookies.get(DEVICE_COOKIE):
        return redirect_no_device_cookie()
    device = get_registered_device(db, request)
    if not device or not _device_identity_valid(device):
        return RedirectResponse(FALLBACK_URL, status_code=302)

    vehicle_obj = get_valid_vehicle(db, vehicle)
    if not vehicle_obj:
        return RedirectResponse(FALLBACK_URL, status_code=302)

    is_provisional = device.provisional_worker_id is not None
    employee = device.employee
    provisional = device.provisional_worker if is_provisional else None

    if is_provisional:
        if not provisional or provisional.status != PW_STATUS_ACTIVE:
            return RedirectResponse(FALLBACK_URL, status_code=302)
        worker_name = provisional.full_name
        worker_phone = provisional.phone or "—"
        employee_can_start = True
    else:
        if not employee:
            return RedirectResponse(FALLBACK_URL, status_code=302)
        worker_name = employee.name
        worker_phone = employee.phone_number or "—"
        employee_can_start = bool(employee.active)

    active_entry = get_active_entry_for_device(db, device)
    return templates.TemplateResponse(
        request=request,
        name="time.html",
        context={
            "request": request,
            "employee": employee,
            "is_provisional": is_provisional,
            "worker_name": worker_name,
            "worker_phone": worker_phone,
            "employee_can_start": employee_can_start,
            "vehicle": vehicle_obj,
            "active_entry": active_entry,
            "message": request.query_params.get("message", ""),
            "error": request.query_params.get("error", ""),
        },
    )


@router.post("/time/start")
def start_shift(request: Request, vehicle_slug: str | None = Form(default=None), db: Session = Depends(get_db)):
    if not request.cookies.get(DEVICE_COOKIE):
        return redirect_no_device_cookie()
    device = get_registered_device(db, request)
    if not device or not _device_identity_valid(device):
        return RedirectResponse(FALLBACK_URL, status_code=302)
    vehicle_obj = get_valid_vehicle(db, vehicle_slug)
    if not vehicle_obj:
        return RedirectResponse(FALLBACK_URL, status_code=302)

    is_provisional = device.provisional_worker_id is not None
    if is_provisional:
        pw = device.provisional_worker
        if not pw or pw.status != PW_STATUS_ACTIVE:
            return RedirectResponse(FALLBACK_URL, status_code=303)
        employee_name = pw.full_name
        employee_id = None
        provisional_worker_id = pw.id
    else:
        emp = device.employee
        if not emp or not emp.active:
            return RedirectResponse(FALLBACK_URL, status_code=303)
        employee_name = emp.name
        employee_id = device.employee_id
        provisional_worker_id = None

    if get_active_entry_for_device(db, device):
        return RedirectResponse(
            f"/time?vehicle={vehicle_slug}&error=Aktif mesai zaten mevcut.",
            status_code=303,
        )

    db.add(
        TimeEntry(
            employee_id=employee_id,
            provisional_worker_id=provisional_worker_id,
            employee_name=employee_name,
            device_id=device.id,
            vehicle_id=vehicle_obj.id,
            start_time=now_berlin(),
            status="active",
        )
    )
    db.commit()
    return RedirectResponse(
        f"/time?vehicle={vehicle_obj.qr_code_slug}&message=Mesai başlatıldı.",
        status_code=303,
    )


@router.post("/time/stop")
def stop_shift(request: Request, vehicle_slug: str | None = Form(default=None), db: Session = Depends(get_db)):
    if not request.cookies.get(DEVICE_COOKIE):
        return redirect_no_device_cookie()
    device = get_registered_device(db, request)
    if not device or not _device_identity_valid(device):
        return RedirectResponse(FALLBACK_URL, status_code=302)
    vehicle_obj = get_valid_vehicle(db, vehicle_slug)
    if not vehicle_obj:
        return RedirectResponse(FALLBACK_URL, status_code=302)

    is_provisional = device.provisional_worker_id is not None
    if is_provisional:
        pw = device.provisional_worker
        if not pw or pw.status != PW_STATUS_ACTIVE:
            return RedirectResponse(FALLBACK_URL, status_code=303)
        hourly_rate = 0.0
        overtime_multiplier = 1.5
        overtime_hourly_rate = 0.0
    else:
        employee = device.employee
        if not employee or not employee.active:
            return RedirectResponse(FALLBACK_URL, status_code=303)
        hourly_rate = float(employee.hourly_rate or 0)
        overtime_multiplier = float(employee.overtime_multiplier or 1.5)
        overtime_hourly_rate = (
            float(employee.overtime_hourly_rate)
            if employee.overtime_hourly_rate is not None
            else round(hourly_rate * overtime_multiplier, 2)
        )

    active = get_active_entry_for_device(db, device)
    if not active:
        return RedirectResponse(
            f"/time?vehicle={vehicle_obj.qr_code_slug}&error=Aktif mesai bulunamadı.",
            status_code=303,
        )

    end = now_berlin()
    total_minutes = max(0, int((end - as_berlin(active.start_time)).total_seconds() // 60))
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
        f"/time?vehicle={vehicle_obj.qr_code_slug}&message=Mesai bitirildi.",
        status_code=303,
    )
