"""
Caja diaria: apertura, cierre con arqueo, lectura de monto esperado.

Reglas:
- Un cajero solo puede tener UNA caja abierta a la vez (índice único parcial).
- El monto esperado = monto_inicial + suma de pagos en efectivo no anulados
  asociados a esta apertura.
- Cerrar exige monto_real_contado y observaciones (opcional).
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class CajaError(Exception):
    pass


def _to_decimal(v) -> Decimal:
    if v is None:
        return Decimal("0")
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


async def caja_abierta_de(session: AsyncSession, cajero_user_id: int) -> Optional[dict]:
    row = (
        await session.execute(
            text(
                "SELECT id, cajero_user_id, monto_inicial, abierta_at "
                "FROM caja_aperturas "
                "WHERE cajero_user_id = :u AND cerrada_at IS NULL "
                "ORDER BY abierta_at DESC LIMIT 1"
            ),
            {"u": cajero_user_id},
        )
    ).mappings().first()
    return dict(row) if row else None


async def abrir_caja(
    session: AsyncSession, cajero_user_id: int, monto_inicial: Decimal
) -> int:
    if monto_inicial is None or monto_inicial < 0:
        raise CajaError("El monto inicial no puede ser negativo.")
    existente = await caja_abierta_de(session, cajero_user_id)
    if existente:
        raise CajaError(
            f"Ya tienes una caja abierta (apertura #{existente['id']}). "
            "Ciérrala antes de abrir otra."
        )
    row = (
        await session.execute(
            text(
                "INSERT INTO caja_aperturas (cajero_user_id, monto_inicial) "
                "VALUES (:u, :m) RETURNING id"
            ),
            {"u": cajero_user_id, "m": _to_decimal(monto_inicial)},
        )
    ).first()
    return row.id


async def calcular_monto_esperado(session: AsyncSession, apertura_id: int) -> Decimal:
    row = (
        await session.execute(
            text(
                "SELECT monto_inicial FROM caja_aperturas WHERE id = :id"
            ),
            {"id": apertura_id},
        )
    ).first()
    if not row:
        raise CajaError("Caja no encontrada.")
    pagos_row = (
        await session.execute(
            text(
                "SELECT COALESCE(SUM(monto), 0) AS total "
                "FROM pagos "
                "WHERE caja_apertura_id = :a AND anulado = FALSE AND metodo = 'efectivo'"
            ),
            {"a": apertura_id},
        )
    ).first()
    return _to_decimal(row.monto_inicial) + _to_decimal(pagos_row.total)


async def listar_pagos_de_caja(session: AsyncSession, apertura_id: int) -> list[dict]:
    rows = (
        await session.execute(
            text(
                """
                SELECT p.id, p.monto, p.metodo, p.fecha_pago, p.anulado,
                       c.numero_recibo, v.codigo_interno
                FROM pagos p
                JOIN cuotas c ON c.id = p.cuota_id
                JOIN viviendas v ON v.id = c.vivienda_id
                WHERE p.caja_apertura_id = :a
                ORDER BY p.fecha_pago
                """
            ),
            {"a": apertura_id},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def cerrar_caja(
    session: AsyncSession,
    apertura_id: int,
    cajero_user_id: int,
    monto_real_contado: Decimal,
    observaciones: Optional[str],
) -> dict:
    if monto_real_contado is None or monto_real_contado < 0:
        raise CajaError("El monto contado no puede ser negativo.")

    apertura = (
        await session.execute(
            text(
                "SELECT id, cajero_user_id, cerrada_at FROM caja_aperturas "
                "WHERE id = :id FOR UPDATE"
            ),
            {"id": apertura_id},
        )
    ).first()
    if not apertura:
        raise CajaError("Caja no encontrada.")
    if apertura.cerrada_at is not None:
        raise CajaError("La caja ya está cerrada.")
    if apertura.cajero_user_id != cajero_user_id:
        raise CajaError("No puedes cerrar una caja que no abriste.")

    esperado = await calcular_monto_esperado(session, apertura_id)
    real = _to_decimal(monto_real_contado).quantize(Decimal("0.01"))
    diferencia = (real - esperado).quantize(Decimal("0.01"))

    await session.execute(
        text(
            "UPDATE caja_aperturas SET cerrada_at = NOW(), "
            "monto_esperado = :e, monto_real_contado = :r, diferencia = :d, "
            "observaciones_cierre = :obs, cerrada_por_user_id = :u "
            "WHERE id = :id"
        ),
        {
            "e": esperado, "r": real, "d": diferencia,
            "obs": (observaciones or None), "u": cajero_user_id, "id": apertura_id,
        },
    )
    return {
        "apertura_id": apertura_id,
        "monto_esperado": esperado,
        "monto_real_contado": real,
        "diferencia": diferencia,
    }


async def obtener_apertura(session: AsyncSession, apertura_id: int) -> Optional[dict]:
    row = (
        await session.execute(
            text(
                """
                SELECT ca.*, u.nombre_completo AS cajero_nombre
                FROM caja_aperturas ca
                LEFT JOIN usuarios u ON u.id = ca.cajero_user_id
                WHERE ca.id = :id
                """
            ),
            {"id": apertura_id},
        )
    ).mappings().first()
    return dict(row) if row else None


async def listar_aperturas(
    session: AsyncSession, cajero_user_id: Optional[int] = None, limit: int = 50
) -> list[dict]:
    params: dict = {"l": limit}
    where = ""
    if cajero_user_id is not None:
        where = "WHERE ca.cajero_user_id = :u"
        params["u"] = cajero_user_id
    rows = (
        await session.execute(
            text(
                f"""
                SELECT ca.id, ca.cajero_user_id, ca.monto_inicial, ca.abierta_at,
                       ca.cerrada_at, ca.monto_esperado, ca.monto_real_contado,
                       ca.diferencia, u.nombre_completo AS cajero_nombre
                FROM caja_aperturas ca
                LEFT JOIN usuarios u ON u.id = ca.cajero_user_id
                {where}
                ORDER BY ca.abierta_at DESC
                LIMIT :l
                """
            ),
            params,
        )
    ).mappings().all()
    return [dict(r) for r in rows]
