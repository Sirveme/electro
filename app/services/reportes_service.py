"""
Consultas para reportes y dashboards.

TODAS las funciones son READ-ONLY y retornan estructura uniforme:
    {
      headers:     list[str],
      rows:        list[dict],
      totales:     dict,       # opcional (totales de monto, etc.)
      params:      dict,       # parámetros usados (para mostrar y exportar)
      generado_at: datetime,
    }

Dashboard del alcalde retorna una estructura distinta (kpis + secciones).
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.timezone import now_lima

logger = logging.getLogger(__name__)


# ============ 1. PADRÓN GLOBAL ============

async def reporte_padron_global(
    session: AsyncSession,
    comunidad_id: Optional[int] = None,
    estado: Optional[str] = None,
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
) -> dict:
    """Listado completo de viviendas activas con filtros opcionales."""
    where = ["v.activa = TRUE"]
    params: dict = {}
    if comunidad_id:
        where.append("v.comunidad_id = :comunidad")
        params["comunidad"] = comunidad_id
    if estado:
        where.append("v.estado_servicio = :estado")
        params["estado"] = estado
    if fecha_desde:
        where.append("v.empadronada_at >= :fdesde")
        params["fdesde"] = fecha_desde
    if fecha_hasta:
        where.append("v.empadronada_at <= :fhasta")
        params["fhasta"] = fecha_hasta

    sql = f"""
        SELECT
          v.codigo_interno,
          c.nombre AS comunidad,
          v.estado_servicio,
          v.referencia_fisica,
          v.modo_calculo,
          (SELECT m.nombre_completo FROM moradores m
             WHERE m.vivienda_id = v.id AND m.es_jefe_familia AND m.activo LIMIT 1) AS jefe,
          (SELECT m.dni FROM moradores m
             WHERE m.vivienda_id = v.id AND m.es_jefe_familia AND m.activo LIMIT 1) AS dni_jefe,
          (SELECT COUNT(*) FROM moradores m
             WHERE m.vivienda_id = v.id AND m.activo) AS n_moradores,
          (SELECT COUNT(*) FROM vivienda_inventario vi
             WHERE vi.vivienda_id = v.id AND vi.vigente_hasta IS NULL) AS n_artefactos,
          v.empadronada_at::date AS fecha_empadronamiento
        FROM viviendas v
        LEFT JOIN comunidades c ON c.id = v.comunidad_id
        WHERE {' AND '.join(where)}
        ORDER BY v.empadronada_at DESC
    """
    rows = (await session.execute(text(sql), params)).mappings().all()
    rows = [dict(r) for r in rows]

    return {
        "headers": ["Código", "Comunidad", "Estado", "Referencia", "Modo",
                    "Jefe de familia", "DNI jefe", "# Moradores", "# Artefactos", "Empadronada"],
        "rows": rows,
        "totales": {"total_viviendas": len(rows)},
        "params": {
            "comunidad_id": comunidad_id, "estado": estado,
            "fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta,
        },
        "generado_at": now_lima(),
    }


# ============ 2. RECAUDACIÓN MENSUAL ============

async def reporte_recaudacion_mensual(
    session: AsyncSession,
    anio: int,
    mes: int,
) -> dict:
    """
    Cuánto se generó (emitido) y cuánto se cobró en un periodo.
    Desglosa por comunidad y por estado.
    """
    sql_resumen = """
        SELECT
          COUNT(*) AS n_recibos,
          COALESCE(SUM(total), 0) AS monto_emitido,
          COALESCE(SUM(monto_pagado), 0) AS monto_cobrado,
          COALESCE(SUM(saldo_pendiente), 0) AS monto_saldo,
          COALESCE(SUM(subsidio_monto), 0) AS monto_subsidiado,
          COUNT(*) FILTER (WHERE estado = 'pagado') AS n_pagados,
          COUNT(*) FILTER (WHERE estado = 'parcial') AS n_parciales,
          COUNT(*) FILTER (WHERE estado = 'pendiente') AS n_pendientes
        FROM cuotas
        WHERE periodo_anio = :a AND periodo_mes = :m
    """
    resumen = (await session.execute(
        text(sql_resumen), {"a": anio, "m": mes}
    )).mappings().first()
    resumen = dict(resumen) if resumen else {}

    sql_por_comunidad = """
        SELECT
          c.nombre AS comunidad,
          COUNT(*) AS n_recibos,
          COALESCE(SUM(cu.total), 0) AS monto_emitido,
          COALESCE(SUM(cu.monto_pagado), 0) AS monto_cobrado,
          COALESCE(SUM(cu.saldo_pendiente), 0) AS monto_saldo,
          CASE WHEN SUM(cu.total) > 0
               THEN ROUND(SUM(cu.monto_pagado) * 100.0 / SUM(cu.total), 1)
               ELSE 0 END AS pct_cobrado
        FROM cuotas cu
        JOIN viviendas v   ON v.id = cu.vivienda_id
        JOIN comunidades c ON c.id = v.comunidad_id
        WHERE cu.periodo_anio = :a AND cu.periodo_mes = :m
        GROUP BY c.nombre
        ORDER BY c.nombre
    """
    por_comunidad = (await session.execute(
        text(sql_por_comunidad), {"a": anio, "m": mes}
    )).mappings().all()
    por_comunidad = [dict(r) for r in por_comunidad]

    return {
        "headers": ["Comunidad", "# Recibos", "Emitido (S/.)", "Cobrado (S/.)", "Saldo (S/.)", "% Cobrado"],
        "rows": por_comunidad,
        "totales": resumen,
        "params": {"anio": anio, "mes": mes},
        "generado_at": now_lima(),
    }


# ============ 3. COBRANZA PENDIENTE (CON AGING) ============

async def reporte_cobranza_pendiente(
    session: AsyncSession,
    comunidad_id: Optional[int] = None,
) -> dict:
    """
    Lista de recibos con saldo pendiente, con antigüedad (aging) en buckets:
      al_dia, 0-30 días, 31-60 días, 61-90 días, 90+ días.
    """
    where = ["cu.saldo_pendiente > 0", "cu.estado IN ('pendiente','parcial')"]
    params: dict = {}
    if comunidad_id:
        where.append("v.comunidad_id = :comunidad")
        params["comunidad"] = comunidad_id

    sql = f"""
        SELECT
          cu.numero_recibo,
          v.codigo_interno,
          c.nombre AS comunidad,
          (SELECT m.nombre_completo FROM moradores m
             WHERE m.vivienda_id = v.id AND m.es_responsable_pago AND m.activo LIMIT 1) AS responsable_pago,
          (SELECT m.dni FROM moradores m
             WHERE m.vivienda_id = v.id AND m.es_responsable_pago AND m.activo LIMIT 1) AS dni_responsable,
          (SELECT m.telefono FROM moradores m
             WHERE m.vivienda_id = v.id AND m.es_responsable_pago AND m.activo LIMIT 1) AS telefono,
          cu.periodo_anio,
          cu.periodo_mes,
          cu.fecha_emision,
          cu.fecha_vencimiento,
          cu.total,
          cu.monto_pagado,
          cu.saldo_pendiente,
          (CURRENT_DATE - cu.fecha_vencimiento) AS dias_atraso,
          CASE
            WHEN (CURRENT_DATE - cu.fecha_vencimiento) <= 0  THEN 'al_dia'
            WHEN (CURRENT_DATE - cu.fecha_vencimiento) <= 30 THEN '0-30 días'
            WHEN (CURRENT_DATE - cu.fecha_vencimiento) <= 60 THEN '31-60 días'
            WHEN (CURRENT_DATE - cu.fecha_vencimiento) <= 90 THEN '61-90 días'
            ELSE '90+ días'
          END AS aging_bucket
        FROM cuotas cu
        JOIN viviendas v   ON v.id = cu.vivienda_id
        LEFT JOIN comunidades c ON c.id = v.comunidad_id
        WHERE {' AND '.join(where)}
        ORDER BY cu.fecha_vencimiento ASC, cu.numero_recibo
    """
    rows = (await session.execute(text(sql), params)).mappings().all()
    rows = [dict(r) for r in rows]

    sql_buckets = f"""
        SELECT
          CASE
            WHEN (CURRENT_DATE - cu.fecha_vencimiento) <= 0  THEN 'al_dia'
            WHEN (CURRENT_DATE - cu.fecha_vencimiento) <= 30 THEN '0-30 días'
            WHEN (CURRENT_DATE - cu.fecha_vencimiento) <= 60 THEN '31-60 días'
            WHEN (CURRENT_DATE - cu.fecha_vencimiento) <= 90 THEN '61-90 días'
            ELSE '90+ días'
          END AS bucket,
          COUNT(*) AS n,
          SUM(cu.saldo_pendiente) AS monto
        FROM cuotas cu
        JOIN viviendas v ON v.id = cu.vivienda_id
        WHERE {' AND '.join(where)}
        GROUP BY bucket
        ORDER BY bucket
    """
    buckets = (await session.execute(text(sql_buckets), params)).mappings().all()
    buckets = [dict(b) for b in buckets]

    total_saldo = sum((r["saldo_pendiente"] or Decimal("0")) for r in rows) if rows else Decimal("0")
    totales = {
        "total_recibos": len(rows),
        "total_saldo": total_saldo,
        "buckets": buckets,
    }

    return {
        "headers": ["N° Recibo", "Vivienda", "Comunidad", "Responsable", "DNI", "Teléfono",
                    "Año", "Mes", "Emisión", "Vencimiento", "Total", "Pagado", "Saldo",
                    "Atraso (días)", "Antigüedad"],
        "rows": rows,
        "totales": totales,
        "params": {"comunidad_id": comunidad_id},
        "generado_at": now_lima(),
    }


# ============ 4. INVENTARIO CONSOLIDADO ============

async def reporte_inventario_consolidado(
    session: AsyncSession,
    comunidad_id: Optional[int] = None,
    fecha_corte: Optional[date] = None,
) -> dict:
    """
    Cuántos artefactos hay en total, agrupado por artefacto y comunidad.
    Si fecha_corte es None, usa HOY.
    """
    fecha = fecha_corte or date.today()
    where = [
        "vi.vigente_desde <= :f",
        "(vi.vigente_hasta IS NULL OR vi.vigente_hasta >= :f)",
        "v.activa = TRUE",
    ]
    params: dict = {"f": fecha}
    if comunidad_id:
        where.append("v.comunidad_id = :comunidad")
        params["comunidad"] = comunidad_id

    sql = f"""
        SELECT
          vi.artefacto_nombre_snapshot AS artefacto,
          vi.artefacto_origen,
          vi.artefacto_codigo,
          c.nombre AS comunidad,
          SUM(vi.cantidad)::INT AS cantidad_total,
          COUNT(DISTINCT vi.vivienda_id)::INT AS n_viviendas
        FROM vivienda_inventario vi
        JOIN viviendas v   ON v.id = vi.vivienda_id
        LEFT JOIN comunidades c ON c.id = v.comunidad_id
        WHERE {' AND '.join(where)}
        GROUP BY vi.artefacto_nombre_snapshot, vi.artefacto_origen, vi.artefacto_codigo, c.nombre
        ORDER BY vi.artefacto_nombre_snapshot, c.nombre
    """
    rows = (await session.execute(text(sql), params)).mappings().all()
    rows = [dict(r) for r in rows]

    sql_totales = f"""
        SELECT
          COALESCE(SUM(vi.cantidad), 0)::INT AS total_artefactos,
          COUNT(DISTINCT vi.vivienda_id)::INT AS viviendas_con_inventario
        FROM vivienda_inventario vi
        JOIN viviendas v ON v.id = vi.vivienda_id
        WHERE {' AND '.join(where)}
    """
    tot = (await session.execute(text(sql_totales), params)).mappings().first()

    return {
        "headers": ["Artefacto", "Origen", "Código", "Comunidad", "Cantidad total", "# Viviendas"],
        "rows": rows,
        "totales": dict(tot) if tot else {},
        "params": {"comunidad_id": comunidad_id, "fecha_corte": fecha},
        "generado_at": now_lima(),
    }


# ============ 5. DASHBOARD DEL ALCALDE ============

async def dashboard_alcalde(session: AsyncSession) -> dict:
    """
    KPIs ejecutivos en una página:
      - Total viviendas empadronadas (activas)
      - Total moradores activos
      - Total comunidades cubiertas
      - Subsidio vigente más reciente
      - Mes actual: recibos emitidos, cobrados, % cobranza
      - Mes anterior: comparativo
      - Top 5 viviendas con mayor deuda
    """
    hoy = date.today()
    mes_actual = hoy.month
    anio_actual = hoy.year
    mes_ant = mes_actual - 1 if mes_actual > 1 else 12
    anio_ant = anio_actual if mes_actual > 1 else anio_actual - 1

    sql_kpis = """
        SELECT
          (SELECT COUNT(*) FROM viviendas WHERE activa) AS viviendas_activas,
          (SELECT COUNT(*) FROM moradores WHERE activo) AS moradores_activos,
          (SELECT COUNT(*) FROM comunidades WHERE activa) AS comunidades_activas,
          (SELECT COUNT(DISTINCT vivienda_id) FROM vivienda_inventario
             WHERE vigente_hasta IS NULL) AS viviendas_con_inventario
    """
    kpis = dict((await session.execute(text(sql_kpis))).mappings().first() or {})

    sql_mes = """
        SELECT
          COUNT(*) AS n_recibos,
          COALESCE(SUM(total), 0) AS emitido,
          COALESCE(SUM(monto_pagado), 0) AS cobrado,
          COALESCE(SUM(saldo_pendiente), 0) AS pendiente,
          COALESCE(SUM(subsidio_monto), 0) AS subsidiado
        FROM cuotas
        WHERE periodo_anio = :a AND periodo_mes = :m
    """
    mes_act = dict((await session.execute(
        text(sql_mes), {"a": anio_actual, "m": mes_actual}
    )).mappings().first() or {})
    mes_anterior = dict((await session.execute(
        text(sql_mes), {"a": anio_ant, "m": mes_ant}
    )).mappings().first() or {})

    sql_top_deuda = """
        SELECT
          v.codigo_interno,
          c.nombre AS comunidad,
          (SELECT m.nombre_completo FROM moradores m
             WHERE m.vivienda_id = v.id AND m.es_responsable_pago AND m.activo LIMIT 1) AS responsable,
          SUM(cu.saldo_pendiente) AS deuda_total,
          COUNT(*) AS recibos_pendientes
        FROM cuotas cu
        JOIN viviendas v   ON v.id = cu.vivienda_id
        LEFT JOIN comunidades c ON c.id = v.comunidad_id
        WHERE cu.saldo_pendiente > 0
        GROUP BY v.codigo_interno, c.nombre, v.id
        ORDER BY deuda_total DESC
        LIMIT 5
    """
    top_deuda = [dict(r) for r in (await session.execute(text(sql_top_deuda))).mappings().all()]

    sql_subsidio = """
        SELECT nombre, porcentaje, base_legal, vigente_desde, vigente_hasta
        FROM subsidios
        WHERE vigente_hasta IS NULL OR vigente_hasta >= CURRENT_DATE
        ORDER BY vigente_desde DESC
        LIMIT 1
    """
    subsidio_vigente = (await session.execute(text(sql_subsidio))).mappings().first()
    subsidio_vigente = dict(subsidio_vigente) if subsidio_vigente else None

    emitido = float(mes_act.get("emitido") or 0)
    cobrado = float(mes_act.get("cobrado") or 0)
    pct_cobranza = (cobrado * 100 / emitido) if emitido > 0 else 0.0

    return {
        "kpis": kpis,
        "mes_actual": {
            **mes_act,
            "periodo": f"{anio_actual}-{mes_actual:02d}",
            "pct_cobranza": round(pct_cobranza, 1),
        },
        "mes_anterior": {**mes_anterior, "periodo": f"{anio_ant}-{mes_ant:02d}"},
        "top_deuda": top_deuda,
        "subsidio_vigente": subsidio_vigente,
        "generado_at": now_lima(),
    }
