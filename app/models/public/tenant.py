from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, TIMESTAMP, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Municipio(Base):
    __tablename__ = "municipios"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ubigeo: Mapped[str] = mapped_column(String(6), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    departamento: Mapped[Optional[str]] = mapped_column(String(60))
    provincia: Mapped[Optional[str]] = mapped_column(String(60))
    distrito: Mapped[Optional[str]] = mapped_column(String(60))
    schema_name: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    responsable_nombre: Mapped[Optional[str]] = mapped_column(String(120))
    responsable_dni: Mapped[Optional[str]] = mapped_column(String(8))
    responsable_telefono: Mapped[Optional[str]] = mapped_column(String(20))
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )
    created_by: Mapped[Optional[int]] = mapped_column(Integer)

    suscripciones: Mapped[list["Suscripcion"]] = relationship(
        back_populates="municipio", cascade="all, delete-orphan"
    )


class Suscripcion(Base):
    __tablename__ = "suscripciones"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    municipio_id: Mapped[int] = mapped_column(
        ForeignKey("public.municipios.id", ondelete="CASCADE"), nullable=False
    )
    plan: Mapped[str] = mapped_column(String(20), nullable=False, default="demo")
    vigente_desde: Mapped[date] = mapped_column(Date, nullable=False)
    vigente_hasta: Mapped[Optional[date]] = mapped_column(Date)
    precio_mensual: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    municipio: Mapped["Municipio"] = relationship(back_populates="suscripciones")
