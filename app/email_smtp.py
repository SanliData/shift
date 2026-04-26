"""SMTP email sending (admin password reset, etc.)."""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from threading import Lock

from .config import get_setting

logger = logging.getLogger(__name__)

_TEST_OUTBOX: list[dict[str, str]] = []
_TEST_LOCK = Lock()

SMTP_TEST_HOST = "__test__"


def clear_test_outbox() -> None:
    with _TEST_LOCK:
        _TEST_OUTBOX.clear()


def get_test_outbox() -> list[dict[str, str]]:
    with _TEST_LOCK:
        return list(_TEST_OUTBOX)


def send_email(to: str, subject: str, body: str) -> bool:
    """
    Send a plain-text email. Returns True if handed off / test-captured successfully.
    When SMTP_HOST is unset, logs and returns False (caller may still treat forgot flow as OK).
    """
    to_addr = (to or "").strip()
    if not to_addr:
        return False

    host = (get_setting("SMTP_HOST", "") or "").strip()
    if host == SMTP_TEST_HOST:
        with _TEST_LOCK:
            _TEST_OUTBOX.append({"to": to_addr, "subject": subject, "body": body})
        return True

    if not host:
        logger.warning("SMTP_HOST not configured; email to %s not sent", to_addr[:3] + "…")
        return False

    port = int(get_setting("SMTP_PORT", "587") or "587")
    user = (get_setting("SMTP_USER", "") or "").strip()
    password = get_setting("SMTP_PASS", "") or ""
    from_addr = (get_setting("SMTP_FROM", "") or user or "").strip()
    if not from_addr:
        logger.error("SMTP_FROM / SMTP_USER missing; cannot send")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body)

    try:
        if port == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as smtp:
                if user:
                    smtp.login(user, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.ehlo()
                try:
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()
                except smtplib.SMTPException:
                    pass
                if user:
                    smtp.login(user, password)
                smtp.send_message(msg)
    except Exception:
        logger.exception("SMTP send failed for to=%s", to_addr[:3] + "…")
        return False

    return True
