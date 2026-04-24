from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from .database import Base, SessionLocal, engine
from .models import Employee, Vehicle
from .routes import admin_time, time

app = FastAPI(title="NOVARCHIVE QR Time Demo")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
BERLIN_TZ = ZoneInfo("Europe/Berlin")

app.include_router(time.router)
app.include_router(admin_time.router)


def seed_data():
    with SessionLocal() as db:
        if (db.scalar(select(func.count(Employee.id))) or 0) == 0:
            db.add_all(
                [
                    Employee(name="Mehmet Yilmaz", active=True),
                    Employee(name="Ali Demir", active=True),
                ]
            )
        if (db.scalar(select(func.count(Vehicle.id))) or 0) == 0:
            db.add_all(
                [
                    Vehicle(name="vehicle-01", qr_code_slug="vehicle-01"),
                    Vehicle(name="vehicle-02", qr_code_slug="vehicle-02"),
                ]
            )
        db.commit()


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    seed_data()


@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    return templates.TemplateResponse(
        "home.html",
        {"request": request, "now_time": datetime.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M")},
    )


@app.get("/ui/index.html", response_class=HTMLResponse)
def ui_index(request: Request):
    return templates.TemplateResponse("ui_index.html", {"request": request})
