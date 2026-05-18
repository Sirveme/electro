"""
Modelos que viven en cada schema muni_{ubigeo}.

Notas:
- Estos modelos NO declaran un schema fijo en __table_args__: el schema se selecciona
  vía SET search_path antes de ejecutar la query (ver app.database.tenant_session).
- Las FKs cruzadas a public.* se mantienen como referencias lógicas (sin ForeignKey explícito)
  cuando la columna podría romper el aislamiento del tenant.
"""

from app.models.tenant.user import Usuario
from app.models.tenant.perfil_tenant import Perfil, PerfilPermiso
from app.models.tenant.comunidad import Comunidad
from app.models.tenant.referente import Referente
from app.models.tenant.vivienda import Vivienda
from app.models.tenant.morador import Morador
from app.models.tenant.inventario import ViviendaInventario
from app.models.tenant.vivienda_foto import ViviendaFoto
from app.models.tenant.vivienda_evento import ViviendaEvento
from app.models.tenant.artefacto_config import ArtefactoConfig
from app.models.tenant.artefacto_propio import ArtefactoPropio
from app.models.tenant.config_municipio import ConfigMunicipio

__all__ = [
    "Usuario",
    "Perfil",
    "PerfilPermiso",
    "Comunidad",
    "Referente",
    "Vivienda",
    "Morador",
    "ViviendaInventario",
    "ViviendaFoto",
    "ViviendaEvento",
    "ArtefactoConfig",
    "ArtefactoPropio",
    "ConfigMunicipio",
]
