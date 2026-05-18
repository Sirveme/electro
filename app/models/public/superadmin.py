from datetime import datetime

from sqlalchemy import Boolean, Integer, String, TIMESTAMP, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SuperadminUser(Base):
    __tablename__ = "superadmin_users"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    access_code: Mapped[str] = mapped_column(String(120), nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )
