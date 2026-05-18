from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ArtefactoCatalogo(Base):
    __tablename__ = "artefacto_catalogo"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    codigo: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    categoria: Mapped[str] = mapped_column(String(40), nullable=False)
    icono: Mapped[Optional[str]] = mapped_column(String(40))
    descripcion: Mapped[Optional[str]] = mapped_column(Text)
    tarifa_sugerida: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    activo_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
