from typing import Optional

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Referente(Base):
    __tablename__ = "referentes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre_completo: Mapped[str] = mapped_column(String(160), nullable=False)
    cargo: Mapped[str] = mapped_column(String(40), nullable=False)
    dni: Mapped[Optional[str]] = mapped_column(String(8))
    telefono: Mapped[Optional[str]] = mapped_column(String(20))
    foto_url: Mapped[Optional[str]] = mapped_column(String(300))
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
