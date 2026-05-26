"""
Portal del morador — versión ampliada zClaude-04.

Muestra a un morador autenticado:
- Su deuda actual.
- Sus recibos.
- Detalle de un recibo.
- PDF del recibo descargable.

La versión completa (auto-servicio de baja de artefactos, etc.) llega en
zClaude-05.
"""
import logging
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import text

from app.context_processor import build_context
from app.database import tenant_session
from app.services.cuota_service import (
    obtener_cuota_completa,
    obtener_cuotas_por_vivienda,
)
from app.services.pdf_service import get_pdf_renderer
from app.utils.periodos import nombre_periodo, nombre_periodo_largo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/portal")


def _ensure_morador(request: Request) -> tuple[str, int, int]:
    """Devuelve (tenant_schema, morador_id, vivienda_id) o lanza 401/redirect."""
    if request.session.get("kind") != "morador":
        return None  # caller maneja redirect
    schema = request.session.get("tenant_schema")
    morador_id = request.session.get("user_id")
    vivienda_id = request.session.get("vivienda_id")
    if not schema or not morador_id or not vivienda_id:
        return None
    return (schema, morador_id, vivienda_id)


@router.get("/", response_class=HTMLResponse)
async def portal_home(request: Request):
    info = _ensure_morador(request)
    if not info:
        return RedirectResponse("/login", status_code=303)
    schema, _morador_id, vivienda_id = info

    async with tenant_session(schema) as ts:
        row = (
            await ts.execute(
                text(
                    "SELECT v.id, v.codigo_interno, v.referencia_fisica, "
                    "       com.nombre AS comunidad_nombre "
                    "FROM viviendas v LEFT JOIN comunidades com ON com.id = v.comunidad_id "
                    "WHERE v.id = :v"
                ),
                {"v": vivienda_id},
            )
        ).mappings().first()
        if not row:
            request.session.clear()
            return RedirectResponse("/login", status_code=303)
        vivienda = dict(row)
        cuotas = await obtener_cuotas_por_vivienda(ts, vivienda_id)

    saldo_total = sum(
        (Decimal(str(c["saldo_pendiente"])) for c in cuotas if c["estado"] != "pagado"),
        Decimal("0"),
    )
    pendientes_count = sum(1 for c in cuotas if c["estado"] in ("pendiente", "parcial"))

    return request.app.state.templates.TemplateResponse(
        "portal/home.html",
        build_context(
            request, user=None,
            vivienda=vivienda, cuotas=cuotas,
            saldo_total=float(saldo_total),
            pendientes_count=pendientes_count,
            nombre_periodo=nombre_periodo,
        ),
    )


@router.get("/recibos/{cuota_id}", response_class=HTMLResponse)
async def recibo_detalle(request: Request, cuota_id: int):
    info = _ensure_morador(request)
    if not info:
        return RedirectResponse("/login", status_code=303)
    schema, _morador_id, vivienda_id = info

    async with tenant_session(schema) as ts:
        cuota = await obtener_cuota_completa(ts, cuota_id)
    if not cuota or cuota["vivienda_id"] != vivienda_id:
        raise HTTPException(404, "Recibo no encontrado")

    return request.app.state.templates.TemplateResponse(
        "portal/recibo_detalle.html",
        build_context(
            request, user=None,
            cuota=cuota,
            periodo_label=nombre_periodo_largo(cuota["periodo_anio"], cuota["periodo_mes"]),
        ),
    )


@router.get("/recibos/{cuota_id}/pdf")
async def recibo_pdf(request: Request, cuota_id: int):
    info = _ensure_morador(request)
    if not info:
        return RedirectResponse("/login", status_code=303)
    schema, _morador_id, vivienda_id = info

    async with tenant_session(schema) as ts:
        cuota = await obtener_cuota_completa(ts, cuota_id)
        if not cuota or cuota["vivienda_id"] != vivienda_id:
            raise HTTPException(404, "Recibo no encontrado")
        muni_nombre = (
            await ts.execute(
                text("SELECT nombre FROM public.municipios WHERE schema_name = :s"),
                {"s": schema},
            )
        ).scalar()
        moradores = (
            await ts.execute(
                text(
                    "SELECT dni, nombre_completo, es_jefe_familia FROM moradores "
                    "WHERE vivienda_id = :v AND activo = TRUE "
                    "ORDER BY es_jefe_familia DESC, nombre_completo"
                ),
                {"v": vivienda_id},
            )
        ).mappings().all()

    renderer = get_pdf_renderer()
    ctx = {
        "cuota": cuota,
        "vivienda": {
            "codigo_interno": cuota["codigo_interno"],
            "comunidad_nombre": cuota["comunidad_nombre"],
            "referencia_fisica": cuota["referencia_fisica"],
            "direccion_textual": cuota["direccion_textual"],
        },
        "moradores": [dict(m) for m in moradores],
        "municipio_nombre": muni_nombre or "Municipio",
        "periodo_label": nombre_periodo_largo(cuota["periodo_anio"], cuota["periodo_mes"]),
    }
    pdf_bytes = renderer.render_recibo(request.app.state.templates.env, ctx)
    filename = f"recibo_{cuota['numero_recibo']}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/cuenta/cambiar-clave", response_class=HTMLResponse)
async def cambiar_clave_placeholder(request: Request):
    """Placeholder hasta zClaude-05."""
    if request.session.get("kind") != "morador":
        return RedirectResponse("/login", status_code=303)
    return request.app.state.templates.TemplateResponse(
        "portal/wip.html",
        build_context(request, user=None),
    )
