from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, TIMESTAMP, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Vivienda(Base):
    __tablename__ = "viviendas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    codigo_interno: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    comunidad_id: Mapped[int] = mapped_column(Integer, nullable=False)
    referente_id: Mapped[Optional[int]] = mapped_column(Integer)
    fuente_validacion: Mapped[Optional[str]] = mapped_column(String(80))
    referencia_fisica: Mapped[str] = mapped_column(Text, nullable=False)
    direccion_textual: Mapped[Optional[str]] = mapped_column(String(200))
    gps_lat: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 7))
    gps_lng: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 7))
    gps_precision_metros: Mapped[Optional[int]] = mapped_column(Integer)
    foto_fachada_url: Mapped[Optional[str]] = mapped_column(String(400))
    estado_servicio: Mapped[str] = mapped_column(String(20), nullable=False, default="activo")
    observaciones: Mapped[Optional[str]] = mapped_column(Text)
    empadronada_por_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    empadronada_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )
    actualizada_por_user_id: Mapped[Optional[int]] = mapped_column(Integer)
    actualizada_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
