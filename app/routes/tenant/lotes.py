"""Lotes de facturación: listar, generar, ver, anular."""
import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.context_processor import build_context
from app.database import tenant_session
from app.dependencies import CurrentUser, require_password_changed
from app.services.csrf import verify_csrf
from app.services.lote_service import (
    LoteError,
    anular_lote,
    generar_lote_mensual,
    listar_cuotas_del_lote,
    listar_lotes,
    obtener_lote,
)
from app.utils.flash import set_flash
from app.utils.periodos import (
    nombre_periodo_largo,
    periodo_actual_a_facturar,
    ultimo_dia_del_mes,
    vencimiento_por_periodo,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/app/cobranza/lotes")


@router.get("/", response_class=HTMLResponse)
async def listar(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("lotes", "facturacion", "ver"):
        raise HTTPException(403, "Sin permiso")
    async with tenant_session(user.tenant_schema) as ts:
        lotes = await listar_lotes(ts)
    return request.app.state.templates.TemplateResponse(
        "tenant/lotes/lista.html",
        build_context(request, user=user, lotes=lotes, nombre_periodo=nombre_periodo_largo),
    )


@router.get("/nuevo", response_class=HTMLResponse)
async def nuevo_form(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("lotes", "facturacion", "generar"):
        raise HTTPException(403, "Sin permiso")
    hoy = date.today()
    anio, mes = periodo_actual_a_facturar(hoy)
    return request.app.state.templates.TemplateResponse(
        "tenant/lotes/nuevo.html",
        build_context(
            request, user=user,
            anio_default=anio, mes_default=mes,
            ultimo_dia_default=ultimo_dia_del_mes(anio, mes).isoformat(),
            vencimiento_default=vencimiento_por_periodo(anio, mes).isoformat(),
        ),
    )


@router.post("/nuevo", dependencies=[Depends(verify_csrf)])
async def nuevo_submit(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
    periodo_anio: int = Form(...),
    periodo_mes: int = Form(...),
    fecha_emision: str = Form(...),
    fecha_vencimiento: str = Form(...),
):
    if not user.puede("lotes", "facturacion", "generar"):
        raise HTTPException(403, "Sin permiso")
    try:
        fe = datetime.strptime(fecha_emision, "%Y-%m-%d").date()
        fv = datetime.strptime(fecha_vencimiento, "%Y-%m-%d").date()
    except ValueError:
        set_flash(request, "error", "Fechas inválidas.")
        return RedirectResponse("/app/cobranza/lotes/nuevo", status_code=303)
    if periodo_mes < 1 or periodo_mes > 12:
        set_flash(request, "error", "Mes inválido.")
        return RedirectResponse("/app/cobranza/lotes/nuevo", status_code=303)

    try:
        async with tenant_session(user.tenant_schema) as ts:
            result = await generar_lote_mensual(
                ts,
                periodo_anio=periodo_anio,
                periodo_mes=periodo_mes,
                fecha_emision=fe,
                fecha_vencimiento=fv,
                user_id=user.user_id,
            )
            await ts.commit()
    except LoteError as exc:
        set_flash(request, "error", str(exc))
        return RedirectResponse("/app/cobranza/lotes/nuevo", status_code=303)

    msg = (
        f"Lote #{result['lote_id']} generado: "
        f"{result['ok']} recibos OK, {result['fail']} fallidos de {result['total_viviendas']} viviendas."
    )
    set_flash(request, "success" if result["fail"] == 0 else "warning", msg)
    return RedirectResponse(f"/app/cobranza/lotes/{result['lote_id']}", status_code=303)


@router.get("/{lote_id}", response_class=HTMLResponse)
async def detalle(
    request: Request,
    lote_id: int,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("lotes", "facturacion", "ver"):
        raise HTTPException(403, "Sin permiso")
    async with tenant_session(user.tenant_schema) as ts:
        lote = await obtener_lote(ts, lote_id)
        if not lote:
            raise HTTPException(404, "Lote no encontrado")
        cuotas = await listar_cuotas_del_lote(ts, lote_id)
    return request.app.state.templates.TemplateResponse(
        "tenant/lotes/detalle.html",
        build_context(
            request, user=user, lote=lote, cuotas=cuotas,
            periodo_label=nombre_periodo_largo(lote["periodo_anio"], lote["periodo_mes"]),
        ),
    )


@router.post("/{lote_id}/anular", dependencies=[Depends(verify_csrf)])
async def anular(
    request: Request,
    lote_id: int,
    user: CurrentUser = Depends(require_password_changed),
    motivo: str = Form(...),
):
    if not user.puede("lotes", "facturacion", "anular"):
        raise HTTPException(403, "Sin permiso")
    try:
        async with tenant_session(user.tenant_schema) as ts:
            await anular_lote(ts, lote_id, motivo, user.user_id)
            await ts.commit()
    except LoteError as exc:
        set_flash(request, "error", str(exc))
        return RedirectResponse(f"/app/cobranza/lotes/{lote_id}", status_code=303)
    set_flash(request, "success", "Lote anulado.")
    return RedirectResponse(f"/app/cobranza/lotes/{lote_id}", status_code=303)
