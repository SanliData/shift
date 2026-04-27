"""Admin login, logout, and forced password change."""

from __future__ import annotations

import logging
import re
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..admin_passwords import hash_password, verify_password
from ..admin_session_tokens import issue_admin_session_token
from ..config import ADMIN_SESSION_COOKIE, COOKIE_SECURE
from ..database import get_db
from ..models import AdminUser

router = APIRouter(prefix="/admin", tags=["admin-auth"])
change_password_router = APIRouter(tags=["admin-change-password"])
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)

_NEXT_UNSAFE = re.compile(r"^(https?:)?//", re.I)


def _safe_next(raw: str | None) -> str:
    if not raw:
        return "/admin-time/reports"
    s = unquote((raw or "").strip())
    if not s.startswith("/") or _NEXT_UNSAFE.match(s):
        return "/admin-time/reports"
    return s.split("\n")[0][:2048] or "/admin-time/reports"


def _set_session_cookie(response: RedirectResponse, request: Request, user: AdminUser) -> None:
    token = issue_admin_session_token(user_id=user.id, email=user.email, role=user.role or "owner")
    response.set_cookie(
        ADMIN_SESSION_COOKIE,
        token,
        httponly=True,
        secure=bool(COOKIE_SECURE and request.url.scheme == "https"),
        samesite="lax",
        max_age=14 * 24 * 3600,
        path="/",
    )


def _clear_session_cookie(response: RedirectResponse, request: Request) -> None:
    response.delete_cookie(ADMIN_SESSION_COOKIE, path="/")


@router.get("/login", response_class=HTMLResponse)
def admin_login_get(
    request: Request,
    next: str | None = Query(default=None),
    error: str | None = Query(default=None),
    reset: str | None = Query(default=None),
):
    reset_ok = (reset or "").strip().lower() == "success"
    return templates.TemplateResponse(
        request=request,
        name="admin_login.html",
        context={
            "request": request,
            "next_url": _safe_next(next),
            "error": (error or "").strip(),
            "reset_success": reset_ok,
        },
    )


@router.get("-login", response_class=HTMLResponse)
def admin_login_get_legacy(
    request: Request,
    next: str | None = Query(default=None),
    error: str | None = Query(default=None),
    reset: str | None = Query(default=None),
):
    return admin_login_get(request=request, next=next, error=error, reset=reset)


@router.post("/login", response_class=HTMLResponse)
def admin_login_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form(""),
    db: Session = Depends(get_db),
):
    em = (email or "").strip().lower()
    pw = password or ""
    if not em or not pw:
        return templates.TemplateResponse(
            request=request,
            name="admin_login.html",
            context={
                "request": request,
                "next_url": _safe_next(next),
                "error": "E-posta ve şifre zorunludur.",
                "email_value": (email or "").strip(),
            },
        )
    user = db.scalar(select(AdminUser).where(AdminUser.email == em))
    if not user or not user.is_active or not verify_password(pw, user.password_hash):
        logger.info("admin login failed for %s", em)
        return templates.TemplateResponse(
            request=request,
            name="admin_login.html",
            context={
                "request": request,
                "next_url": _safe_next(next),
                "error": "E-posta veya şifre hatalı.",
                "email_value": (email or "").strip(),
            },
        )
    dest = "/admin-change-password" if user.force_password_change else _safe_next(next)
    resp = RedirectResponse(url=dest, status_code=303)
    _set_session_cookie(resp, request, user)
    logger.info("admin login ok %s", em)
    return resp


@router.post("-login", response_class=HTMLResponse)
def admin_login_post_legacy(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form(""),
    db: Session = Depends(get_db),
):
    return admin_login_post(request=request, email=email, password=password, next=next, db=db)


@router.get("/logout", response_class=HTMLResponse)
@router.post("/logout", response_class=HTMLResponse)
def admin_logout(request: Request):
    resp = RedirectResponse(url="/admin/login", status_code=303)
    _clear_session_cookie(resp, request)
    return resp


@change_password_router.get("/admin-change-password", response_class=HTMLResponse)
def admin_change_password_get(request: Request):
    if not getattr(request.state, "admin_force_password_change", False):
        return RedirectResponse(url="/admin-time/reports", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="admin_change_password.html",
        context={"request": request, "error": ""},
    )


@change_password_router.post("/admin-change-password", response_class=HTMLResponse)
def admin_change_password_post(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    new_password_confirm: str = Form(...),
    db: Session = Depends(get_db),
):
    uid = getattr(request.state, "admin_user_id", None)
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.get(AdminUser, uid)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not user.force_password_change:
        return RedirectResponse(url="/admin-time/reports", status_code=303)

    cur = (current_password or "").strip()
    a = (new_password or "").strip()
    b = (new_password_confirm or "").strip()
    err: str | None = None
    if not cur:
        err = "Mevcut şifre zorunludur."
    elif not verify_password(cur, user.password_hash):
        err = "Mevcut şifre hatalı."
    elif not a:
        err = "Yeni şifre boş olamaz."
    elif len(a) < 8:
        err = "Yeni şifre en az 8 karakter olmalıdır."
    elif a.lower() == (user.email or "").strip().lower():
        err = "Yeni şifre e-posta adresiniz ile aynı olamaz."
    elif a != b:
        err = "Yeni şifreler eşleşmiyor."
    if err:
        return templates.TemplateResponse(
            request=request,
            name="admin_change_password.html",
            context={"request": request, "error": err},
        )

    user.password_hash = hash_password(a)
    user.force_password_change = False
    db.commit()
    resp = RedirectResponse(url="/admin-time/reports", status_code=303)
    _set_session_cookie(resp, request, user)
    logger.info("admin password changed for %s", user.email)
    return resp
