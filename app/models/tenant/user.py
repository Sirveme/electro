from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Integer, String, TIMESTAMP, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dni: Mapped[str] = mapped_column(String(8), unique=True, nullable=False)
    nombre_completo: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(120))
    telefono: Mapped[Optional[str]] = mapped_column(String(20))
    access_code: Mapped[str] = mapped_column(String(120), nullable=False)
    perfil_id: Mapped[Optional[int]] = mapped_column(Integer)
    debe_cambiar_clave: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ultimo_login: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )
