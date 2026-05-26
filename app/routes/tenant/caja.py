"""Caja diaria: apertura, cierre con arqueo, reporte por apertura."""
import logging
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.context_processor import build_context
from app.database import tenant_session
from app.dependencies import CurrentUser, require_password_changed
from app.services.caja_service import (
    CajaError,
    abrir_caja,
    caja_abierta_de,
    calcular_monto_esperado,
    cerrar_caja,
    listar_aperturas,
    listar_pagos_de_caja,
    obtener_apertura,
)
from app.services.csrf import verify_csrf
from app.utils.flash import set_flash

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/app/caja")


def _parse_decimal(raw: str) -> Decimal:
    try:
        return Decimal(str(raw or "0").strip().replace(",", "."))
    except (InvalidOperation, AttributeError, ValueError) as exc:
        raise CajaError(f"Monto inválido: '{raw}'") from exc


@router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("caja", "diaria", "ver_propia"):
        raise HTTPException(403, "Sin permiso")
    async with tenant_session(user.tenant_schema) as ts:
        caja = await caja_abierta_de(ts, user.user_id)
        monto_esperado = None
        pagos = []
        if caja:
            monto_esperado = await calcular_monto_esperado(ts, caja["id"])
            pagos = await listar_pagos_de_caja(ts, caja["id"])
        ver_todas = user.puede("caja", "diaria", "ver_todas")
        aperturas_recientes = await listar_aperturas(
            ts,
            cajero_user_id=None if ver_todas else user.user_id,
            limit=20,
        )
    return request.app.state.templates.TemplateResponse(
        "tenant/caja/index.html",
        build_context(
            request, user=user,
            caja_abierta=caja, monto_esperado=monto_esperado, pagos=pagos,
            aperturas_recientes=aperturas_recientes, ver_todas=ver_todas,
        ),
    )


@router.get("/abrir", response_class=HTMLResponse)
async def abrir_form(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("caja", "diaria", "abrir"):
        raise HTTPException(403, "Sin permiso")
    async with tenant_session(user.tenant_schema) as ts:
        caja = await caja_abierta_de(ts, user.user_id)
    if caja:
        set_flash(request, "warning", f"Ya tienes la caja #{caja['id']} abierta.")
        return RedirectResponse("/app/caja/", status_code=303)
    return request.app.state.templates.TemplateResponse(
        "tenant/caja/abrir.html",
        build_context(request, user=user),
    )


@router.post("/abrir", dependencies=[Depends(verify_csrf)])
async def abrir_submit(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
    monto_inicial: str = Form("0"),
):
    if not user.puede("caja", "diaria", "abrir"):
        raise HTTPException(403, "Sin permiso")
    try:
        monto = _parse_decimal(monto_inicial)
        async with tenant_session(user.tenant_schema) as ts:
            apertura_id = await abrir_caja(ts, user.user_id, monto)
            await ts.commit()
    except CajaError as exc:
        set_flash(request, "error", str(exc))
        return RedirectResponse("/app/caja/abrir", status_code=303)
    set_flash(request, "success", f"Caja abierta #{apertura_id}.")
    return RedirectResponse("/app/caja/", status_code=303)


@router.get("/cerrar", response_class=HTMLResponse)
async def cerrar_form(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("caja", "diaria", "cerrar"):
        raise HTTPException(403, "Sin permiso")
    async with tenant_session(user.tenant_schema) as ts:
        caja = await caja_abierta_de(ts, user.user_id)
        if not caja:
            set_flash(request, "error", "No tienes caja abierta.")
            return RedirectResponse("/app/caja/", status_code=303)
        monto_esperado = await calcular_monto_esperado(ts, caja["id"])
        pagos = await listar_pagos_de_caja(ts, caja["id"])
    return request.app.state.templates.TemplateResponse(
        "tenant/caja/cerrar.html",
        build_context(
            request, user=user,
            caja=caja, monto_esperado=monto_esperado, pagos=pagos,
        ),
    )


@router.post("/cerrar", dependencies=[Depends(verify_csrf)])
async def cerrar_submit(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
    apertura_id: int = Form(...),
    monto_real_contado: str = Form(...),
    observaciones: str = Form(""),
):
    if not user.puede("caja", "diaria", "cerrar"):
        raise HTTPException(403, "Sin permiso")
    try:
        monto_real = _parse_decimal(monto_real_contado)
        async with tenant_session(user.tenant_schema) as ts:
            result = await cerrar_caja(
                ts, apertura_id, user.user_id, monto_real, observaciones or None
            )
            await ts.commit()
    except CajaError as exc:
        set_flash(request, "error", str(exc))
        return RedirectResponse("/app/caja/cerrar", status_code=303)
    set_flash(
        request, "success",
        f"Caja cerrada. Esperado S/ {result['monto_esperado']}, "
        f"contado S/ {result['monto_real_contado']}, "
        f"diferencia S/ {result['diferencia']}.",
    )
    return RedirectResponse(f"/app/caja/reporte/{apertura_id}", status_code=303)


@router.get("/reporte/{apertura_id}", response_class=HTMLResponse)
async def reporte(
    request: Request,
    apertura_id: int,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("caja", "diaria", "ver_propia"):
        raise HTTPException(403, "Sin permiso")
    async with tenant_session(user.tenant_schema) as ts:
        apertura = await obtener_apertura(ts, apertura_id)
        if not apertura:
            raise HTTPException(404, "Apertura no encontrada")
        if (
            apertura["cajero_user_id"] != user.user_id
            and not user.puede("caja", "diaria", "ver_todas")
        ):
            raise HTTPException(403, "No tienes acceso a este reporte.")
        pagos = await listar_pagos_de_caja(ts, apertura_id)
        if apertura.get("cerrada_at") is None:
            monto_esperado = await calcular_monto_esperado(ts, apertura_id)
        else:
            monto_esperado = apertura.get("monto_esperado")
    return request.app.state.templates.TemplateResponse(
        "tenant/caja/reporte.html",
        build_context(
            request, user=user,
            apertura=apertura, pagos=pagos, monto_esperado=monto_esperado,
        ),
    )
