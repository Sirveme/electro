"""Cobranza: buscar vivienda, ver recibos, cobrar."""
import logging
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text

from app.context_processor import build_context
from app.database import tenant_session
from app.dependencies import CurrentUser, require_password_changed
from app.services.caja_service import caja_abierta_de
from app.services.cuota_service import obtener_cuotas_por_vivienda
from app.services.csrf import verify_csrf
from app.services.pago_service import (
    PagoError,
    listar_pagos_de_vivienda,
    registrar_pago,
)
from app.utils.flash import set_flash
from app.utils.periodos import nombre_periodo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/app/cobranza")


def _parse_decimal(raw: str) -> Decimal:
    try:
        return Decimal(str(raw).strip().replace(",", "."))
    except (InvalidOperation, AttributeError, ValueError) as exc:
        raise PagoError(f"Monto inválido: '{raw}'") from exc


async def _vivienda_por_codigo_o_dni(ts, q: str) -> Optional[dict]:
    q = (q or "").strip()
    if not q:
        return None
    # Por código (V-0001)
    row = (
        await ts.execute(
            text(
                """
                SELECT v.id, v.codigo_interno, v.referencia_fisica,
                       com.nombre AS comunidad_nombre,
                       (SELECT m.nombre_completo FROM moradores m
                        WHERE m.vivienda_id = v.id AND m.es_jefe_familia = TRUE
                          AND m.activo = TRUE LIMIT 1) AS jefe_nombre,
                       (SELECT m.dni FROM moradores m
                        WHERE m.vivienda_id = v.id AND m.es_jefe_familia = TRUE
                          AND m.activo = TRUE LIMIT 1) AS jefe_dni
                FROM viviendas v LEFT JOIN comunidades com ON com.id = v.comunidad_id
                WHERE v.codigo_interno = :c AND v.activa = TRUE
                LIMIT 1
                """
            ),
            {"c": q.upper()},
        )
    ).mappings().first()
    if row:
        return dict(row)
    # Por DNI de morador (8 dígitos)
    if q.isdigit() and len(q) == 8:
        row = (
            await ts.execute(
                text(
                    """
                    SELECT v.id, v.codigo_interno, v.referencia_fisica,
                           com.nombre AS comunidad_nombre,
                           m.nombre_completo AS jefe_nombre, m.dni AS jefe_dni
                    FROM moradores m
                    JOIN viviendas v ON v.id = m.vivienda_id
                    LEFT JOIN comunidades com ON com.id = v.comunidad_id
                    WHERE m.dni = :d AND m.activo = TRUE AND v.activa = TRUE
                    ORDER BY m.es_jefe_familia DESC
                    LIMIT 1
                    """
                ),
                {"d": q},
            )
        ).mappings().first()
        if row:
            return dict(row)
    return None


@router.get("/buscar", response_class=HTMLResponse)
async def buscar_form(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
    q: str = "",
):
    if not user.puede("cobranza", "recibos", "ver"):
        raise HTTPException(403, "Sin permiso")
    encontrado = None
    if q:
        async with tenant_session(user.tenant_schema) as ts:
            encontrado = await _vivienda_por_codigo_o_dni(ts, q)
    if encontrado:
        return RedirectResponse(
            f"/app/cobranza/vivienda/{encontrado['codigo_interno']}",
            status_code=303,
        )
    return request.app.state.templates.TemplateResponse(
        "tenant/cobranza/buscar.html",
        build_context(request, user=user, q=q, no_encontrado=bool(q)),
    )


@router.get("/vivienda/{codigo}", response_class=HTMLResponse)
async def vivienda(
    request: Request,
    codigo: str,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("cobranza", "recibos", "ver"):
        raise HTTPException(403, "Sin permiso")
    async with tenant_session(user.tenant_schema) as ts:
        v = await _vivienda_por_codigo_o_dni(ts, codigo)
        if not v:
            raise HTTPException(404, "Vivienda no encontrada")
        cuotas = await obtener_cuotas_por_vivienda(ts, v["id"])
        pagos = await listar_pagos_de_vivienda(ts, v["id"])
        caja = await caja_abierta_de(ts, user.user_id) if user.puede("cobranza", "pagos", "cobrar") else None
    saldo_total = float(
        sum((Decimal(str(c["saldo_pendiente"])) for c in cuotas if c["estado"] != "pagado"),
            Decimal("0"))
    )
    pendientes_count = sum(1 for c in cuotas if c["estado"] in ("pendiente", "parcial"))
    return request.app.state.templates.TemplateResponse(
        "tenant/cobranza/vivienda.html",
        build_context(
            request, user=user, vivienda=v,
            cuotas=cuotas, pagos=pagos, caja_abierta=caja,
            nombre_periodo=nombre_periodo,
            puede_cobrar=user.puede("cobranza", "pagos", "cobrar"),
            saldo_total=saldo_total, pendientes_count=pendientes_count,
        ),
    )


@router.post("/vivienda/{codigo}/cobrar", dependencies=[Depends(verify_csrf)])
async def cobrar(
    request: Request,
    codigo: str,
    user: CurrentUser = Depends(require_password_changed),
    cuota_id: int = Form(...),
    monto: str = Form(...),
    metodo: str = Form("efectivo"),
    referencia_externa: str = Form(""),
    observaciones: str = Form(""),
):
    if not user.puede("cobranza", "pagos", "cobrar"):
        raise HTTPException(403, "Sin permiso")
    try:
        monto_dec = _parse_decimal(monto)
        async with tenant_session(user.tenant_schema) as ts:
            caja = await caja_abierta_de(ts, user.user_id)
            if metodo == "efectivo" and not caja:
                raise PagoError("Debes abrir caja antes de cobrar en efectivo.")
            pago_id = await registrar_pago(
                ts,
                cuota_id=cuota_id,
                monto=monto_dec,
                metodo=metodo,
                user_id=user.user_id,
                caja_apertura_id=caja["id"] if caja else None,
                observaciones=observaciones or None,
                referencia_externa=referencia_externa or None,
            )
            await ts.commit()
    except PagoError as exc:
        set_flash(request, "error", str(exc))
        return RedirectResponse(f"/app/cobranza/vivienda/{codigo}", status_code=303)

    set_flash(
        request, "success",
        f"Pago #{pago_id} registrado por S/ {monto_dec}.",
    )
    return RedirectResponse(
        f"/app/cobranza/vivienda/{codigo}?pago={pago_id}",
        status_code=303,
    )
