import os
from pathlib import Path

# ============================================================
# CLOUDIA FIELD OS — Configuration
# ============================================================


def _read_dotenv_value(key: str) -> str | None:
    env_path = Path(".env")
    if not env_path.exists():
        return None
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    except Exception:
        return None
    return None


def get_setting(key: str, default: str) -> str:
    return os.getenv(key) or _read_dotenv_value(key) or default


def get_bool_setting(key: str, default: bool) -> bool:
    raw = os.getenv(key) or _read_dotenv_value(key)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


# ---- App Identity ----
APP_NAME = "Cloudia Field OS"
APP_SUBTITLE = "QR-Based Workforce, Asset & Cost Tracking Platform"
APP_VERSION = "2.0.0"

# ---- Runtime Settings ----
# BASE_URL should be set via environment variable in production
BASE_URL = get_setting("BASE_URL", "http://127.0.0.1:8002").rstrip("/")
TIMEZONE = get_setting("TIMEZONE", "Europe/Berlin")
ENV = get_setting("ENV", "development").lower()
DATABASE_URL = get_setting("DATABASE_URL", "sqlite:///./data/app.db")

# Fallback: redirect unregistered devices here
TIME_FALLBACK_URL = get_setting("TIME_FALLBACK_URL", "https://www.sanli-netzbau.de/")

COOKIE_SECURE = get_bool_setting("COOKIE_SECURE", ENV == "production")

# HMAC for self-registration confirm links (set in production .env)
REGISTRATION_SIGNING_SECRET = get_setting("REGISTRATION_SIGNING_SECRET", "dev-change-me-not-for-production")

# Admin UI (JWT cookie session; bcrypt passwords in admin_users)
ADMIN_SESSION_SECRET = get_setting("ADMIN_SESSION_SECRET", "dev-admin-session-secret-change-in-production")
ADMIN_SESSION_COOKIE = "admin_session"

# Tüm ön tanımlı yöneticiler için ortak geçici şifre (ilk girişte değiştirilir). Üretimde .env ile değiştirin.
ADMIN_BOOTSTRAP_TEMP_PASSWORD = get_setting("ADMIN_BOOTSTRAP_TEMP_PASSWORD", "Damlacik242-28")

# ---- Multi-tenant readiness ----
# TODO (v3): Add company_id to all models for multi-tenant SaaS
# COMPANY_ID = get_setting("COMPANY_ID", "default")
