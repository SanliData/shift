from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text

from .config import APP_NAME, TIMEZONE
from .database import Base, SessionLocal, engine
from .models import Employee, TimeEntry, Vehicle
from .routes import admin_time, time_routes

app = FastAPI(title=APP_NAME, version="2.0.0")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
BERLIN_TZ = ZoneInfo(TIMEZONE)

app.include_router(time_routes.router)
app.include_router(admin_time.router)


def seed_data():
    with SessionLocal() as db:
        cols = db.execute(text("PRAGMA table_info(employees)")).fetchall()
        col_names = {c[1] for c in cols}
        if "phone_number" not in col_names and cols:
            db.execute(text("ALTER TABLE employees ADD COLUMN phone_number VARCHAR(40)"))
            db.commit()
        if "hourly_rate" not in col_names and cols:
            db.execute(text("ALTER TABLE employees ADD COLUMN hourly_rate FLOAT DEFAULT 0"))
            db.commit()
        if "overtime_multiplier" not in col_names and cols:
            db.execute(text("ALTER TABLE employees ADD COLUMN overtime_multiplier FLOAT DEFAULT 1.5"))
            db.commit()
        if "overtime_hourly_rate" not in col_names and cols:
            db.execute(text("ALTER TABLE employees ADD COLUMN overtime_hourly_rate FLOAT"))
            db.commit()
        te_cols = db.execute(text("PRAGMA table_info(time_entries)")).fetchall()
        te_col_names = {c[1] for c in te_cols}
        for col in ("regular_minutes", "regular_cost", "overtime_cost", "total_cost"):
            if col not in te_col_names and te_cols:
                db.execute(text(f"ALTER TABLE time_entries ADD COLUMN {col} FLOAT"))
                db.commit()
        v_cols = db.execute(text("PRAGMA table_info(vehicles)")).fetchall()
        v_col_names = {c[1] for c in v_cols}
        if "type" not in v_col_names and v_cols:
            db.execute(text("ALTER TABLE vehicles ADD COLUMN type VARCHAR(50)"))
            db.commit()
        if "active" not in v_col_names and v_cols:
            db.execute(text("ALTER TABLE vehicles ADD COLUMN active BOOLEAN DEFAULT 1"))
            db.commit()
        rt_cols = db.execute(text("PRAGMA table_info(registration_tokens)")).fetchall()
        rt_col_names = {c[1] for c in rt_cols}
        if rt_cols and "active" not in rt_col_names:
            db.execute(text("ALTER TABLE registration_tokens ADD COLUMN active BOOLEAN DEFAULT 1"))
            db.commit()
        if rt_cols and "last_sent_at" not in rt_col_names:
            db.execute(text("ALTER TABLE registration_tokens ADD COLUMN last_sent_at DATETIME"))
            db.commit()
        if rt_cols:
            db.execute(text("UPDATE registration_tokens SET used = 0 WHERE used IS NULL"))
            db.execute(text("UPDATE registration_tokens SET active = 1 WHERE active IS NULL"))
            db.execute(text("UPDATE registration_tokens SET active = 0 WHERE used = 1"))
            employee_ids = db.execute(text("SELECT DISTINCT employee_id FROM registration_tokens")).fetchall()
            for row in employee_ids:
                eid = int(row[0])
                valid_rows = db.execute(
                    text("SELECT id FROM registration_tokens WHERE employee_id = :eid AND active = 1 AND used = 0 ORDER BY created_at DESC, id DESC"),
                    {"eid": eid},
                ).fetchall()
                for old in valid_rows[1:]:
                    db.execute(text("UPDATE registration_tokens SET active = 0 WHERE id = :id"), {"id": int(old[0])})
            db.commit()
        if (db.scalar(select(func.count(Employee.id))) or 0) == 0:
            db.add_all([
                Employee(name="Mehmet Yilmaz", phone_number="+49 170 0000001", hourly_rate=22.50, overtime_multiplier=1.5, overtime_hourly_rate=33.75, active=True),
                Employee(name="Ali Demir", phone_number="+49 170 0000002", hourly_rate=20.00, overtime_multiplier=1.5, overtime_hourly_rate=30.00, active=True),
            ])
        if (db.scalar(select(func.count(Vehicle.id))) or 0) == 0:
            db.add_all([
                Vehicle(name="Excavator-01", type="excavator", qr_code_slug="vehicle-01", active=True),
                Vehicle(name="Truck-01", type="truck", qr_code_slug="vehicle-02", active=True),
            ])
        db.commit()


def as_berlin(dt):
    if dt.tzinfo is None:
        return dt.replace(tzinfo=BERLIN_TZ)
    return dt.astimezone(BERLIN_TZ)


def eur(v):
    return f"\u20ac{float(v or 0):,.2f}"


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    seed_data()


@app.get("/")
def root_redirect():
    return RedirectResponse(url="/dashboard")


@app.get("/shift")
def shift_redirect():
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    from datetime import timedelta
    with SessionLocal() as db:
        now = datetime.now(BERLIN_TZ)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=today_start.weekday())
        month_start = today_start.replace(day=1)
        all_completed = db.scalars(select(TimeEntry).where(TimeEntry.status == "completed")).all()
        active_entries = db.scalars(select(TimeEntry).where(TimeEntry.status == "active")).all()
        completed_entries = db.scalars(select(TimeEntry).where(TimeEntry.status == "completed").order_by(TimeEntry.end_time.desc()).limit(10)).all()
        today_m = week_m = month_m = 0
        today_c = week_c = month_c = month_ot_c = 0.0
        for e in all_completed:
            if not e.start_time:
                continue
            ls = as_berlin(e.start_time)
            m = int(e.total_minutes or 0)
            c = float(e.total_cost or 0)
            oc = float(e.overtime_cost or 0)
            if ls >= today_start:
                today_m += m; today_c += c
            if ls >= week_start:
                week_m += m; week_c += c
            if ls >= month_start:
                month_m += m; month_c += c; month_ot_c += oc

    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={
            "request": request,
            "berlin_now": now.strftime("%d.%m.%Y %H:%M:%S"),
            "now_berlin_ts": now.timestamp(),
            "today_hours": round(today_m / 60, 1),
            "week_hours": round(week_m / 60, 1),
            "month_hours": round(month_m / 60, 1),
            "active_shift_count": len(active_entries),
            "today_cost_eur": eur(today_c),
            "week_cost_eur": eur(week_c),
            "month_cost_eur": eur(month_c),
            "month_overtime_cost_eur": eur(month_ot_c),
            "active_entries": active_entries,
            "completed_entries": completed_entries,
            "missing_rate_employees": [],
            "message": "",
        },
    )


@app.get("/ui/index.html")
def ui_index_redirect():
    from .config import TIME_FALLBACK_URL
    return RedirectResponse(url=TIME_FALLBACK_URL)
