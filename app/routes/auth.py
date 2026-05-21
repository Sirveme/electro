"""
Login/logout. Detecta automáticamente si el usuario es superadmin (por username)
o usuario de tenant (por DNI, buscando en TODOS los schemas muni_*).

Tras login exitoso de un usuario tenant:
- Si debe_cambiar_clave=true → redirige a /app/cuenta/cambiar-clave
- Sino → redirige a /app/
"""
import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.context_processor import build_context
from app.database import get_session, tenant_session
from app.security import (
    hash_password,
    needs_rehash,
    verify_password,
)
from app.services.csrf import verify_csrf
from app.utils.flash import set_flash

logger = logging.getLogger(__name__)
router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return _templates(request).TemplateResponse(
        "auth/login.html",
        build_context(request, user=None),
    )


@router.post("/login", dependencies=[Depends(verify_csrf)])
async def login_submit(
    request: Request,
    usuario: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_session),
):
    # El dependency verify_csrf ya validó el token antes de entrar aquí.
    usuario_n = (usuario or "").strip()

    # 1) Intentar superadmin (username)
    row = (
        await db.execute(
            text(
                "SELECT id, username, nombre, access_code FROM public.superadmin_users "
                "WHERE username = :u AND activo = TRUE"
            ),
            {"u": usuario_n},
        )
    ).first()
    if row and verify_password(password, row.access_code):
        request.session.clear()
        request.session["kind"] = "superadmin"
        request.session["user_id"] = row.id
        if needs_rehash(row.access_code):
            new_hash = hash_password(password)
            await db.execute(
                text("UPDATE public.superadmin_users SET access_code = :h WHERE id = :id"),
                {"h": new_hash, "id": row.id},
            )
            await db.commit()
        return RedirectResponse("/sa/", status_code=303)

    # 2) Buscar en todos los schemas muni_* por DNI
    if usuario_n.isdigit() and len(usuario_n) == 8:
        schemas = (
            await db.execute(
                text(
                    "SELECT nspname FROM pg_namespace WHERE nspname LIKE 'muni\\_%' ESCAPE '\\'"
                )
            )
        ).all()
        for s in schemas:
            schema_name = s.nspname
            async with tenant_session(schema_name) as ts:
                u = (
                    await ts.execute(
                        text(
                            "SELECT id, dni, nombre_completo, access_code, debe_cambiar_clave "
                            "FROM usuarios WHERE dni = :d AND activo = TRUE"
                        ),
                        {"d": usuario_n},
                    )
                ).first()
                if u and verify_password(password, u.access_code):
                    request.session.clear()
                    request.session["kind"] = "tenant"
                    request.session["user_id"] = u.id
                    request.session["tenant_schema"] = schema_name
                    await ts.execute(
                        text("UPDATE usuarios SET ultimo_login = NOW() WHERE id = :id"),
                        {"id": u.id},
                    )
                    if needs_rehash(u.access_code):
                        await ts.execute(
                            text("UPDATE usuarios SET access_code = :h WHERE id = :id"),
                            {"h": hash_password(password), "id": u.id},
                        )
                    await ts.commit()
                    if u.debe_cambiar_clave:
                        return RedirectResponse("/app/cuenta/cambiar-clave", status_code=303)
                    return RedirectResponse("/app/", status_code=303)

    set_flash(request, "error", "Credenciales invalidas.")
    return _templates(request).TemplateResponse(
        "auth/login.html",
        build_context(request, user=None, usuario_value=usuario_n),
        status_code=401,
    )


@router.post("/logout", dependencies=[Depends(verify_csrf)])
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/logout")
async def logout_get(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
