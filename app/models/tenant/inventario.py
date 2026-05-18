from datetime import date, datetime
from typing import Optional

from sqlalchemy import CheckConstraint, Date, Integer, String, TIMESTAMP, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ViviendaInventario(Base):
    """
    Effective dating: una fila por evento.
    vigente_hasta IS NULL => vigente.
    Al "dar de baja" se setea vigente_hasta = ayer.
    """

    __tablename__ = "vivienda_inventario"
    __table_args__ = (
        CheckConstraint("artefacto_origen IN ('catalogo', 'propio')"),
        CheckConstraint("cantidad > 0"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vivienda_id: Mapped[int] = mapped_column(Integer, nullable=False)
    artefacto_origen: Mapped[str] = mapped_column(String(10), nullable=False)
    artefacto_codigo: Mapped[str] = mapped_column(String(30), nullable=False)
    artefacto_nombre_snapshot: Mapped[str] = mapped_column(String(80), nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    vigente_desde: Mapped[date] = mapped_column(Date, nullable=False)
    vigente_hasta: Mapped[Optional[date]] = mapped_column(Date)
    motivo_alta: Mapped[Optional[str]] = mapped_column(String(40))
    motivo_baja: Mapped[Optional[str]] = mapped_column(String(40))
    registrado_por_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    dado_de_baja_por_user_id: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )
