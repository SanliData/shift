from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text

from .config import TIMEZONE
from .database import Base, SessionLocal, engine
from .models import Employee, Vehicle
from .routes import admin_time, time

app = FastAPI(title="NOVARCHIVE QR Time Demo")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
BERLIN_TZ = ZoneInfo(TIMEZONE)

app.include_router(time.router)
app.include_router(admin_time.router)


def seed_data():
    with SessionLocal() as db:
        # Lightweight migration for old local DBs.
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

        time_entry_cols = db.execute(text("PRAGMA table_info(time_entries)")).fetchall()
        time_entry_col_names = {c[1] for c in time_entry_cols}
        if "regular_minutes" not in time_entry_col_names and time_entry_cols:
            db.execute(text("ALTER TABLE time_entries ADD COLUMN regular_minutes INTEGER"))
            db.commit()
        if "regular_cost" not in time_entry_col_names and time_entry_cols:
            db.execute(text("ALTER TABLE time_entries ADD COLUMN regular_cost FLOAT"))
            db.commit()
        if "overtime_cost" not in time_entry_col_names and time_entry_cols:
            db.execute(text("ALTER TABLE time_entries ADD COLUMN overtime_cost FLOAT"))
            db.commit()
        if "total_cost" not in time_entry_col_names and time_entry_cols:
            db.execute(text("ALTER TABLE time_entries ADD COLUMN total_cost FLOAT"))
            db.commit()
        vehicle_cols = db.execute(text("PRAGMA table_info(vehicles)")).fetchall()
        vehicle_col_names = {c[1] for c in vehicle_cols}
        if "type" not in vehicle_col_names and vehicle_cols:
            db.execute(text("ALTER TABLE vehicles ADD COLUMN type VARCHAR(50)"))
            db.commit()
        if "active" not in vehicle_col_names and vehicle_cols:
            db.execute(text("ALTER TABLE vehicles ADD COLUMN active BOOLEAN DEFAULT 1"))
            db.commit()

        if (db.scalar(select(func.count(Employee.id))) or 0) == 0:
            db.add_all(
                [
                    Employee(
                        name="Mehmet Yilmaz",
                        phone_number="+49 170 0000001",
                        hourly_rate=22.50,
                        overtime_multiplier=1.5,
                        overtime_hourly_rate=33.75,
                        active=True,
                    ),
                    Employee(
                        name="Ali Demir",
                        phone_number="+49 170 0000002",
                        hourly_rate=20.00,
                        overtime_multiplier=1.5,
                        overtime_hourly_rate=30.00,
                        active=True,
                    ),
                ]
            )
        else:
            # Existing demo records: ensure requested phone numbers are present.
            me = db.scalar(select(Employee).where(Employee.name == "Mehmet Yilmaz"))
            ali = db.scalar(select(Employee).where(Employee.name == "Ali Demir"))
            if me and (not me.phone_number or me.phone_number.startswith("+49 151")):
                me.phone_number = "+49 170 0000001"
            if me and not me.hourly_rate:
                me.hourly_rate = 22.50
            if me and not me.overtime_multiplier:
                me.overtime_multiplier = 1.5
            if me and not me.overtime_hourly_rate:
                me.overtime_hourly_rate = round(float(me.hourly_rate or 0) * float(me.overtime_multiplier or 1.5), 2)
            if ali and (not ali.phone_number or ali.phone_number.startswith("+49 151")):
                ali.phone_number = "+49 170 0000002"
            if ali and not ali.hourly_rate:
                ali.hourly_rate = 20.00
            if ali and not ali.overtime_multiplier:
                ali.overtime_multiplier = 1.5
            if ali and not ali.overtime_hourly_rate:
                ali.overtime_hourly_rate = round(float(ali.hourly_rate or 0) * float(ali.overtime_multiplier or 1.5), 2)
        if (db.scalar(select(func.count(Vehicle.id))) or 0) == 0:
            db.add_all(
                [
                    Vehicle(name="Excavator-01", type="excavator", qr_code_slug="vehicle-01", active=True),
                    Vehicle(name="Truck-01", type="truck", qr_code_slug="vehicle-02", active=True),
                ]
            )
        else:
            v1 = db.scalar(select(Vehicle).where(Vehicle.qr_code_slug == "vehicle-01"))
            v2 = db.scalar(select(Vehicle).where(Vehicle.qr_code_slug == "vehicle-02"))
            if v1 and not v1.type:
                v1.type = "excavator"
            if v1 and v1.active is None:
                v1.active = True
            if v2 and not v2.type:
                v2.type = "truck"
            if v2 and v2.active is None:
                v2.active = True
        db.commit()


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    seed_data()


@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"request": request, "now_time": datetime.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M")},
    )


@app.get("/shift", response_class=HTMLResponse)
def shift_root(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"request": request, "now_time": datetime.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M")},
    )


@app.get("/ui/index.html", response_class=HTMLResponse)
def ui_index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="ui_index.html",
        context={"request": request},
    )
