"""
Generación de lotes mensuales de facturación.

Reglas:
- Solo un lote ACTIVO por periodo (índice único parcial lo garantiza).
- Recorre todas las viviendas activas y crea cuotas con snapshot completo.
- Errores individuales NO abortan el lote: se anotan en observaciones.
- Anular un lote: prohibido si tiene pagos asociados.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.cuota_service import (
    CuotaError,
    _siguiente_numero_recibo,
    calcular_cuota,
    insertar_cuota,
)
from app.utils.periodos import ultimo_dia_del_mes, vencimiento_por_periodo

logger = logging.getLogger(__name__)


class LoteError(Exception):
    pass


async def existe_lote_activo(session: AsyncSession, anio: int, mes: int) -> Optional[int]:
    row = (
        await session.execute(
            text(
                "SELECT id FROM lotes_facturacion "
                "WHERE periodo_anio = :a AND periodo_mes = :m AND estado = 'activo'"
            ),
            {"a": anio, "m": mes},
        )
    ).first()
    return row.id if row else None


async def listar_lotes(session: AsyncSession, limit: int = 50) -> list[dict]:
    rows = (
        await session.execute(
            text(
                """
                SELECT id, periodo_anio, periodo_mes, fecha_emision, fecha_vencimiento,
                       estado, total_viviendas, total_recibos_generados, total_recibos_fallidos,
                       monto_total_emitido, monto_total_subsidiado, generado_por_user_id,
                       anulado_por_user_id, motivo_anulacion, created_at
                FROM lotes_facturacion
                ORDER BY periodo_anio DESC, periodo_mes DESC, id DESC
                LIMIT :l
                """
            ),
            {"l": limit},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def obtener_lote(session: AsyncSession, lote_id: int) -> Optional[dict]:
    row = (
        await session.execute(
            text(
                "SELECT * FROM lotes_facturacion WHERE id = :id"
            ),
            {"id": lote_id},
        )
    ).mappings().first()
    return dict(row) if row else None


async def listar_cuotas_del_lote(session: AsyncSession, lote_id: int) -> list[dict]:
    rows = (
        await session.execute(
            text(
                """
                SELECT c.id, c.numero_recibo, c.vivienda_id,
                       v.codigo_interno, com.nombre AS comunidad_nombre,
                       c.subtotal, c.subsidio_monto, c.total,
                       c.monto_pagado, c.saldo_pendiente, c.estado
                FROM cuotas c
                JOIN viviendas v ON v.id = c.vivienda_id
                LEFT JOIN comunidades com ON com.id = v.comunidad_id
                WHERE c.lote_id = :l
                ORDER BY c.numero_recibo
                """
            ),
            {"l": lote_id},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def generar_lote_mensual(
    session: AsyncSession,
    periodo_anio: int,
    periodo_mes: int,
    fecha_emision: date,
    fecha_vencimiento: date,
    user_id: int,
) -> dict:
    """
    Genera el lote. Retorna {lote_id, total_viviendas, ok, fail, errores}.
    Es responsabilidad del caller hacer commit final.
    """
    existente = await existe_lote_activo(session, periodo_anio, periodo_mes)
    if existente:
        raise LoteError(
            f"Ya existe un lote activo para {periodo_mes}/{periodo_anio} (id={existente})."
        )

    fecha_corte = ultimo_dia_del_mes(periodo_anio, periodo_mes)

    lote_row = (
        await session.execute(
            text(
                """
                INSERT INTO lotes_facturacion
                    (periodo_anio, periodo_mes, fecha_emision, fecha_vencimiento,
                     estado, generado_por_user_id)
                VALUES (:a, :m, :fe, :fv, 'generando', :u)
                RETURNING id
                """
            ),
            {"a": periodo_anio, "m": periodo_mes,
             "fe": fecha_emision, "fv": fecha_vencimiento, "u": user_id},
        )
    ).first()
    lote_id = lote_row.id

    viviendas = (
        await session.execute(
            text(
                "SELECT id, codigo_interno FROM viviendas "
                "WHERE activa = TRUE AND estado_servicio = 'activo' ORDER BY id"
            )
        )
    ).all()

    total = len(viviendas)
    ok = 0
    fail = 0
    monto_emitido = Decimal("0")
    monto_subsidiado = Decimal("0")
    errores: list[str] = []

    for v in viviendas:
        try:
            snap = await calcular_cuota(
                session,
                vivienda_id=v.id,
                periodo_anio=periodo_anio,
                periodo_mes=periodo_mes,
                fecha_corte=fecha_corte,
                fecha_emision=fecha_emision,
                fecha_vencimiento=fecha_vencimiento,
            )
            numero = await _siguiente_numero_recibo(session, periodo_anio)
            await insertar_cuota(session, lote_id, numero, snap)
            ok += 1
            monto_emitido += snap["total"]
            monto_subsidiado += snap["subsidio_monto"]
        except CuotaError as exc:
            fail += 1
            msg = f"{v.codigo_interno}: {exc}"
            errores.append(msg)
            logger.warning("Lote %s — error vivienda %s: %s", lote_id, v.codigo_interno, exc)
        except Exception as exc:  # noqa: BLE001
            fail += 1
            msg = f"{v.codigo_interno}: error inesperado: {exc}"
            errores.append(msg)
            logger.exception("Lote %s — error inesperado vivienda %s", lote_id, v.codigo_interno)

    observaciones = None
    if errores:
        observaciones = "Errores individuales:\n" + "\n".join(errores[:50])
        if len(errores) > 50:
            observaciones += f"\n... y {len(errores) - 50} más."

    await session.execute(
        text(
            """
            UPDATE lotes_facturacion
            SET estado = 'activo',
                total_viviendas = :tv,
                total_recibos_generados = :ok,
                total_recibos_fallidos = :fail,
                monto_total_emitido = :emit,
                monto_total_subsidiado = :sub,
                observaciones = :obs
            WHERE id = :id
            """
        ),
        {
            "id": lote_id, "tv": total, "ok": ok, "fail": fail,
            "emit": monto_emitido, "sub": monto_subsidiado, "obs": observaciones,
        },
    )

    return {
        "lote_id": lote_id,
        "total_viviendas": total,
        "ok": ok,
        "fail": fail,
        "monto_total_emitido": monto_emitido,
        "monto_total_subsidiado": monto_subsidiado,
        "errores": errores,
    }


async def anular_lote(
    session: AsyncSession, lote_id: int, motivo: str, user_id: int
) -> None:
    """Anula un lote — prohibido si tiene pagos asociados."""
    motivo = (motivo or "").strip()
    if not motivo:
        raise LoteError("El motivo de anulación es obligatorio.")
    lote = (
        await session.execute(
            text("SELECT id, estado FROM lotes_facturacion WHERE id = :id FOR UPDATE"),
            {"id": lote_id},
        )
    ).first()
    if not lote:
        raise LoteError("Lote no encontrado.")
    if lote.estado != "activo":
        raise LoteError(f"El lote no está activo (estado={lote.estado}).")

    pagos_row = (
        await session.execute(
            text(
                "SELECT COUNT(*) FROM pagos p "
                "JOIN cuotas c ON c.id = p.cuota_id "
                "WHERE c.lote_id = :l AND p.anulado = FALSE"
            ),
            {"l": lote_id},
        )
    ).first()
    if int(pagos_row[0] or 0) > 0:
        raise LoteError(
            "No se puede anular: el lote tiene pagos asociados. "
            "Anule primero los pagos."
        )

    await session.execute(
        text("UPDATE cuotas SET estado = 'anulada' WHERE lote_id = :l"),
        {"l": lote_id},
    )
    await session.execute(
        text(
            "UPDATE lotes_facturacion "
            "SET estado = 'anulado', motivo_anulacion = :m, anulado_por_user_id = :u "
            "WHERE id = :id"
        ),
        {"m": motivo, "u": user_id, "id": lote_id},
    )
