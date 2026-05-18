from typing import Optional

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ConfigMunicipio(Base):
    """Tabla clave-valor con la configuración del municipio (tarifas, plazos, flags)."""

    __tablename__ = "config_municipio"

    clave: Mapped[str] = mapped_column(String(60), primary_key=True)
    valor: Mapped[Optional[str]] = mapped_column(Text)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="string")
    descripcion: Mapped[Optional[str]] = mapped_column(String(200))
