"""
Subsidios del municipio.

Reglas:
- Un subsidio tiene N comunidades cubiertas.
- En una comunidad solo un subsidio puede estar vigente a la vez.
- Crear un subsidio nuevo SUSPENDE automáticamente el vigente en cada
  comunidad cubierta (setea vigente_hasta = vigente_desde - 1 día).
- Suspender = setear vigente_hasta = HOY.
- Snapshot: los recibos ya emitidos NO se tocan.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class SubsidioError(Exception):
    pass


async def listar_subsidios(session: AsyncSession, solo_vigentes: bool = False) -> list[dict]:
    """Lista subsidios con sus comunidades cubiertas."""
    where = ""
    if solo_vigentes:
        where = (
            "WHERE s.vigente_desde <= CURRENT_DATE "
            "  AND (s.vigente_hasta IS NULL OR s.vigente_hasta >= CURRENT_DATE)"
        )
    rows = (
        await session.execute(
            text(
                f"""
                SELECT s.id, s.nombre, s.porcentaje, s.base_legal,
                       s.vigente_desde, s.vigente_hasta, s.observaciones,
                       s.motivo_suspension, s.created_at,
                       COALESCE(array_agg(c.id) FILTER (WHERE c.id IS NOT NULL), '{{}}') AS comunidad_ids,
                       COALESCE(array_agg(c.nombre) FILTER (WHERE c.id IS NOT NULL), '{{}}') AS comunidad_nombres
                FROM subsidios s
                LEFT JOIN subsidio_comunidades sc ON sc.subsidio_id = s.id
                LEFT JOIN comunidades c ON c.id = sc.comunidad_id
                {where}
                GROUP BY s.id
                ORDER BY s.vigente_desde DESC, s.id DESC
                """
            )
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def obtener_subsidio(session: AsyncSession, subsidio_id: int) -> Optional[dict]:
    row = (
        await session.execute(
            text(
                """
                SELECT s.id, s.nombre, s.porcentaje, s.base_legal,
                       s.vigente_desde, s.vigente_hasta, s.observaciones,
                       s.creado_por_user_id, s.suspendido_por_user_id,
                       s.motivo_suspension, s.created_at,
                       COALESCE(array_agg(c.id) FILTER (WHERE c.id IS NOT NULL), '{}') AS comunidad_ids,
                       COALESCE(array_agg(c.nombre) FILTER (WHERE c.id IS NOT NULL), '{}') AS comunidad_nombres
                FROM subsidios s
                LEFT JOIN subsidio_comunidades sc ON sc.subsidio_id = s.id
                LEFT JOIN comunidades c ON c.id = sc.comunidad_id
                WHERE s.id = :id
                GROUP BY s.id
                """
            ),
            {"id": subsidio_id},
        )
    ).mappings().first()
    return dict(row) if row else None


async def crear_subsidio(
    session: AsyncSession,
    nombre: str,
    porcentaje: Decimal,
    base_legal: str,
    vigente_desde: date,
    observaciones: Optional[str],
    comunidad_ids: Iterable[int],
    user_id: int,
) -> int:
    nombre = (nombre or "").strip()
    base_legal = (base_legal or "").strip()
    if not nombre:
        raise SubsidioError("El nombre del subsidio es obligatorio.")
    if not base_legal:
        raise SubsidioError("La base legal (Ordenanza N°...) es obligatoria.")
    if porcentaje is None or porcentaje < 0 or porcentaje > 100:
        raise SubsidioError("El porcentaje debe estar entre 0 y 100.")
    ids = [int(c) for c in comunidad_ids if c]
    if not ids:
        raise SubsidioError("Debe seleccionar al menos una comunidad cubierta.")

    # Suspender el subsidio vigente en cada comunidad seleccionada (si existe).
    hasta = vigente_desde - timedelta(days=1)
    await session.execute(
        text(
            """
            UPDATE subsidios SET vigente_hasta = :h
            WHERE id IN (
                SELECT DISTINCT s.id
                FROM subsidios s
                JOIN subsidio_comunidades sc ON sc.subsidio_id = s.id
                WHERE sc.comunidad_id = ANY(:cids)
                  AND s.vigente_desde <= :vd
                  AND (s.vigente_hasta IS NULL OR s.vigente_hasta >= :vd)
            )
            """
        ),
        {"h": hasta, "cids": ids, "vd": vigente_desde},
    )

    row = (
        await session.execute(
            text(
                """
                INSERT INTO subsidios
                    (nombre, porcentaje, base_legal, vigente_desde, observaciones, creado_por_user_id)
                VALUES (:n, :p, :bl, :vd, :obs, :u)
                RETURNING id
                """
            ),
            {
                "n": nombre, "p": porcentaje, "bl": base_legal,
                "vd": vigente_desde, "obs": (observaciones or None), "u": user_id,
            },
        )
    ).first()
    subsidio_id = row.id

    for cid in ids:
        await session.execute(
            text(
                "INSERT INTO subsidio_comunidades (subsidio_id, comunidad_id) "
                "VALUES (:s, :c) ON CONFLICT DO NOTHING"
            ),
            {"s": subsidio_id, "c": cid},
        )
    return subsidio_id


async def suspender_subsidio(
    session: AsyncSession, subsidio_id: int, motivo: str, user_id: int
) -> None:
    motivo = (motivo or "").strip()
    if not motivo:
        raise SubsidioError("El motivo de suspensión es obligatorio.")
    row = (
        await session.execute(
            text("SELECT id, vigente_hasta FROM subsidios WHERE id = :id"),
            {"id": subsidio_id},
        )
    ).first()
    if not row:
        raise SubsidioError("Subsidio no encontrado.")
    if row.vigente_hasta is not None and row.vigente_hasta < date.today():
        raise SubsidioError("El subsidio ya no está vigente.")
    await session.execute(
        text(
            "UPDATE subsidios SET vigente_hasta = CURRENT_DATE, "
            "motivo_suspension = :m, suspendido_por_user_id = :u "
            "WHERE id = :id"
        ),
        {"m": motivo, "u": user_id, "id": subsidio_id},
    )


async def obtener_subsidio_para_comunidad(
    session: AsyncSession, comunidad_id: int, fecha_ref: date
) -> Optional[dict]:
    """Retorna el subsidio vigente para una comunidad en una fecha dada (o None)."""
    row = (
        await session.execute(
            text(
                """
                SELECT s.id, s.nombre, s.porcentaje, s.base_legal
                FROM subsidios s
                JOIN subsidio_comunidades sc ON sc.subsidio_id = s.id
                WHERE sc.comunidad_id = :c
                  AND s.vigente_desde <= :f
                  AND (s.vigente_hasta IS NULL OR s.vigente_hasta >= :f)
                ORDER BY s.vigente_desde DESC
                LIMIT 1
                """
            ),
            {"c": comunidad_id, "f": fecha_ref},
        )
    ).mappings().first()
    return dict(row) if row else None
