"""Admin forgot / reset password (email link)."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from threading import Lock
from time import monotonic

from fastapi import Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.routing import APIRouter
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..admin_passwords import hash_password
from ..admin_reset_token_crypto import hash_password_reset_token
from ..config import BASE_URL
from ..database import get_db
from ..email_smtp import send_email
from ..models import AdminPasswordResetToken, AdminUser

logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="app/templates")

password_reset_router = APIRouter(tags=["admin-password-reset"])
# Backward-compatible module-level router name for app.main include.
router = password_reset_router

FORGOT_WINDOW_SEC = 15 * 60
FORGOT_MAX_PER_WINDOW = 5
_forgot_lock = Lock()
_forgot_hits: dict[str, list[float]] = defaultdict(list)


def clear_forgot_rate_limit() -> None:
    """Test helper: reset per-IP forgot-password counters."""
    with _forgot_lock:
        _forgot_hits.clear()

RESET_GENERIC_OK = (
    "Bu e-posta adresi sistemde kayıtlıysa, şifre sıfırlama bağlantısı gönderilmiştir. "
    "Gelen kutunuzu ve spam klasörünü kontrol edin."
)


def _client_ip(request: Request) -> str:
    return (request.client.host if request.client else "") or ""


def _forgot_rate_allow(ip: str) -> bool:
    with _forgot_lock:
        now = monotonic()
        hits = _forgot_hits[ip]
        hits[:] = [t for t in hits if now - t < FORGOT_WINDOW_SEC]
        if len(hits) >= FORGOT_MAX_PER_WINDOW:
            return False
        hits.append(now)
        return True


def _invalidate_open_tokens(db: Session, user_id: int) -> None:
    db.execute(
        update(AdminPasswordResetToken)
        .where(AdminPasswordResetToken.user_id == user_id, AdminPasswordResetToken.used.is_(False))
        .values(used=True)
    )


def _find_valid_token_row(db: Session, raw_token: str) -> AdminPasswordResetToken | None:
    if not (raw_token or "").strip():
        return None
    th = hash_password_reset_token(raw_token.strip())
    row = db.scalar(
        select(AdminPasswordResetToken).where(
            AdminPasswordResetToken.token_hash == th,
            AdminPasswordResetToken.used.is_(False),
        )
    )
    if not row:
        return None
    now = datetime.now(timezone.utc)
    exp = row.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if now > exp:
        return None
    return row


@password_reset_router.get("/admin-forgot-password", response_class=HTMLResponse)
def admin_forgot_password_get(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="admin_forgot_password.html",
        context={"request": request, "message": "", "rate_limited": False},
    )


@password_reset_router.post("/admin-forgot-password", response_class=HTMLResponse)
def admin_forgot_password_post(
    request: Request,
    email: str = Form(""),
    db: Session = Depends(get_db),
):
    ip = _client_ip(request)
    if not _forgot_rate_allow(ip):
        logger.info("admin forgot-password rate limited for ip=%s", ip[:16])
        return templates.TemplateResponse(
            request=request,
            name="admin_forgot_password.html",
            context={
                "request": request,
                "message": "Çok fazla istek. Lütfen bir süre sonra tekrar deneyin.",
                "rate_limited": True,
            },
            status_code=429,
        )

    em = (email or "").strip().lower()
    if em:
        user = db.scalar(select(AdminUser).where(AdminUser.email == em, AdminUser.is_active.is_(True)))
        if user:
            _invalidate_open_tokens(db, user.id)
            raw = token_urlsafe(32)
            th = hash_password_reset_token(raw)
            now = datetime.now(timezone.utc)
            row = AdminPasswordResetToken(
                user_id=user.id,
                token_hash=th,
                expires_at=now + timedelta(minutes=30),
                used=False,
                created_at=now,
            )
            db.add(row)
            db.commit()
            link = f"{BASE_URL.rstrip('/')}/admin-reset-password?token={raw}"
            subject = "Cloudia Field OS — Şifre sıfırlama"
            body = (
                "Şifrenizi sıfırlamak için aşağıdaki bağlantıyı kullanın (30 dakika geçerlidir).\n\n"
                f"{link}\n\n"
                "Bu isteği siz yapmadıysanız bu e-postayı yok sayabilirsiniz.\n"
            )
            send_email(user.email, subject, body)
            logger.info("admin password reset email queued/sent for user_id=%s", user.id)

    return templates.TemplateResponse(
        request=request,
        name="admin_forgot_password.html",
        context={"request": request, "message": RESET_GENERIC_OK, "rate_limited": False},
    )


@password_reset_router.get("/admin-reset-password", response_class=HTMLResponse)
def admin_reset_password_get(
    request: Request,
    token: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    raw = (token or "").strip()
    row = _find_valid_token_row(db, raw) if raw else None
    if not row:
        return templates.TemplateResponse(
            request=request,
            name="admin_reset_password_error.html",
            context={"request": request},
            status_code=400,
        )
    return templates.TemplateResponse(
        request=request,
        name="admin_reset_password.html",
        context={"request": request, "token": raw, "error": ""},
    )


@password_reset_router.post("/admin-reset-password", response_class=HTMLResponse)
def admin_reset_password_post(
    request: Request,
    token: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    raw = (token or "").strip()
    row = _find_valid_token_row(db, raw)
    if not row:
        return templates.TemplateResponse(
            request=request,
            name="admin_reset_password_error.html",
            context={"request": request},
            status_code=400,
        )

    user = db.get(AdminUser, row.user_id)
    if not user or not user.is_active:
        return templates.TemplateResponse(
            request=request,
            name="admin_reset_password_error.html",
            context={"request": request},
            status_code=400,
        )

    a = (new_password or "").strip()
    b = (confirm_password or "").strip()
    err: str | None = None
    if len(a) < 8:
        err = "Yeni şifre en az 8 karakter olmalıdır."
    elif a.lower() == (user.email or "").strip().lower():
        err = "Yeni şifre e-posta adresiniz ile aynı olamaz."
    elif a != b:
        err = "Şifreler eşleşmiyor."
    if err:
        return templates.TemplateResponse(
            request=request,
            name="admin_reset_password.html",
            context={"request": request, "token": raw, "error": err},
        )

    user.password_hash = hash_password(a)
    user.force_password_change = False
    row.used = True
    db.commit()
    logger.info("admin password reset completed for user_id=%s", user.id)
    return RedirectResponse(url="/admin/login?reset=success", status_code=303)
