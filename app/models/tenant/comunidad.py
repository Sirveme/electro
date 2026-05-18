from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Integer, String, TIMESTAMP, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Comunidad(Base):
    __tablename__ = "comunidades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    referente_principal_id: Mapped[Optional[int]] = mapped_column(Integer)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )
