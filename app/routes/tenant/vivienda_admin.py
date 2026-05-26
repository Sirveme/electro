"""
Administración de una vivienda específica:
- GET  /app/padron/{codigo}/editar     → form de edición
- POST /app/padron/{codigo}/editar     → guarda edición
- POST /app/padron/{codigo}/anular     → soft delete
- POST /app/padron/{codigo}/reactivar  → revierte anulación

Estas rutas comparten prefijo con `padron.py` pero los segmentos literales
(/editar, /anular, /reactivar) van DESPUÉS del segmento dinámico {codigo} en
las URLs — FastAPI los matcha correctamente porque el patrón completo es
distinto. Para evitar que el router de padron.py haga shadow, registramos
este router DESPUÉS en main.py.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text

from app.context_processor import build_context
from app.database import tenant_session
from app.dependencies import CurrentUser, require_password_changed
from app.services.csrf import verify_csrf
from app.services.vivienda_service import (
    MOTIVOS_VALIDOS,
    ViviendaError,
    anular_vivienda,
    modificar_vivienda,
    reactivar_vivienda,
)
from app.utils.flash import set_flash

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/app/padron")


async def _cargar_vivienda_por_codigo(ts, codigo: str) -> dict | None:
    row = (
        await ts.execute(
            text(
                "SELECT v.*, c.nombre AS comunidad_nombre, "
                "       r.nombre_completo AS referente_nombre "
                "FROM viviendas v "
                "LEFT JOIN comunidades c ON c.id = v.comunidad_id "
                "LEFT JOIN referentes r ON r.id = v.referente_id "
                "WHERE v.codigo_interno = :c"
            ),
            {"c": codigo},
        )
    ).mappings().first()
    return dict(row) if row else None


# ============ EDITAR ============

@router.get("/{codigo}/editar", response_class=HTMLResponse)
async def form_editar(
    request: Request,
    codigo: str,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("viviendas", "admin", "editar"):
        raise HTTPException(403, "Sin permiso para editar viviendas")

    async with tenant_session(user.tenant_schema) as ts:
        vivienda = await _cargar_vivienda_por_codigo(ts, codigo)
        if not vivienda:
            raise HTTPException(404, "Vivienda no encontrada")
        if vivienda["anulada_at"] is not None:
            set_flash(
                request, "error",
                "No se puede editar una vivienda anulada. Reactivarla primero.",
            )
            return RedirectResponse(f"/app/padron/{codigo}", status_code=303)

        comunidades = (
            await ts.execute(
                text("SELECT id, nombre FROM comunidades WHERE activa = TRUE ORDER BY nombre")
            )
        ).all()
        referentes = (
            await ts.execute(
                text(
                    "SELECT id, nombre_completo, cargo FROM referentes "
                    "WHERE activo = TRUE ORDER BY nombre_completo"
                )
            )
        ).all()

    return request.app.state.templates.TemplateResponse(
        "tenant/padron/ficha_editar.html",
        build_context(
            request, user=user,
            vivienda=vivienda,
            comunidades=comunidades,
            referentes=referentes,
        ),
    )


@router.post("/{codigo}/editar", dependencies=[Depends(verify_csrf)])
async def submit_editar(
    request: Request,
    codigo: str,
    user: CurrentUser = Depends(require_password_changed),
    comunidad_id: int = Form(...),
    referente_id: str = Form(""),
    referencia_fisica: str = Form(...),
    fuente_validacion: str = Form(""),
    estado_servicio: str = Form(...),
    modo_calculo: str = Form(...),
    observaciones: str = Form(""),
):
    if not user.puede("viviendas", "admin", "editar"):
        raise HTTPException(403, "Sin permiso para editar viviendas")

    cambios = {
        "comunidad_id":      comunidad_id,
        "referente_id":      int(referente_id) if referente_id.strip() else None,
        "referencia_fisica": referencia_fisica.strip(),
        "fuente_validacion": fuente_validacion.strip(),
        "estado_servicio":   estado_servicio,
        "modo_calculo":      modo_calculo,
        "observaciones":     observaciones.strip(),
    }

    async with tenant_session(user.tenant_schema) as ts:
        vid = (
            await ts.execute(
                text("SELECT id FROM viviendas WHERE codigo_interno = :c"),
                {"c": codigo},
            )
        ).scalar()
        if not vid:
            raise HTTPException(404, "Vivienda no encontrada")
        try:
            modificados = await modificar_vivienda(ts, vid, cambios, user.user_id)
        except ViviendaError as exc:
            await ts.rollback()
            set_flash(request, "error", str(exc))
            return RedirectResponse(f"/app/padron/{codigo}/editar", status_code=303)

    if modificados:
        set_flash(request, "success", f"Cambios guardados ({len(modificados)} campo(s)).")
    else:
        set_flash(request, "info", "No había cambios para guardar.")
    return RedirectResponse(f"/app/padron/{codigo}", status_code=303)


# ============ ANULAR ============

@router.post("/{codigo}/anular", dependencies=[Depends(verify_csrf)])
async def submit_anular(
    request: Request,
    codigo: str,
    user: CurrentUser = Depends(require_password_changed),
    motivo: str = Form(...),
    observacion: str = Form(""),
):
    if not user.puede("viviendas", "admin", "anular"):
        raise HTTPException(403, "Sin permiso para anular viviendas")

    if motivo not in MOTIVOS_VALIDOS:
        set_flash(request, "error", "Motivo de anulación inválido.")
        return RedirectResponse(f"/app/padron/{codigo}", status_code=303)

    async with tenant_session(user.tenant_schema) as ts:
        vid = (
            await ts.execute(
                text("SELECT id FROM viviendas WHERE codigo_interno = :c"),
                {"c": codigo},
            )
        ).scalar()
        if not vid:
            raise HTTPException(404, "Vivienda no encontrada")
        try:
            await anular_vivienda(ts, vid, motivo, observacion, user.user_id)
        except ViviendaError as exc:
            await ts.rollback()
            set_flash(request, "error", str(exc))
            return RedirectResponse(f"/app/padron/{codigo}", status_code=303)

    set_flash(request, "success", "Vivienda anulada correctamente.")
    return RedirectResponse(f"/app/padron/{codigo}", status_code=303)


# ============ REACTIVAR ============

@router.post("/{codigo}/reactivar", dependencies=[Depends(verify_csrf)])
async def submit_reactivar(
    request: Request,
    codigo: str,
    user: CurrentUser = Depends(require_password_changed),
    motivo_reactivacion: str = Form(...),
):
    if not user.puede("viviendas", "admin", "reactivar"):
        raise HTTPException(403, "Sin permiso para reactivar viviendas")

    async with tenant_session(user.tenant_schema) as ts:
        vid = (
            await ts.execute(
                text("SELECT id FROM viviendas WHERE codigo_interno = :c"),
                {"c": codigo},
            )
        ).scalar()
        if not vid:
            raise HTTPException(404, "Vivienda no encontrada")
        try:
            await reactivar_vivienda(ts, vid, motivo_reactivacion, user.user_id)
        except ViviendaError as exc:
            await ts.rollback()
            set_flash(request, "error", str(exc))
            return RedirectResponse(f"/app/padron/{codigo}", status_code=303)

    set_flash(request, "success", "Vivienda reactivada correctamente.")
    return RedirectResponse(f"/app/padron/{codigo}", status_code=303)
