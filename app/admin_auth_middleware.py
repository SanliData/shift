"""Require admin JWT session for /admin-time/*, /admin-change-password, and /admin/* (except login/logout)."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import Request
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from .admin_session_tokens import decode_admin_session_token
from .config import ADMIN_SESSION_COOKIE
from .database import SessionLocal
from .models import AdminUser

CHANGE_PASSWORD_PATH = "/admin-change-password"


def _requires_admin_session(path: str) -> bool:
    if path.startswith("/admin-time"):
        return True
    if path == CHANGE_PASSWORD_PATH:
        return True
    if path.startswith("/admin/"):
        return True
    return False


def _redirect_to_login(request: Request) -> RedirectResponse:
    nxt = request.url.path
    if request.url.query:
        nxt = f"{nxt}?{request.url.query}"
    loc = f"/admin/login?next={quote(nxt, safe='')}"
    return RedirectResponse(url=loc, status_code=302)


class AdminAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request.state.admin_user_id = None
        request.state.admin_email = None
        request.state.admin_role = None
        request.state.admin_force_password_change = False

        path = request.url.path

        if not _requires_admin_session(path):
            return await call_next(request)

        if path.startswith("/admin/login") or path.startswith("/admin/logout"):
            return await call_next(request)

        raw = (request.cookies.get(ADMIN_SESSION_COOKIE) or "").strip()
        payload = decode_admin_session_token(raw) if raw else None
        if not payload:
            return _redirect_to_login(request)

        try:
            uid = int(payload.get("sub") or 0)
        except (TypeError, ValueError):
            return _redirect_to_login(request)

        email_claim = (payload.get("email") or "").strip().lower()
        if not uid or not email_claim:
            return _redirect_to_login(request)

        with SessionLocal() as db:
            user = db.get(AdminUser, uid)
            if (
                not user
                or not user.is_active
                or (user.email or "").strip().lower() != email_claim
            ):
                return _redirect_to_login(request)
            force_pw = bool(user.force_password_change)
            email_db = user.email
            role_db = user.role or "owner"

        request.state.admin_user_id = uid
        request.state.admin_email = email_db
        request.state.admin_role = role_db
        request.state.admin_force_password_change = force_pw

        if force_pw and path != CHANGE_PASSWORD_PATH:
            if path.startswith("/admin-time") or (
                path.startswith("/admin/") and not path.startswith("/admin/login") and not path.startswith("/admin/logout")
            ):
                return RedirectResponse(url=CHANGE_PASSWORD_PATH, status_code=302)

        return await call_next(request)
