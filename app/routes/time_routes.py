import logging
import re
from collections import defaultdict
from datetime import datetime
from secrets import token_urlsafe
from urllib.parse import quote
from threading import Lock
from time import monotonic
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from ..config import COOKIE_SECURE, TIMEZONE, TIME_FALLBACK_URL
from ..database import get_db
from ..models import Device, Employee, ProvisionalWorker, TimeEntry, Vehicle
from ..models import PW_STATUS_ACTIVE, PW_STATUS_DEACTIVATED, PW_STATUS_PENDING
from ..sqlite_migrations import ensure_provisional_schema, ensure_provisional_worker_phone_extensions
from .admin_time import find_employee_id_with_permanent_primary_digits, normalize_phone_digits

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

BERLIN_TZ = ZoneInfo(TIMEZONE)
DEVICE_COOKIE = "device_token"
FALLBACK_URL = TIME_FALLBACK_URL
logger = logging.getLogger(__name__)

_TIME_QR_REG_WINDOW_SEC = 15 * 60
_TIME_QR_REG_MAX = 12
_time_qr_reg_lock = Lock()
_time_qr_reg_hits: dict[str, list[float]] = defaultdict(list)


def clear_time_qr_register_rate_limit() -> None:
    """Test helper: reset per-IP QR registration counters."""
    with _time_qr_reg_lock:
        _time_qr_reg_hits.clear()


def _client_ip(request: Request) -> str:
    return (request.client.host if request.client else "") or ""


def _time_qr_register_rate_allow(ip: str) -> bool:
    with _time_qr_reg_lock:
        now = monotonic()
        hits = _time_qr_reg_hits[ip]
        hits[:] = [t for t in hits if now - t < _TIME_QR_REG_WINDOW_SEC]
        if len(hits) >= _TIME_QR_REG_MAX:
            return False
        hits.append(now)
        return True


def _name_key(full_name: str) -> str:
    return re.sub(r"\s+", " ", (full_name or "").strip()).lower()


def _find_pending_pw_same_phone_digits(db: Session, digits: str) -> ProvisionalWorker | None:
    if not digits:
        return None
    for pw in db.scalars(select(ProvisionalWorker).where(ProvisionalWorker.status == PW_STATUS_PENDING)):
        if normalize_phone_digits(pw.phone) == digits:
            return pw
    return None


def _find_active_pw_same_phone_digits(db: Session, digits: str) -> ProvisionalWorker | None:
    if not digits:
        return None
    for pw in db.scalars(select(ProvisionalWorker).where(ProvisionalWorker.status == PW_STATUS_ACTIVE)):
        if normalize_phone_digits(pw.phone) == digits:
            return pw
    return None


def _other_provisional_same_name_dob(
    db: Session, *, full_name: str, date_of_birth: str, exclude_id: int | None
) -> bool:
    nk = _name_key(full_name)
    dob = (date_of_birth or "").strip()
    if not nk or not dob:
        return False
    for pw in db.scalars(select(ProvisionalWorker).where(ProvisionalWorker.status != PW_STATUS_DEACTIVATED)):
        if exclude_id is not None and pw.id == exclude_id:
            continue
        if (pw.date_of_birth or "").strip() != dob:
            continue
        if _name_key(pw.full_name) == nk:
            return True
    return False


def _set_device_cookie(response: RedirectResponse, request: Request, raw_token: str) -> None:
    response.set_cookie(
        DEVICE_COOKIE,
        raw_token,
        httponly=True,
        secure=bool(COOKIE_SECURE and request.url.scheme == "https"),
        samesite="lax",
        max_age=31536000,
        path="/",
    )


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


def _normalize_vehicle_slug(raw: str | None) -> str:
    return (raw or "").strip()


def get_valid_vehicle(db: Session, vehicle_slug: str | None):
    clean_slug = _normalize_vehicle_slug(vehicle_slug)
    if not clean_slug:
        return None
    return db.scalar(select(Vehicle).where(Vehicle.qr_code_slug == clean_slug, Vehicle.active.is_(True)))


def _device_identity_valid(device: Device) -> bool:
    e = device.employee_id is not None
    p = device.provisional_worker_id is not None
    return e ^ p


def _vehicle_not_found_response(request: Request, slug: str):
    return templates.TemplateResponse(
        request=request,
        name="time_vehicle_not_found.html",
        context={"request": request, "slug": slug},
        status_code=404,
    )


def _time_qr_register_form(
    request: Request,
    vehicle_obj: Vehicle,
    *,
    error: str = "",
    full_name: str = "",
    phone: str = "",
    date_of_birth: str = "",
    secondary_phone: str = "",
    primary_phone_temporary: bool = False,
    registration_note: str = "",
):
    return templates.TemplateResponse(
        request=request,
        name="time_qr_register.html",
        context={
            "request": request,
            "vehicle": vehicle_obj,
            "form_action": f"/time/{vehicle_obj.qr_code_slug}/register",
            "error": error,
            "full_name": full_name,
            "phone": phone,
            "date_of_birth": date_of_birth,
            "secondary_phone": secondary_phone,
            "primary_phone_temporary": primary_phone_temporary,
            "registration_note": registration_note,
        },
        status_code=200,
    )


def _render_time_screen(
    request: Request,
    db: Session,
    *,
    vehicle_obj: Vehicle,
    device: Device,
):
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


def _serve_time_page_for_slug(request: Request, db: Session, vehicle_slug: str | None):
    """Validate vehicle slug first; unknown slug → 404 (no device cookie required)."""
    slug = _normalize_vehicle_slug(vehicle_slug)
    if not slug:
        if not request.cookies.get(DEVICE_COOKIE):
            return redirect_no_device_cookie()
        device = get_registered_device(db, request)
        if not device or not _device_identity_valid(device):
            return RedirectResponse(FALLBACK_URL, status_code=302)
        return RedirectResponse(FALLBACK_URL, status_code=302)

    vehicle_obj = get_valid_vehicle(db, slug)
    if not vehicle_obj:
        return _vehicle_not_found_response(request, slug)

    if not request.cookies.get(DEVICE_COOKIE):
        return _time_qr_register_form(request, vehicle_obj)
    device = get_registered_device(db, request)
    if not device or not _device_identity_valid(device):
        return _time_qr_register_form(request, vehicle_obj)

    return _render_time_screen(request, db, vehicle_obj=vehicle_obj, device=device)


@router.get("/time", response_class=HTMLResponse)
def time_page(request: Request, vehicle: str | None = None, db: Session = Depends(get_db)):
    return _serve_time_page_for_slug(request, db, vehicle)


@router.get("/time/{vehicle_slug}", response_class=HTMLResponse)
def time_page_by_vehicle_slug(request: Request, vehicle_slug: str, db: Session = Depends(get_db)):
    """Path form: /time/vehicle-01 (same as /time?vehicle=vehicle-01)."""
    return _serve_time_page_for_slug(request, db, vehicle_slug)


def _time_qr_register_post_impl(
    request: Request,
    db: Session,
    vehicle_slug: str,
    full_name: str,
    phone: str,
    date_of_birth: str,
    secondary_phone: str,
    primary_phone_temporary: str,
    registration_note: str,
):
    slug = _normalize_vehicle_slug(vehicle_slug)
    vehicle_obj = get_valid_vehicle(db, slug)
    if not vehicle_obj:
        return _vehicle_not_found_response(request, slug)

    if not _time_qr_register_rate_allow(_client_ip(request)):
        return _time_qr_register_form(
            request,
            vehicle_obj,
            error="Çok fazla deneme. Lütfen bir süre sonra tekrar deneyin.",
            full_name=full_name,
            phone=phone,
            date_of_birth=date_of_birth,
            secondary_phone=secondary_phone,
            primary_phone_temporary=str(primary_phone_temporary).lower() in ("true", "1", "on", "yes"),
            registration_note=registration_note,
        )

    ensure_provisional_schema(db)
    ensure_provisional_worker_phone_extensions(db)

    name = (full_name or "").strip()
    ph = (phone or "").strip()
    sec = (secondary_phone or "").strip() or None
    note = (registration_note or "").strip() or None
    is_temp = str(primary_phone_temporary).lower() in ("1", "true", "yes", "on")
    dob = (date_of_birth or "").strip()

    if not name or not ph or not dob:
        return _time_qr_register_form(
            request,
            vehicle_obj,
            error="Ad soyad, telefon ve doğum tarihi zorunludur.",
            full_name=name,
            phone=ph,
            date_of_birth=dob,
            secondary_phone=(sec or ""),
            primary_phone_temporary=is_temp,
            registration_note=note or "",
        )

    digits = normalize_phone_digits(ph)
    if not is_temp and find_employee_id_with_permanent_primary_digits(db, digits) is not None:
        return _time_qr_register_form(
            request,
            vehicle_obj,
            error="Bu telefon numarası kayıtlı bir çalışana ait görünüyor. Farklı numara kullanın veya birincil telefonu “geçici” olarak işaretleyin.",
            full_name=name,
            phone=ph,
            date_of_birth=dob,
            secondary_phone=(sec or ""),
            primary_phone_temporary=is_temp,
            registration_note=note or "",
        )

    if _find_active_pw_same_phone_digits(db, digits):
        return _time_qr_register_form(
            request,
            vehicle_obj,
            error="Bu telefon numarası ile zaten tanımlı bir ön kayıt var. Aynı cihazınızla giriş yapın veya yöneticinize danışın.",
            full_name=name,
            phone=ph,
            date_of_birth=dob,
            secondary_phone=(sec or ""),
            primary_phone_temporary=is_temp,
            registration_note=note or "",
        )

    pending_existing = _find_pending_pw_same_phone_digits(db, digits)
    if pending_existing:
        pw = pending_existing
        for dev in db.scalars(
            select(Device).where(Device.provisional_worker_id == pw.id, Device.active.is_(True))
        ).all():
            dev.active = False
    else:
        pw = ProvisionalWorker(
            full_name=name,
            phone=ph,
            secondary_phone=sec,
            primary_phone_is_temporary=is_temp,
            date_of_birth=dob,
            device_token=None,
            registration_note=note,
            possible_duplicate_review=False,
            created_at=now_berlin(),
            status=PW_STATUS_PENDING,
        )
        db.add(pw)
        db.flush()

    dup_flag = _other_provisional_same_name_dob(db, full_name=name, date_of_birth=dob, exclude_id=pw.id)
    pw.full_name = name
    pw.phone = ph
    pw.secondary_phone = sec
    pw.primary_phone_is_temporary = is_temp
    pw.date_of_birth = dob
    pw.registration_note = note
    pw.possible_duplicate_review = bool(dup_flag)

    new_token = token_urlsafe(32)
    db.add(
        Device(
            employee_id=None,
            provisional_worker_id=pw.id,
            device_token=new_token,
            created_at=now_berlin(),
            active=True,
        )
    )
    pw.device_token = new_token
    pw.status = PW_STATUS_ACTIVE
    db.commit()

    logger.info("time QR register ok pw_id=%s vehicle=%s", pw.id, vehicle_obj.qr_code_slug)
    resp = RedirectResponse(
        url=f"/time/{vehicle_obj.qr_code_slug}?message={quote('Kayıt tamamlandı')}",
        status_code=303,
    )
    _set_device_cookie(resp, request, new_token)
    return resp


@router.post("/time/register")
def time_qr_register_post_query_vehicle(
    request: Request,
    vehicle_slug: str = Form(...),
    full_name: str = Form(...),
    phone: str = Form(...),
    date_of_birth: str = Form(...),
    secondary_phone: str = Form(""),
    primary_phone_temporary: str = Form(""),
    registration_note: str = Form(""),
    db: Session = Depends(get_db),
):
    """POST /time/register — same as path form; vehicle_slug comes from a hidden field."""
    return _time_qr_register_post_impl(
        request,
        db,
        vehicle_slug,
        full_name,
        phone,
        date_of_birth,
        secondary_phone,
        primary_phone_temporary,
        registration_note,
    )


@router.post("/time/{vehicle_slug}/register")
def time_qr_register_post_path_vehicle(
    request: Request,
    vehicle_slug: str,
    full_name: str = Form(...),
    phone: str = Form(...),
    date_of_birth: str = Form(...),
    secondary_phone: str = Form(""),
    primary_phone_temporary: str = Form(""),
    registration_note: str = Form(""),
    db: Session = Depends(get_db),
):
    return _time_qr_register_post_impl(
        request,
        db,
        vehicle_slug,
        full_name,
        phone,
        date_of_birth,
        secondary_phone,
        primary_phone_temporary,
        registration_note,
    )


@router.post("/time/start")
def start_shift(request: Request, vehicle_slug: str | None = Form(default=None), db: Session = Depends(get_db)):
    if not request.cookies.get(DEVICE_COOKIE):
        return redirect_no_device_cookie()
    device = get_registered_device(db, request)
    if not device or not _device_identity_valid(device):
        return RedirectResponse(FALLBACK_URL, status_code=302)
    slug = _normalize_vehicle_slug(vehicle_slug)
    if not slug:
        return RedirectResponse(FALLBACK_URL, status_code=302)
    vehicle_obj = get_valid_vehicle(db, slug)
    if not vehicle_obj:
        return _vehicle_not_found_response(request, slug)

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
            f"/time?vehicle={vehicle_obj.qr_code_slug}&error=Aktif mesai zaten mevcut.",
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
    slug = _normalize_vehicle_slug(vehicle_slug)
    if not slug:
        return RedirectResponse(FALLBACK_URL, status_code=302)
    vehicle_obj = get_valid_vehicle(db, slug)
    if not vehicle_obj:
        return _vehicle_not_found_response(request, slug)

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
