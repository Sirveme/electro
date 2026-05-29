"""
Cálculo de cuotas (recibos individuales).

Snapshot completo: cargo fijo, adicional moradores, detalle aparatos con tarifa
en ese instante y subsidio aplicado. Nada de esto se recalcula al pago.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.subsidio_service import obtener_subsidio_para_comunidad
from app.services.tarifa_service import obtener_config_calculo

logger = logging.getLogger(__name__)


class CuotaError(Exception):
    pass


def _to_decimal(v) -> Decimal:
    if v is None:
        return Decimal("0")
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


async def _siguiente_numero_recibo(session: AsyncSession, anio: int) -> str:
    """
    Devuelve el siguiente número del año en formato 0001-{anio}.
    Usa MAX dentro de la misma TX. La unicidad final la garantiza el índice único.
    """
    row = (
        await session.execute(
            text(
                "SELECT MAX(CAST(SPLIT_PART(numero_recibo, '-', 1) AS INTEGER)) AS max_seq "
                "FROM cuotas WHERE numero_recibo LIKE :pat"
            ),
            {"pat": f"%-{anio}"},
        )
    ).first()
    siguiente = (row.max_seq or 0) + 1
    return f"{siguiente:04d}-{anio}"


async def _inventario_con_tarifa(
    session: AsyncSession, vivienda_id: int, fecha: date
) -> list[dict]:
    """
    Inventario vigente a `fecha` con la tarifa snapshot que corresponde
    según artefacto_config (catálogo) o artefacto_propio (propio).
    """
    catalogo_rows = (
        await session.execute(
            text(
                """
                SELECT vi.id, vi.artefacto_origen, vi.artefacto_codigo,
                       vi.artefacto_nombre_snapshot AS nombre, vi.cantidad,
                       COALESCE(cfg.tarifa_mensual, ac.tarifa_sugerida, 0) AS tarifa
                FROM vivienda_inventario vi
                LEFT JOIN public.artefacto_catalogo ac ON ac.codigo = vi.artefacto_codigo
                LEFT JOIN artefacto_config cfg ON cfg.catalogo_id = ac.id
                WHERE vi.vivienda_id = :v
                  AND vi.artefacto_origen = 'catalogo'
                  AND vi.vigente_desde <= :f
                  AND (vi.vigente_hasta IS NULL OR vi.vigente_hasta >= :f)
                """
            ),
            {"v": vivienda_id, "f": fecha},
        )
    ).mappings().all()

    propios_rows = (
        await session.execute(
            text(
                """
                SELECT vi.id, vi.artefacto_origen, vi.artefacto_codigo,
                       vi.artefacto_nombre_snapshot AS nombre, vi.cantidad,
                       COALESCE(ap.tarifa_mensual, 0) AS tarifa
                FROM vivienda_inventario vi
                LEFT JOIN artefacto_propio ap ON ap.codigo = vi.artefacto_codigo
                WHERE vi.vivienda_id = :v
                  AND vi.artefacto_origen = 'propio'
                  AND vi.vigente_desde <= :f
                  AND (vi.vigente_hasta IS NULL OR vi.vigente_hasta >= :f)
                """
            ),
            {"v": vivienda_id, "f": fecha},
        )
    ).mappings().all()

    out: list[dict] = []
    for r in list(catalogo_rows) + list(propios_rows):
        d = dict(r)
        d["importe"] = _to_decimal(d["tarifa"]) * Decimal(d["cantidad"])
        out.append(d)
    out.sort(key=lambda x: (x["artefacto_origen"], x["nombre"]))
    return out


async def calcular_cuota(
    session: AsyncSession,
    vivienda_id: int,
    periodo_anio: int,
    periodo_mes: int,
    fecha_corte: date,
    fecha_emision: date,
    fecha_vencimiento: date,
) -> dict:
    """
    Calcula la cuota (snapshot listo para INSERT en `cuotas`).
    NO inserta ni asigna numero_recibo (eso lo hace el lote_service).
    """
    vivienda = (
        await session.execute(
            text(
                "SELECT v.id, v.codigo_interno, v.comunidad_id, v.estado_servicio, "
                "       COALESCE(v.tiene_subvencion, TRUE) AS tiene_subvencion, "
                "       COALESCE(c.alumbrado_publico_mensual, 0) AS alumbrado_publico_mensual "
                "FROM viviendas v "
                "LEFT JOIN comunidades c ON c.id = v.comunidad_id "
                "WHERE v.id = :id"
            ),
            {"id": vivienda_id},
        )
    ).first()
    if not vivienda:
        raise CuotaError(f"Vivienda {vivienda_id} no existe.")
    if vivienda.estado_servicio != "activo":
        raise CuotaError(
            f"Vivienda {vivienda.codigo_interno} no está activa "
            f"(estado={vivienda.estado_servicio})."
        )

    config = await obtener_config_calculo(session)
    # zClaude-fix-16: el "alumbrado público" (cargo fijo por comunidad) reemplaza
    # al antiguo cargo_fijo_mensual por municipio. Se sigue almacenando en la
    # columna cargo_fijo del snapshot para no romper recibos/PDF existentes.
    cargo_fijo = _to_decimal(vivienda.alumbrado_publico_mensual)
    adicional_por_morador = _to_decimal(config.get("adicional_por_morador", 0))

    n_moradores_row = (
        await session.execute(
            text(
                "SELECT COUNT(*) FROM moradores WHERE vivienda_id = :v AND activo = TRUE"
            ),
            {"v": vivienda_id},
        )
    ).first()
    n_moradores = int(n_moradores_row[0] or 0)

    inventario = await _inventario_con_tarifa(session, vivienda_id, fecha_corte)

    detalle_aparatos = [
        {
            "origen": it["artefacto_origen"],
            "codigo": it["artefacto_codigo"],
            "nombre": it["nombre"],
            "cantidad": int(it["cantidad"]),
            "tarifa": float(_to_decimal(it["tarifa"])),
            "importe": float(it["importe"]),
        }
        for it in inventario
    ]
    monto_aparatos = sum((_to_decimal(it["importe"]) for it in inventario), Decimal("0"))

    adicional_morador_total = adicional_por_morador * Decimal(n_moradores)
    # CONSUMO PRIVADO = adicional por moradores + aparatos. El alumbrado público
    # (cargo_fijo) NO forma parte del consumo y por tanto NO recibe subvención.
    consumo_privado = (adicional_morador_total + monto_aparatos).quantize(Decimal("0.01"))
    subtotal = (cargo_fijo + consumo_privado).quantize(Decimal("0.01"))

    # zClaude-fix-16: la "subvención" reutiliza el subsidio vigente de la
    # comunidad. La vivienda puede excluirse vía tiene_subvencion=FALSE (opt-out).
    # El descuento se aplica SOLO sobre el consumo privado, no sobre el alumbrado.
    tiene_subvencion = bool(vivienda.tiene_subvencion)
    subsidio = None
    if tiene_subvencion:
        subsidio = await obtener_subsidio_para_comunidad(
            session, vivienda.comunidad_id, fecha_corte
        )
    subsidio_monto = Decimal("0")
    subsidio_id: Optional[int] = None
    subsidio_nombre: Optional[str] = None
    subsidio_porcentaje: Optional[Decimal] = None
    subsidio_base_legal: Optional[str] = None
    if subsidio:
        subsidio_id = subsidio["id"]
        subsidio_nombre = subsidio["nombre"]
        subsidio_porcentaje = _to_decimal(subsidio["porcentaje"])
        subsidio_base_legal = subsidio["base_legal"]
        subsidio_monto = (consumo_privado * subsidio_porcentaje / Decimal(100)).quantize(Decimal("0.01"))

    total = (subtotal - subsidio_monto).quantize(Decimal("0.01"))
    if total < Decimal("0"):
        total = Decimal("0.00")

    return {
        "vivienda_id": vivienda_id,
        "periodo_anio": periodo_anio,
        "periodo_mes": periodo_mes,
        "fecha_emision": fecha_emision,
        "fecha_vencimiento": fecha_vencimiento,
        "cargo_fijo": cargo_fijo.quantize(Decimal("0.01")),
        "adicional_morador": adicional_morador_total.quantize(Decimal("0.01")),
        "n_moradores": n_moradores,
        "detalle_aparatos_json": detalle_aparatos,
        "monto_aparatos": monto_aparatos.quantize(Decimal("0.01")),
        "subtotal": subtotal,
        "subsidio_id": subsidio_id,
        "subsidio_nombre": subsidio_nombre,
        "subsidio_porcentaje": subsidio_porcentaje,
        "subsidio_base_legal": subsidio_base_legal,
        "subsidio_monto": subsidio_monto,
        "total": total,
        "monto_pagado": Decimal("0"),
        "saldo_pendiente": total,
        "estado": "pagado" if total == Decimal("0.00") else "pendiente",
    }


async def insertar_cuota(
    session: AsyncSession,
    lote_id: int,
    numero_recibo: str,
    snapshot: dict,
) -> int:
    detalle_json = json.dumps(snapshot.get("detalle_aparatos_json") or [])
    row = (
        await session.execute(
            text(
                """
                INSERT INTO cuotas (
                    lote_id, numero_recibo, vivienda_id,
                    periodo_anio, periodo_mes, fecha_emision, fecha_vencimiento,
                    cargo_fijo, adicional_morador, n_moradores,
                    detalle_aparatos_json, monto_aparatos, subtotal,
                    subsidio_id, subsidio_nombre, subsidio_porcentaje, subsidio_base_legal, subsidio_monto,
                    total, monto_pagado, saldo_pendiente, estado
                ) VALUES (
                    :lote_id, :numero_recibo, :vivienda_id,
                    :periodo_anio, :periodo_mes, :fecha_emision, :fecha_vencimiento,
                    :cargo_fijo, :adicional_morador, :n_moradores,
                    CAST(:detalle_json AS JSONB), :monto_aparatos, :subtotal,
                    :subsidio_id, :subsidio_nombre, :subsidio_porcentaje, :subsidio_base_legal, :subsidio_monto,
                    :total, :monto_pagado, :saldo_pendiente, :estado
                )
                RETURNING id
                """
            ),
            {
                "lote_id": lote_id,
                "numero_recibo": numero_recibo,
                "vivienda_id": snapshot["vivienda_id"],
                "periodo_anio": snapshot["periodo_anio"],
                "periodo_mes": snapshot["periodo_mes"],
                "fecha_emision": snapshot["fecha_emision"],
                "fecha_vencimiento": snapshot["fecha_vencimiento"],
                "cargo_fijo": snapshot["cargo_fijo"],
                "adicional_morador": snapshot["adicional_morador"],
                "n_moradores": snapshot["n_moradores"],
                "detalle_json": detalle_json,
                "monto_aparatos": snapshot["monto_aparatos"],
                "subtotal": snapshot["subtotal"],
                "subsidio_id": snapshot["subsidio_id"],
                "subsidio_nombre": snapshot["subsidio_nombre"],
                "subsidio_porcentaje": snapshot["subsidio_porcentaje"],
                "subsidio_base_legal": snapshot["subsidio_base_legal"],
                "subsidio_monto": snapshot["subsidio_monto"],
                "total": snapshot["total"],
                "monto_pagado": snapshot["monto_pagado"],
                "saldo_pendiente": snapshot["saldo_pendiente"],
                "estado": snapshot["estado"],
            },
        )
    ).first()
    return row.id


async def obtener_cuotas_por_vivienda(
    session: AsyncSession, vivienda_id: int, solo_pendientes: bool = False
) -> list[dict]:
    where_extra = "AND c.estado != 'pagado'" if solo_pendientes else ""
    rows = (
        await session.execute(
            text(
                f"""
                SELECT c.id, c.numero_recibo, c.periodo_anio, c.periodo_mes,
                       c.fecha_emision, c.fecha_vencimiento,
                       c.subtotal, c.subsidio_monto, c.total,
                       c.monto_pagado, c.saldo_pendiente, c.estado
                FROM cuotas c
                WHERE c.vivienda_id = :v {where_extra}
                ORDER BY c.periodo_anio DESC, c.periodo_mes DESC
                """
            ),
            {"v": vivienda_id},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def obtener_cuota_completa(session: AsyncSession, cuota_id: int) -> Optional[dict]:
    row = (
        await session.execute(
            text(
                """
                SELECT c.*, v.codigo_interno, com.nombre AS comunidad_nombre,
                       v.referencia_fisica, v.direccion_textual
                FROM cuotas c
                JOIN viviendas v ON v.id = c.vivienda_id
                LEFT JOIN comunidades com ON com.id = v.comunidad_id
                WHERE c.id = :id
                """
            ),
            {"id": cuota_id},
        )
    ).mappings().first()
    if not row:
        return None
    d = dict(row)
    # detalle_aparatos_json llega como list/dict ya parseado por asyncpg
    if isinstance(d.get("detalle_aparatos_json"), str):
        try:
            d["detalle_aparatos_json"] = json.loads(d["detalle_aparatos_json"])
        except (json.JSONDecodeError, TypeError):
            d["detalle_aparatos_json"] = []
    return d


# Reexport para retro-compatibilidad
__all__ = [
    "CuotaError",
    "calcular_cuota",
    "insertar_cuota",
    "obtener_cuotas_por_vivienda",
    "obtener_cuota_completa",
    "_siguiente_numero_recibo",
]
