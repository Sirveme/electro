from typing import Optional

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Perfil(Base):
    __tablename__ = "perfiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    codigo: Mapped[str] = mapped_column(String(40), nullable=False)
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    descripcion: Mapped[Optional[str]] = mapped_column(String(200))


class PerfilPermiso(Base):
    __tablename__ = "perfiles_permisos"

    perfil_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    permiso_codigo: Mapped[str] = mapped_column(String(80), primary_key=True)
