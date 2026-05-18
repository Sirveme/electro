from typing import Optional

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Permiso(Base):
    __tablename__ = "permisos"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    codigo: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    modulo: Mapped[str] = mapped_column(String(40), nullable=False)
    opcion: Mapped[str] = mapped_column(String(40), nullable=False)
    accion: Mapped[str] = mapped_column(String(40), nullable=False)
    descripcion: Mapped[Optional[str]] = mapped_column(String(200))


class PerfilPlantilla(Base):
    __tablename__ = "perfiles_plantilla"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    codigo: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    descripcion: Mapped[Optional[str]] = mapped_column(String(200))
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=100)


class PerfilPlantillaPermiso(Base):
    __tablename__ = "perfiles_plantilla_permisos"
    __table_args__ = {"schema": "public"}

    perfil_id: Mapped[int] = mapped_column(
        ForeignKey("public.perfiles_plantilla.id", ondelete="CASCADE"), primary_key=True
    )
    permiso_id: Mapped[int] = mapped_column(
        ForeignKey("public.permisos.id", ondelete="CASCADE"), primary_key=True
    )
