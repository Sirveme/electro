from datetime import datetime

from sqlalchemy import Boolean, Integer, String, TIMESTAMP, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ViviendaFoto(Base):
    __tablename__ = "vivienda_fotos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vivienda_id: Mapped[int] = mapped_column(Integer, nullable=False)
    url: Mapped[str] = mapped_column(String(400), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="fachada")
    tomada_por_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    tomada_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )
    es_actual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
