from decimal import Decimal

from sqlalchemy import Boolean, Integer, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ArtefactoConfig(Base):
    """Override del maestro public.artefacto_catalogo para un tenant específico."""

    __tablename__ = "artefacto_config"
    __table_args__ = (UniqueConstraint("catalogo_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    catalogo_id: Mapped[int] = mapped_column(Integer, nullable=False)
    tarifa_mensual: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    habilitado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
