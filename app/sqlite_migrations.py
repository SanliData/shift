"""SQLite-only schema adjustments (legacy DBs). Kept separate to avoid import cycles."""

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
