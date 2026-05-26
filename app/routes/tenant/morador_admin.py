"""
Edición de un morador:
- GET  /app/padron/{codigo}/morador/{morador_id}/editar
- POST /app/padron/{codigo}/morador/{morador_id}/editar

El DNI se muestra readonly en el formulario — no es editable.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text

from app.context_processor import build_context
from app.database import tenant_session
from app.dependencies import CurrentUser, require_password_changed
from app.services.csrf import verify_csrf
from app.services.morador_service import MoradorError, modificar_morador
from app.utils.flash import set_flash

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/app/padron")


async def _cargar_morador(ts, codigo: str, morador_id: int) -> dict | None:
    """Devuelve el morador junto con datos mínimos de la vivienda."""
    row = (
        await ts.execute(
            text(
                "SELECT m.*, v.codigo_interno AS v_codigo, v.anulada_at AS v_anulada_at "
                "FROM moradores m JOIN viviendas v ON v.id = m.vivienda_id "
                "WHERE v.codigo_interno = :c AND m.id = :mid"
            ),
            {"c": codigo, "mid": morador_id},
        )
    ).mappings().first()
    return dict(row) if row else None


@router.get("/{codigo}/morador/{morador_id}/editar", response_class=HTMLResponse)
async def form_editar_morador(
    request: Request,
    codigo: str,
    morador_id: int,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("moradores", "admin", "editar"):
        raise HTTPException(403, "Sin permiso para editar moradores")

    async with tenant_session(user.tenant_schema) as ts:
        morador = await _cargar_morador(ts, codigo, morador_id)
        if not morador:
            raise HTTPException(404, "Morador no encontrado")
        if morador["v_anulada_at"] is not None:
            set_flash(
                request, "error",
                "No se puede editar un morador de una vivienda anulada.",
            )
            return RedirectResponse(f"/app/padron/{codigo}", status_code=303)
        if not morador["activo"]:
            set_flash(request, "error", "El morador está inactivo.")
            return RedirectResponse(f"/app/padron/{codigo}", status_code=303)

    return request.app.state.templates.TemplateResponse(
        "tenant/padron/morador_editar.html",
        build_context(
            request, user=user,
            codigo=codigo,
            morador=morador,
        ),
    )


@router.post(
    "/{codigo}/morador/{morador_id}/editar",
    dependencies=[Depends(verify_csrf)],
)
async def submit_editar_morador(
    request: Request,
    codigo: str,
    morador_id: int,
    user: CurrentUser = Depends(require_password_changed),
    nombre_completo: str = Form(...),
    sexo: str = Form(""),
    fecha_nacimiento: str = Form(""),
    telefono: str = Form(""),
    es_jefe_familia: Optional[str] = Form(None),
    es_responsable_pago: Optional[str] = Form(None),
    acceso_portal: Optional[str] = Form(None),
):
    if not user.puede("moradores", "admin", "editar"):
        raise HTTPException(403, "Sin permiso para editar moradores")

    cambios = {
        "nombre_completo":     nombre_completo,
        "sexo":                sexo,
        "fecha_nacimiento":    fecha_nacimiento,
        "telefono":            telefono,
        "es_jefe_familia":     es_jefe_familia == "on",
        "es_responsable_pago": es_responsable_pago == "on",
        "acceso_portal":       acceso_portal == "on",
    }

    async with tenant_session(user.tenant_schema) as ts:
        try:
            modificados = await modificar_morador(ts, morador_id, cambios, user.user_id)
        except MoradorError as exc:
            await ts.rollback()
            set_flash(request, "error", str(exc))
            return RedirectResponse(
                f"/app/padron/{codigo}/morador/{morador_id}/editar",
                status_code=303,
            )

    if modificados:
        set_flash(
            request, "success",
            f"Morador actualizado ({len(modificados)} campo(s)).",
        )
    else:
        set_flash(request, "info", "No había cambios para guardar.")
    return RedirectResponse(f"/app/padron/{codigo}", status_code=303)
