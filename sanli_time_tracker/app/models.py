from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    devices = relationship("Device", back_populates="employee")
    time_entries = relationship("TimeEntry", back_populates="employee")


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    device_token: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    employee = relationship("Employee", back_populates="devices")
    time_entries = relationship("TimeEntry", back_populates="device")


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    qr_code_slug: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)

    time_entries = relationship("TimeEntry", back_populates="vehicle")


class TimeEntry(Base):
    __tablename__ = "time_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    employee_name: Mapped[str] = mapped_column(String(120), nullable=False)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overtime_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)

    employee = relationship("Employee", back_populates="time_entries")
    device = relationship("Device", back_populates="time_entries")
    vehicle = relationship("Vehicle", back_populates="time_entries")


class RegistrationToken(Base):
    __tablename__ = "registration_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    token: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    employee = relationship("Employee")


class MonthlySummary(Base):
    __tablename__ = "monthly_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    month: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"), nullable=True)
    total_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    overtime_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active_entries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_entries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    missing_checkout_entries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PayrollExport(Base):
    __tablename__ = "payroll_exports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    report_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    filters_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ImportedFile(Base):
    __tablename__ = "imported_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(60), nullable=False)
    imported_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
