import os
from pathlib import Path


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


BASE_URL = get_setting("BASE_URL", "http://127.0.0.1:8002").rstrip("/")
TIMEZONE = get_setting("TIMEZONE", "Europe/Berlin")
ENV = get_setting("ENV", "development").lower()
DATABASE_URL = get_setting("DATABASE_URL", "sqlite:///./data/app.db")
TIME_FALLBACK_URL = BASE_URL if ENV == "production" else "/ui/index.html"
COOKIE_SECURE = get_bool_setting("COOKIE_SECURE", ENV == "production")
