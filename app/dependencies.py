import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session, tenant_session

logger = logging.getLogger(__name__)

CAMBIAR_CLAVE_PATH = "/app/cuenta/cambiar-clave"
LOGOUT_PATH = "/logout"


class CurrentUser:
    """Representa el usuario autenticado (superadmin o usuario de tenant)."""

    def __init__(
        self,
        kind: str,
        user_id: int,
        nombre: str,
        username_or_dni: str,
        tenant_schema: Optional[str] = None,
        perfil_codigo: Optional[str] = None,
        permisos: Optional[list[str]] = None,
        debe_cambiar_clave: bool = False,
    ):
        self.kind = kind  # "superadmin" | "tenant"
        self.user_id = user_id
        self.nombre = nombre
        self.username_or_dni = username_or_dni
        self.tenant_schema = tenant_schema
        self.perfil_codigo = perfil_codigo
        self.permisos = permisos or []
        self.debe_cambiar_clave = debe_cambiar_clave

    @property
    def is_superadmin(self) -> bool:
        return self.kind == "superadmin"

    @property
    def is_tenant(self) -> bool:
        return self.kind == "tenant"

    def puede(self, modulo: str, opcion: str, accion: str) -> bool:
        if self.is_superadmin:
            return True
        codigo = f"{modulo}.{opcion}.{accion}"
        codigo_short = f"{modulo}.{opcion}"
        return codigo in self.permisos or codigo_short in self.permisos


async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> Optional[CurrentUser]:
    """Devuelve el usuario actual si hay sesión válida, sino None."""
    sess = request.session
    kind = sess.get("kind")
    if not kind:
        return None

    if kind == "superadmin":
        uid = sess.get("user_id")
        if not uid:
            return None
        row = (
            await db.execute(
                text(
                    "SELECT id, username, nombre FROM public.superadmin_users "
                    "WHERE id = :id AND activo = TRUE"
                ),
                {"id": uid},
            )
        ).first()
        if not row:
            return None
        return CurrentUser(
            kind="superadmin",
            user_id=row.id,
            nombre=row.nombre,
            username_or_dni=row.username,
        )

    if kind == "tenant":
        uid = sess.get("user_id")
        schema = sess.get("tenant_schema")
        if not uid or not schema:
            return None
        async with tenant_session(schema) as ts:
            row = (
                await ts.execute(
                    text(
                        "SELECT u.id, u.dni, u.nombre_completo, u.debe_cambiar_clave, "
                        "       p.codigo AS perfil_codigo "
                        "FROM usuarios u LEFT JOIN perfiles p ON p.id = u.perfil_id "
                        "WHERE u.id = :id AND u.activo = TRUE"
                    ),
                    {"id": uid},
                )
            ).first()
            if not row:
                return None
            permisos_rows = (
                await ts.execute(
                    text(
                        "SELECT permiso_codigo FROM perfiles_permisos "
                        "WHERE perfil_id = (SELECT perfil_id FROM usuarios WHERE id = :id)"
                    ),
                    {"id": uid},
                )
            ).all()
            permisos = [r.permiso_codigo for r in permisos_rows]
            return CurrentUser(
                kind="tenant",
                user_id=row.id,
                nombre=row.nombre_completo,
                username_or_dni=row.dni,
                tenant_schema=schema,
                perfil_codigo=row.perfil_codigo,
                permisos=permisos,
                debe_cambiar_clave=bool(row.debe_cambiar_clave),
            )

    return None


async def require_login(
    user: Optional[CurrentUser] = Depends(get_current_user_optional),
) -> CurrentUser:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesión requerida",
            headers={"Location": "/login"},
        )
    return user


async def require_superadmin(
    user: CurrentUser = Depends(require_login),
) -> CurrentUser:
    if not user.is_superadmin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo superadmin")
    return user


class RedirectException(Exception):
    """Excepción usada por dependencias para forzar un redirect 303."""
    def __init__(self, location: str):
        self.location = location


async def require_tenant(
    user: CurrentUser = Depends(require_login),
) -> CurrentUser:
    if not user.is_tenant:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo usuario de municipio")
    return user


async def require_password_changed(
    request: Request,
    user: CurrentUser = Depends(require_tenant),
) -> CurrentUser:
    """
    Bloquea acceso a todas las rutas tenant si debe_cambiar_clave=true,
    salvo /app/cuenta/cambiar-clave y /logout.
    """
    if not user.debe_cambiar_clave:
        return user
    path = request.url.path
    if path == CAMBIAR_CLAVE_PATH or path == LOGOUT_PATH:
        return user
    raise RedirectException(CAMBIAR_CLAVE_PATH)


def require_permission(modulo: str, opcion: str, accion: str):
    """Factory para dependencia que exige un permiso atómico."""

    async def _checker(user: CurrentUser = Depends(require_login)) -> CurrentUser:
        if not user.puede(modulo, opcion, accion):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Permiso requerido: {modulo}.{opcion}.{accion}",
            )
        return user

    return _checker


def redirect_to_login() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
