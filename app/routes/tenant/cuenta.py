"""
Cambio de clave del usuario tenant.
- Obligatorio en primer login (debe_cambiar_clave=true).
- Voluntario después.
"""
import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text

from app.context_processor import build_context
from app.database import tenant_session
from app.dependencies import CurrentUser, require_tenant
from app.security import hash_password, verify_password
from app.utils.flash import set_flash

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/app/cuenta")


def _validar_clave(nueva: str, dni: str) -> str | None:
    if len(nueva) < 8:
        return "La nueva clave debe tener al menos 8 caracteres."
    if not any(c.isalpha() for c in nueva):
        return "La nueva clave debe contener al menos una letra."
    if not any(c.isdigit() for c in nueva):
        return "La nueva clave debe contener al menos un número."
    if nueva == dni:
        return "La nueva clave no puede ser igual a tu DNI."
    return None


@router.get("/cambiar-clave", response_class=HTMLResponse)
async def form(
    request: Request,
    user: CurrentUser = Depends(require_tenant),
):
    return request.app.state.templates.TemplateResponse(
        "tenant/cuenta/cambiar_clave.html",
        build_context(request, user=user),
    )


@router.post("/cambiar-clave")
async def submit(
    request: Request,
    user: CurrentUser = Depends(require_tenant),
    clave_actual: str = Form(...),
    clave_nueva: str = Form(...),
    clave_nueva_repetir: str = Form(...),
):
    async with tenant_session(user.tenant_schema) as ts:
        row = (
            await ts.execute(
                text("SELECT access_code, dni FROM usuarios WHERE id = :id"),
                {"id": user.user_id},
            )
        ).first()
        if not row:
            set_flash(request, "error", "Usuario no encontrado.")
            return RedirectResponse("/logout", status_code=303)

        if not verify_password(clave_actual, row.access_code):
            set_flash(request, "error", "La clave actual es incorrecta.")
            return RedirectResponse("/app/cuenta/cambiar-clave", status_code=303)

        if clave_nueva != clave_nueva_repetir:
            set_flash(request, "error", "Las nuevas claves no coinciden.")
            return RedirectResponse("/app/cuenta/cambiar-clave", status_code=303)

        if verify_password(clave_nueva, row.access_code):
            set_flash(request, "error", "La nueva clave debe ser distinta a la actual.")
            return RedirectResponse("/app/cuenta/cambiar-clave", status_code=303)

        msg = _validar_clave(clave_nueva, row.dni)
        if msg:
            set_flash(request, "error", msg)
            return RedirectResponse("/app/cuenta/cambiar-clave", status_code=303)

        nuevo_hash = hash_password(clave_nueva)
        await ts.execute(
            text(
                "UPDATE usuarios "
                "SET access_code = :h, debe_cambiar_clave = FALSE "
                "WHERE id = :id"
            ),
            {"h": nuevo_hash, "id": user.user_id},
        )
        await ts.commit()

    logger.info("user_id=%s cambió clave en schema=%s", user.user_id, user.tenant_schema)
    set_flash(request, "success", "Clave actualizada correctamente.")
    return RedirectResponse("/app/", status_code=303)
