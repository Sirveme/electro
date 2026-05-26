"""
Reportes y consultas. Tres formatos por reporte: HTML (default), CSV, PDF.
?format=csv → descarga forzada CSV (BOM UTF-8 para Excel).
?format=pdf → descarga forzada PDF.

Las descargas usan application/octet-stream + Content-Disposition: attachment
para evitar previews inline en navegadores con visor PDF activo o intermediarios
(Cloudflare) que cambian content-type.
"""
import csv
import io
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from sqlalchemy import text

from app.context_processor import build_context
from app.database import tenant_session
from app.dependencies import CurrentUser, require_password_changed
from app.services.pdf_service import get_pdf_renderer
from app.services.reportes_service import (
    dashboard_alcalde,
    reporte_cobranza_pendiente,
    reporte_inventario_consolidado,
    reporte_padron_global,
    reporte_recaudacion_mensual,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/app/reportes")


PERMISO_POR_REPORTE = {
    "padron":      ("reportes", "padron",      "ver"),
    "recaudacion": ("reportes", "recaudacion", "ver"),
    "cobranza":    ("reportes", "cobranza",    "ver"),
    "inventario":  ("reportes", "inventario",  "ver"),
    "dashboard":   ("reportes", "dashboard",   "ver"),
}


def _check_permiso(user: CurrentUser, reporte: str) -> None:
    parts = PERMISO_POR_REPORTE.get(reporte)
    if parts is None:
        raise HTTPException(404, "Reporte no encontrado")
    if not user.puede(*parts):
        raise HTTPException(403, "Sin permiso para este reporte")


def _format_cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return f"{v:.2f}"
    return str(v)


def _csv_response(filename: str, headers: list[str], rows: list[dict]) -> StreamingResponse:
    """Genera CSV streaming con descarga forzada (resistente a inline preview).

    - BOM (\\ufeff) hace que Excel lea UTF-8 sin caracteres raros en tildes.
    - application/octet-stream evita que el navegador haga preview inline.
    - filename*=UTF-8'' por RFC 6266 para nombres con caracteres especiales.
    """
    output = io.StringIO()
    output.write("﻿")
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(headers)
    for r in rows:
        writer.writerow([_format_cell(v) for v in r.values()])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}.csv"; filename*=UTF-8\'\'{filename}.csv',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


async def _render_pdf(request: Request, template: str, ctx: dict, filename: str) -> Response:
    """Render template Jinja → HTML → PDF (vía pdf_service). Descarga forzada."""
    html = request.app.state.templates.get_template(template).render(ctx)
    renderer = get_pdf_renderer()
    pdf_bytes = renderer.render_html_to_pdf(html)
    return Response(
        content=pdf_bytes,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}.pdf"; filename*=UTF-8\'\'{filename}.pdf',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


async def _comunidades(ts) -> list[dict]:
    rows = (await ts.execute(
        text("SELECT id, nombre FROM comunidades WHERE activa ORDER BY nombre")
    )).mappings().all()
    return [dict(r) for r in rows]


# ============ HUB ============

@router.get("/", response_class=HTMLResponse)
async def index(request: Request, user: CurrentUser = Depends(require_password_changed)):
    return request.app.state.templates.TemplateResponse(
        "tenant/reportes/index.html",
        build_context(request, user=user),
    )


# ============ 1. PADRÓN GLOBAL ============

@router.get("/padron")
async def padron(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
    format: str = Query("html"),
    comunidad: Optional[int] = None,
    estado: Optional[str] = None,
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
):
    _check_permiso(user, "padron")
    async with tenant_session(user.tenant_schema) as ts:
        data = await reporte_padron_global(ts, comunidad, estado, fecha_desde, fecha_hasta)
        comunidades = await _comunidades(ts)

    filtros = {"comunidad": comunidad, "estado": estado,
               "fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta}

    if format == "csv":
        return _csv_response("padron_global", data["headers"], data["rows"])
    if format == "pdf":
        ctx = build_context(request, user=user, data=data,
                            comunidades=comunidades, filtros=filtros, print_mode=True)
        return await _render_pdf(request, "tenant/reportes/padron_global.html", ctx, "padron_global")

    return request.app.state.templates.TemplateResponse(
        "tenant/reportes/padron_global.html",
        build_context(request, user=user, data=data, comunidades=comunidades, filtros=filtros),
    )


# ============ 2. RECAUDACIÓN MENSUAL ============

@router.get("/recaudacion")
async def recaudacion(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
    format: str = Query("html"),
    anio: Optional[int] = None,
    mes: Optional[int] = None,
):
    _check_permiso(user, "recaudacion")
    hoy = date.today()
    anio = anio or hoy.year
    mes = mes or hoy.month
    async with tenant_session(user.tenant_schema) as ts:
        data = await reporte_recaudacion_mensual(ts, anio, mes)

    if format == "csv":
        return _csv_response(f"recaudacion_{anio}_{mes:02d}", data["headers"], data["rows"])
    if format == "pdf":
        ctx = build_context(request, user=user, data=data, anio=anio, mes=mes, print_mode=True)
        return await _render_pdf(
            request, "tenant/reportes/recaudacion_mensual.html", ctx,
            f"recaudacion_{anio}_{mes:02d}",
        )

    return request.app.state.templates.TemplateResponse(
        "tenant/reportes/recaudacion_mensual.html",
        build_context(request, user=user, data=data, anio=anio, mes=mes),
    )


# ============ 3. COBRANZA PENDIENTE ============

@router.get("/cobranza-pendiente")
async def cobranza_pend(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
    format: str = Query("html"),
    comunidad: Optional[int] = None,
):
    _check_permiso(user, "cobranza")
    async with tenant_session(user.tenant_schema) as ts:
        data = await reporte_cobranza_pendiente(ts, comunidad)
        comunidades = await _comunidades(ts)

    filtros = {"comunidad": comunidad}

    if format == "csv":
        return _csv_response("cobranza_pendiente", data["headers"], data["rows"])
    if format == "pdf":
        ctx = build_context(request, user=user, data=data,
                            comunidades=comunidades, filtros=filtros, print_mode=True)
        return await _render_pdf(
            request, "tenant/reportes/cobranza_pendiente.html", ctx, "cobranza_pendiente",
        )

    return request.app.state.templates.TemplateResponse(
        "tenant/reportes/cobranza_pendiente.html",
        build_context(request, user=user, data=data, comunidades=comunidades, filtros=filtros),
    )


# ============ 4. INVENTARIO CONSOLIDADO ============

@router.get("/inventario")
async def inventario(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
    format: str = Query("html"),
    comunidad: Optional[int] = None,
    fecha_corte: Optional[date] = None,
):
    _check_permiso(user, "inventario")
    async with tenant_session(user.tenant_schema) as ts:
        data = await reporte_inventario_consolidado(ts, comunidad, fecha_corte)
        comunidades = await _comunidades(ts)

    filtros = {"comunidad": comunidad, "fecha_corte": fecha_corte}

    if format == "csv":
        return _csv_response("inventario_consolidado", data["headers"], data["rows"])
    if format == "pdf":
        ctx = build_context(request, user=user, data=data,
                            comunidades=comunidades, filtros=filtros, print_mode=True)
        return await _render_pdf(
            request, "tenant/reportes/inventario_consolidado.html", ctx, "inventario_consolidado",
        )

    return request.app.state.templates.TemplateResponse(
        "tenant/reportes/inventario_consolidado.html",
        build_context(request, user=user, data=data, comunidades=comunidades, filtros=filtros),
    )


# ============ 5. DASHBOARD DEL ALCALDE ============

@router.get("/dashboard")
async def dashboard(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
    format: str = Query("html"),
):
    _check_permiso(user, "dashboard")
    async with tenant_session(user.tenant_schema) as ts:
        data = await dashboard_alcalde(ts)

    if format == "csv":
        headers = ["Métrica", "Valor"]
        rows = [
            {"m": "Viviendas empadronadas",       "v": data["kpis"].get("viviendas_activas", 0)},
            {"m": "Moradores activos",            "v": data["kpis"].get("moradores_activos", 0)},
            {"m": "Comunidades activas",          "v": data["kpis"].get("comunidades_activas", 0)},
            {"m": "Viviendas con inventario",     "v": data["kpis"].get("viviendas_con_inventario", 0)},
            {"m": f"Recibos emitidos ({data['mes_actual']['periodo']})",
             "v": data["mes_actual"].get("n_recibos", 0)},
            {"m": "Monto emitido",                "v": data["mes_actual"].get("emitido", 0)},
            {"m": "Monto cobrado",                "v": data["mes_actual"].get("cobrado", 0)},
            {"m": "Saldo pendiente",              "v": data["mes_actual"].get("pendiente", 0)},
            {"m": "% cobranza del mes",           "v": data["mes_actual"].get("pct_cobranza", 0)},
        ]
        return _csv_response("dashboard_alcalde", headers, rows)
    if format == "pdf":
        ctx = build_context(request, user=user, data=data, print_mode=True)
        return await _render_pdf(
            request, "tenant/reportes/dashboard_alcalde.html", ctx, "dashboard_alcalde",
        )

    return request.app.state.templates.TemplateResponse(
        "tenant/reportes/dashboard_alcalde.html",
        build_context(request, user=user, data=data),
    )
