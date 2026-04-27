"""SQLite-only schema adjustments (legacy DBs). Kept separate to avoid import cycles."""

import secrets
from datetime import datetime, timezone

from sqlalchemy import text


def _pragma_col_notnull(cols: list, name: str) -> bool:
    for c in cols:
        if c[1] == name:
            return bool(c[3])
    return False


def ensure_provisional_schema(db) -> None:
    """provisional_workers table + nullable employee_id on devices/time_entries."""
    has_pw = db.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='provisional_workers' LIMIT 1")
    ).fetchone()
    if not has_pw:
        db.execute(
            text(
                """
                CREATE TABLE provisional_workers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name VARCHAR(200) NOT NULL,
                    phone VARCHAR(60) NOT NULL,
                    date_of_birth VARCHAR(32),
                    device_token VARCHAR(255),
                    created_at DATETIME NOT NULL,
                    status VARCHAR(40) NOT NULL
                )
                """
            )
        )
        db.commit()

    dcols = db.execute(text("PRAGMA table_info(devices)")).fetchall()
    if dcols:
        dnames = {c[1] for c in dcols}
        if "provisional_worker_id" not in dnames:
            db.execute(text("ALTER TABLE devices ADD COLUMN provisional_worker_id INTEGER"))
            db.commit()
            dcols = db.execute(text("PRAGMA table_info(devices)")).fetchall()
        if _pragma_col_notnull(dcols, "employee_id"):
            db.execute(text("PRAGMA foreign_keys=OFF"))
            db.execute(
                text(
                    """
                    CREATE TABLE _devices_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        employee_id INTEGER,
                        provisional_worker_id INTEGER,
                        device_token VARCHAR(255) NOT NULL UNIQUE,
                        created_at DATETIME NOT NULL,
                        active BOOLEAN NOT NULL
                    )
                    """
                )
            )
            db.execute(
                text(
                    """
                    INSERT INTO _devices_new (id, employee_id, provisional_worker_id, device_token, created_at, active)
                    SELECT id, employee_id, provisional_worker_id, device_token, created_at, active FROM devices
                    """
                )
            )
            db.execute(text("DROP TABLE devices"))
            db.execute(text("ALTER TABLE _devices_new RENAME TO devices"))
            db.execute(text("PRAGMA foreign_keys=ON"))
            db.commit()

    tcols = db.execute(text("PRAGMA table_info(time_entries)")).fetchall()
    if tcols:
        tnames = {c[1] for c in tcols}
        if "provisional_worker_id" not in tnames:
            db.execute(text("ALTER TABLE time_entries ADD COLUMN provisional_worker_id INTEGER"))
            db.commit()
            tcols = db.execute(text("PRAGMA table_info(time_entries)")).fetchall()
        if _pragma_col_notnull(tcols, "employee_id"):
            db.execute(text("PRAGMA foreign_keys=OFF"))
            db.execute(
                text(
                    """
                    CREATE TABLE _te_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        employee_id INTEGER,
                        provisional_worker_id INTEGER,
                        employee_name VARCHAR(120) NOT NULL,
                        device_id INTEGER NOT NULL,
                        vehicle_id INTEGER NOT NULL,
                        start_time DATETIME NOT NULL,
                        end_time DATETIME,
                        total_minutes INTEGER,
                        regular_minutes INTEGER,
                        overtime_minutes INTEGER,
                        regular_cost FLOAT,
                        overtime_cost FLOAT,
                        total_cost FLOAT,
                        status VARCHAR(30) NOT NULL
                    )
                    """
                )
            )
            db.execute(
                text(
                    """
                    INSERT INTO _te_new (
                        id, employee_id, provisional_worker_id, employee_name, device_id, vehicle_id,
                        start_time, end_time, total_minutes, regular_minutes, overtime_minutes,
                        regular_cost, overtime_cost, total_cost, status
                    )
                    SELECT
                        id, employee_id, provisional_worker_id, employee_name, device_id, vehicle_id,
                        start_time, end_time, total_minutes, regular_minutes, overtime_minutes,
                        regular_cost, overtime_cost, total_cost, status
                    FROM time_entries
                    """
                )
            )
            db.execute(text("DROP TABLE time_entries"))
            db.execute(text("ALTER TABLE _te_new RENAME TO time_entries"))
            db.execute(text("PRAGMA foreign_keys=ON"))
            db.commit()


def ensure_reporting_schema(db) -> None:
    """Employees DOB + time_entry_corrections audit table."""
    ecols = db.execute(text("PRAGMA table_info(employees)")).fetchall()
    if ecols and "date_of_birth" not in {c[1] for c in ecols}:
        db.execute(text("ALTER TABLE employees ADD COLUMN date_of_birth VARCHAR(32)"))
        db.commit()
    has_tc = db.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='time_entry_corrections' LIMIT 1")
    ).fetchone()
    if not has_tc:
        db.execute(
            text(
                """
                CREATE TABLE time_entry_corrections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    time_entry_id INTEGER NOT NULL,
                    old_clock_in DATETIME,
                    old_clock_out DATETIME,
                    new_clock_in DATETIME,
                    new_clock_out DATETIME,
                    old_employee_id INTEGER,
                    new_employee_id INTEGER,
                    old_vehicle_id INTEGER,
                    new_vehicle_id INTEGER,
                    reason VARCHAR(1000),
                    created_at DATETIME NOT NULL,
                    corrected_by VARCHAR(120) DEFAULT 'admin',
                    corrected_by_role VARCHAR(60) DEFAULT 'admin',
                    corrected_by_ip VARCHAR(64),
                    corrected_by_user_agent TEXT
                )
                """
            )
        )
        db.commit()
    tccols = db.execute(text("PRAGMA table_info(time_entry_corrections)")).fetchall()
    if tccols:
        tcnames = {c[1] for c in tccols}
        alters: list[tuple[str, str]] = [
            ("corrected_by", "VARCHAR(120) DEFAULT 'admin'"),
            ("corrected_by_role", "VARCHAR(60) DEFAULT 'admin'"),
            ("corrected_by_ip", "VARCHAR(64)"),
            ("corrected_by_user_agent", "TEXT"),
        ]
        for col, typ in alters:
            if col not in tcnames:
                db.execute(text(f"ALTER TABLE time_entry_corrections ADD COLUMN {col} {typ}"))
                db.commit()
                tcnames.add(col)
        db.execute(
            text(
                "UPDATE time_entry_corrections SET corrected_by = 'admin' "
                "WHERE corrected_by IS NULL OR corrected_by = ''"
            )
        )
        db.execute(
            text(
                "UPDATE time_entry_corrections SET corrected_by_role = 'admin' "
                "WHERE corrected_by_role IS NULL OR corrected_by_role = ''"
            )
        )
        db.commit()


def ensure_provisional_vehicle_schema(db) -> None:
    """Self-service vehicle registration queue (provisional_vehicles)."""
    has_pv = db.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='provisional_vehicles' LIMIT 1")
    ).fetchone()
    if not has_pv:
        db.execute(
            text(
                """
                CREATE TABLE provisional_vehicles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(120) NOT NULL,
                    type VARCHAR(50),
                    notes TEXT,
                    qr_slug_hint VARCHAR(120),
                    created_at DATETIME NOT NULL,
                    status VARCHAR(40) NOT NULL,
                    vehicle_id INTEGER REFERENCES vehicles(id)
                )
                """
            )
        )
        db.commit()


def ensure_worker_registration_tokens_schema(db) -> None:
    has_t = db.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='worker_registration_tokens' LIMIT 1")
    ).fetchone()
    if not has_t:
        db.execute(
            text(
                """
                CREATE TABLE worker_registration_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token VARCHAR(255) NOT NULL UNIQUE,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        db.commit()
    active = db.execute(text("SELECT 1 FROM worker_registration_tokens WHERE is_active = 1 LIMIT 1")).fetchone()
    if not active:
        tok = secrets.token_urlsafe(24)
        created = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        db.execute(
            text(
                "INSERT INTO worker_registration_tokens (token, is_active, created_at) VALUES (:tok, 1, :created)"
            ),
            {"tok": tok, "created": created},
        )
        db.commit()


def ensure_employee_phones_schema(db) -> None:
    has_ep = db.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='employee_phones' LIMIT 1")
    ).fetchone()
    if not has_ep:
        db.execute(
            text(
                """
                CREATE TABLE employee_phones (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id INTEGER NOT NULL REFERENCES employees(id),
                    phone VARCHAR(60) NOT NULL,
                    is_primary BOOLEAN NOT NULL DEFAULT 0,
                    is_temporary BOOLEAN NOT NULL DEFAULT 0
                )
                """
            )
        )
        db.commit()
    rows = db.execute(
        text(
            """
            SELECT e.id, e.phone_number FROM employees e
            WHERE e.phone_number IS NOT NULL AND TRIM(e.phone_number) != ''
            AND NOT EXISTS (SELECT 1 FROM employee_phones ep WHERE ep.employee_id = e.id)
            """
        )
    ).fetchall()
    for eid, pnum in rows:
        db.execute(
            text(
                "INSERT INTO employee_phones (employee_id, phone, is_primary, is_temporary) "
                "VALUES (:eid, :ph, 1, 0)"
            ),
            {"eid": int(eid), "ph": str(pnum).strip()[:60]},
        )
    if rows:
        db.commit()


def ensure_provisional_worker_phone_extensions(db) -> None:
    cols = db.execute(text("PRAGMA table_info(provisional_workers)")).fetchall()
    if not cols:
        return
    names = {c[1] for c in cols}
    if "secondary_phone" not in names:
        db.execute(text("ALTER TABLE provisional_workers ADD COLUMN secondary_phone VARCHAR(60)"))
        db.commit()
    if "primary_phone_is_temporary" not in names:
        db.execute(text("ALTER TABLE provisional_workers ADD COLUMN primary_phone_is_temporary BOOLEAN DEFAULT 0"))
        db.commit()
    if "registration_note" not in names:
        db.execute(text("ALTER TABLE provisional_workers ADD COLUMN registration_note VARCHAR(500)"))
        db.commit()
    if "possible_duplicate_review" not in names:
        db.execute(
            text("ALTER TABLE provisional_workers ADD COLUMN possible_duplicate_review BOOLEAN NOT NULL DEFAULT 0")
        )
        db.commit()


def ensure_admin_users_schema(db) -> None:
    """admin_users for FastAPI admin login (idempotent)."""
    has_t = db.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='admin_users' LIMIT 1")
    ).fetchone()
    if not has_t:
        db.execute(
            text(
                """
                CREATE TABLE admin_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email VARCHAR(255) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    role VARCHAR(32) NOT NULL DEFAULT 'owner',
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    force_password_change BOOLEAN NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        db.commit()
        return
    names = {c[1] for c in db.execute(text("PRAGMA table_info(admin_users)")).fetchall()}
    if "force_password_change" not in names:
        db.execute(text("ALTER TABLE admin_users ADD COLUMN force_password_change BOOLEAN NOT NULL DEFAULT 0"))
        db.commit()


def ensure_password_reset_tokens_schema(db) -> None:
    has_t = db.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='password_reset_tokens' LIMIT 1")
    ).fetchone()
    if not has_t:
        db.execute(
            text(
                """
                CREATE TABLE password_reset_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES admin_users(id),
                    token_hash VARCHAR(128) NOT NULL,
                    expires_at DATETIME NOT NULL,
                    used BOOLEAN NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        db.execute(text("CREATE INDEX ix_password_reset_tokens_token_hash ON password_reset_tokens (token_hash)"))
        db.commit()
