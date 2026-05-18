from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, Integer, String, TIMESTAMP, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Morador(Base):
    __tablename__ = "moradores"
    __table_args__ = (UniqueConstraint("vivienda_id", "dni"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vivienda_id: Mapped[int] = mapped_column(Integer, nullable=False)
    dni: Mapped[str] = mapped_column(String(8), nullable=False)
    nombre_completo: Mapped[str] = mapped_column(String(160), nullable=False)
    fecha_nacimiento: Mapped[Optional[date]] = mapped_column(Date)
    sexo: Mapped[Optional[str]] = mapped_column(String(1))
    telefono: Mapped[Optional[str]] = mapped_column(String(20))
    es_jefe_familia: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    es_responsable_pago: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dni_foto_url: Mapped[Optional[str]] = mapped_column(String(400))
    acceso_portal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    access_code: Mapped[Optional[str]] = mapped_column(String(120))
    debe_cambiar_clave: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ultimo_login: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
