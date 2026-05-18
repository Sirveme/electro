from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Integer, String, TIMESTAMP, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ViviendaEvento(Base):
    """Bitácora de eventos de la vivienda: empadronamiento, revisita, alta/baja artefacto, etc."""

    __tablename__ = "vivienda_eventos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vivienda_id: Mapped[int] = mapped_column(Integer, nullable=False)
    tipo: Mapped[str] = mapped_column(String(40), nullable=False)
    descripcion: Mapped[Optional[str]] = mapped_column(Text)
    extra_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column("metadata", JSONB)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )
