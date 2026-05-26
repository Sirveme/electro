"""
Registro y consulta de pagos. Valida sobrepago, exige caja abierta para
método efectivo y actualiza estado de la cuota.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class PagoError(Exception):
    pass


def _to_decimal(v) -> Decimal:
    if v is None:
        return Decimal("0")
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


async def registrar_pago(
    session: AsyncSession,
    cuota_id: int,
    monto: Decimal,
    metodo: str,
    user_id: int,
    caja_apertura_id: Optional[int],
    observaciones: Optional[str] = None,
    referencia_externa: Optional[str] = None,
) -> int:
    if monto is None or monto <= 0:
        raise PagoError("El monto debe ser mayor a 0.")
    metodo = (metodo or "efectivo").strip().lower()
    if metodo not in ("efectivo", "yape", "plin"):
        raise PagoError(f"Método de pago no soportado: {metodo}")

    if metodo == "efectivo" and not caja_apertura_id:
        raise PagoError("Para cobrar en efectivo necesitas una caja abierta.")

    cuota = (
        await session.execute(
            text(
                "SELECT id, total, monto_pagado, saldo_pendiente, estado "
                "FROM cuotas WHERE id = :id FOR UPDATE"
            ),
            {"id": cuota_id},
        )
    ).first()
    if not cuota:
        raise PagoError("Recibo no encontrado.")
    if cuota.estado == "anulada":
        raise PagoError("El recibo está anulado.")
    if cuota.estado == "pagado":
        raise PagoError("Este recibo ya está completamente pagado.")

    saldo = _to_decimal(cuota.saldo_pendiente)
    monto_dec = _to_decimal(monto).quantize(Decimal("0.01"))
    if monto_dec > saldo:
        raise PagoError(
            f"Sobrepago no permitido: monto S/ {monto_dec} > saldo S/ {saldo}."
        )

    if caja_apertura_id:
        caja = (
            await session.execute(
                text(
                    "SELECT id, cajero_user_id, cerrada_at "
                    "FROM caja_aperturas WHERE id = :id"
                ),
                {"id": caja_apertura_id},
            )
        ).first()
        if not caja:
            raise PagoError("Caja no encontrada.")
        if caja.cerrada_at is not None:
            raise PagoError("La caja ya fue cerrada.")
        if caja.cajero_user_id != user_id:
            raise PagoError("Esta caja no pertenece al cajero actual.")

    pago_row = (
        await session.execute(
            text(
                """
                INSERT INTO pagos
                    (cuota_id, monto, metodo, referencia_externa,
                     caja_apertura_id, cobrado_por_user_id, observaciones)
                VALUES (:c, :m, :met, :ref, :caja, :u, :obs)
                RETURNING id
                """
            ),
            {
                "c": cuota_id, "m": monto_dec, "met": metodo,
                "ref": (referencia_externa or None),
                "caja": caja_apertura_id, "u": user_id,
                "obs": (observaciones or None),
            },
        )
    ).first()
    pago_id = pago_row.id

    nuevo_pagado = _to_decimal(cuota.monto_pagado) + monto_dec
    nuevo_saldo = saldo - monto_dec
    nuevo_estado = "pagado" if nuevo_saldo <= Decimal("0") else "parcial"
    await session.execute(
        text(
            "UPDATE cuotas SET monto_pagado = :mp, saldo_pendiente = :sp, "
            "estado = :st WHERE id = :id"
        ),
        {"mp": nuevo_pagado, "sp": nuevo_saldo, "st": nuevo_estado, "id": cuota_id},
    )
    return pago_id


async def obtener_pago_completo(session: AsyncSession, pago_id: int) -> Optional[dict]:
    row = (
        await session.execute(
            text(
                """
                SELECT p.id, p.cuota_id, p.monto, p.metodo, p.referencia_externa,
                       p.caja_apertura_id, p.cobrado_por_user_id, p.fecha_pago,
                       p.observaciones, p.anulado,
                       u.nombre_completo AS cajero_nombre,
                       c.numero_recibo, c.total, c.monto_pagado, c.saldo_pendiente,
                       c.periodo_anio, c.periodo_mes,
                       v.codigo_interno, com.nombre AS comunidad_nombre,
                       v.referencia_fisica
                FROM pagos p
                JOIN cuotas c ON c.id = p.cuota_id
                JOIN viviendas v ON v.id = c.vivienda_id
                LEFT JOIN comunidades com ON com.id = v.comunidad_id
                LEFT JOIN usuarios u ON u.id = p.cobrado_por_user_id
                WHERE p.id = :id
                """
            ),
            {"id": pago_id},
        )
    ).mappings().first()
    return dict(row) if row else None


async def listar_pagos_de_vivienda(
    session: AsyncSession, vivienda_id: int, limit: int = 20
) -> list[dict]:
    rows = (
        await session.execute(
            text(
                """
                SELECT p.id, p.monto, p.metodo, p.fecha_pago, p.anulado,
                       c.numero_recibo, c.periodo_anio, c.periodo_mes,
                       u.nombre_completo AS cajero_nombre
                FROM pagos p
                JOIN cuotas c ON c.id = p.cuota_id
                LEFT JOIN usuarios u ON u.id = p.cobrado_por_user_id
                WHERE c.vivienda_id = :v
                ORDER BY p.fecha_pago DESC
                LIMIT :l
                """
            ),
            {"v": vivienda_id, "l": limit},
        )
    ).mappings().all()
    return [dict(r) for r in rows]
