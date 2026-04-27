# ============================================================
# CLOUDIA FIELD OS — Data Models
# ============================================================

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# ---- Admin UI (FastAPI session + admin_users) ----


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="owner")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    force_password_change: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    password_reset_tokens = relationship(
        "AdminPasswordResetToken", back_populates="user", cascade="all, delete-orphan"
    )


class AdminPasswordResetToken(Base):
    """Single-use admin password reset link (token stored as HMAC digest only)."""

    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user = relationship("AdminUser", back_populates="password_reset_tokens")


# provisional_workers.status
PW_STATUS_PENDING = "pending_registration"
PW_STATUS_ACTIVE = "active"
PW_STATUS_DEACTIVATED = "deactivated"

# provisional_vehicles.status (self-register → admin approves)
PV_VEHICLE_PENDING = "pending_vehicle"
PV_VEHICLE_APPROVED = "approved_vehicle"
PV_VEHICLE_REJECTED = "rejected_vehicle"


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone_number: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    date_of_birth: Mapped[str | None] = mapped_column(String(32), nullable=True)
    hourly_rate: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    overtime_multiplier: Mapped[float] = mapped_column(Float, default=1.5, nullable=False)
    overtime_hourly_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    devices = relationship("Device", back_populates="employee", foreign_keys="Device.employee_id")
    phones = relationship("EmployeePhone", back_populates="employee", cascade="all, delete-orphan")


class EmployeePhone(Base):
    __tablename__ = "employee_phones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(60), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_temporary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    employee = relationship("Employee", back_populates="phones")


class WorkerRegistrationToken(Base):
    """Single-use pool: one active row gates public /worker-register/{token} (self-service worker onboarding)."""

    __tablename__ = "worker_registration_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    token: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProvisionalWorker(Base):
    __tablename__ = "provisional_workers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str] = mapped_column(String(60), nullable=False)
    secondary_phone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    primary_phone_is_temporary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    date_of_birth: Mapped[str | None] = mapped_column(String(32), nullable=True)
    device_token: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    registration_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    possible_duplicate_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)

    devices = relationship("Device", back_populates="provisional_worker", foreign_keys="Device.provisional_worker_id")


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True, index=True)
    provisional_worker_id: Mapped[int | None] = mapped_column(
        ForeignKey("provisional_workers.id"), nullable=True, index=True
    )
    device_token: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    employee = relationship("Employee", back_populates="devices", foreign_keys=[employee_id])
    provisional_worker = relationship("ProvisionalWorker", back_populates="devices", foreign_keys=[provisional_worker_id])


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    qr_code_slug: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ProvisionalVehicle(Base):
    """Field self-registration: pending until admin creates the real Vehicle row."""

    __tablename__ = "provisional_vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    qr_slug_hint: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"), nullable=True, index=True)


class TimeEntry(Base):
    __tablename__ = "time_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True, index=True)
    provisional_worker_id: Mapped[int | None] = mapped_column(
        ForeignKey("provisional_workers.id"), nullable=True, index=True
    )
    employee_name: Mapped[str] = mapped_column(String(120), nullable=False)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    regular_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overtime_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    regular_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    overtime_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)


class TimeEntryCorrection(Base):
    __tablename__ = "time_entry_corrections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    time_entry_id: Mapped[int] = mapped_column(ForeignKey("time_entries.id"), nullable=False, index=True)
    old_clock_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    old_clock_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    new_clock_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    new_clock_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    old_employee_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_employee_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    old_vehicle_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_vehicle_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    corrected_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    corrected_by_role: Mapped[str | None] = mapped_column(String(60), nullable=True)
    corrected_by_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    corrected_by_user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)


class RegistrationToken(Base):
    __tablename__ = "registration_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    token: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ImportedFile(Base):
    __tablename__ = "imported_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    imported_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
