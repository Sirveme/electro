from decimal import Decimal

from sqlalchemy import Boolean, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ArtefactoPropio(Base):
    """Artefactos que el municipio agrega y no están en el maestro público."""

    __tablename__ = "artefacto_propio"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    codigo: Mapped[str] = mapped_column(String(30), nullable=False)
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    categoria: Mapped[str] = mapped_column(String(40), nullable=False)
    tarifa_mensual: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    habilitado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
