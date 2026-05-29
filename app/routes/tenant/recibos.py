"""
Recibos formales A5: pantalla de impresión por lotes, PDF individual y PDF
combinado. Solo lectura sobre cuotas (numeración la asigna lote_service).
"""
import io
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import text

from app.context_processor import build_context
from app.database import tenant_session
from app.dependencies import CurrentUser, require_password_changed
from app.services.recibo_service import generar_pdf_lote, generar_pdf_recibo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/app/recibos")

MAX_LOTE = 100


def _pdf_response(pdf_bytes: bytes, filename: str, inline: bool = True) -> Response:
    disp = "inline" if inline else "attachment"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"{disp}; filename=\"{filename}\"",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.get("")
async def lista_impresion(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
    comunidad_id: str = Query(""),
    desde: str = Query(""),
    hasta: str = Query(""),
    estado: str = Query("pendiente"),
    periodo_anio: str = Query(""),
    periodo_mes: str = Query(""),
):
    if not user.puede("cobranza", "recibos", "ver"):
        raise HTTPException(403, "Sin permiso")

    # Los parámetros llegan como string: un <select> vacío manda "" y un
    # `int = Query(None)` devolvería 422. Se convierten manualmente.
    comunidad_id_int = int(comunidad_id) if comunidad_id.strip().isdigit() else None
    periodo_anio_int = int(periodo_anio) if periodo_anio.strip().isdigit() else None
    periodo_mes_int = int(periodo_mes) if periodo_mes.strip().isdigit() else None
    desde = desde.strip() or None
    hasta = hasta.strip() or None

    where = ["v.activa = TRUE", "v.anulada_at IS NULL", "c.estado != 'anulada'"]
    params: dict = {}
    if comunidad_id_int:
        where.append("v.comunidad_id = :cid")
        params["cid"] = comunidad_id_int
    if desde:
        where.append("v.codigo_interno >= :desde")
        params["desde"] = desde
    if hasta:
        where.append("v.codigo_interno <= :hasta")
        params["hasta"] = hasta
    if estado and estado != "todos":
        where.append("c.estado = :est")
        params["est"] = estado
    if periodo_anio_int and periodo_mes_int:
        where.append("c.periodo_anio = :anio AND c.periodo_mes = :mes")
        params["anio"] = periodo_anio_int
        params["mes"] = periodo_mes_int
    where_sql = " AND ".join(where)

    async with tenant_session(user.tenant_schema) as ts:
        comunidades = (
            await ts.execute(
                text("SELECT id, nombre FROM comunidades WHERE activa = TRUE ORDER BY nombre")
            )
        ).mappings().all()
        cuotas = (
            await ts.execute(
                text(
                    f"""
                    SELECT c.id, c.numero_recibo, c.periodo_anio, c.periodo_mes,
                           c.total, c.estado,
                           v.codigo_interno,
                           com.nombre AS comunidad,
                           m.nombre_completo AS jefe
                    FROM cuotas c
                    JOIN viviendas v ON v.id = c.vivienda_id
                    JOIN comunidades com ON com.id = v.comunidad_id
                    LEFT JOIN moradores m
                      ON m.vivienda_id = v.id AND m.es_jefe_familia = TRUE AND m.activo = TRUE
                    WHERE {where_sql}
                    ORDER BY v.codigo_interno
                    LIMIT 200
                    """
                ),
                params,
            )
        ).mappings().all()

    ctx = build_context(
        request, user=user,
        comunidades=[dict(c) for c in comunidades],
        cuotas=[dict(c) for c in cuotas],
        filtros={
            "comunidad_id": comunidad_id_int,
            "desde": desde, "hasta": hasta, "estado": estado,
            "periodo_anio": periodo_anio_int, "periodo_mes": periodo_mes_int,
        },
    )
    return request.app.state.templates.TemplateResponse("tenant/recibos/lista_impresion.html", ctx)


@router.get("/cuota/{cuota_id}.pdf")
async def descargar_pdf(
    request: Request,
    cuota_id: int,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("cobranza", "recibos", "ver"):
        raise HTTPException(403, "Sin permiso")
    base_url = str(request.base_url).rstrip("/")
    async with tenant_session(user.tenant_schema) as ts:
        try:
            pdf_bytes = await generar_pdf_recibo(ts, cuota_id, base_url)
        except ValueError:
            raise HTTPException(404, "Recibo no encontrado")
    return _pdf_response(pdf_bytes, f"recibo_{cuota_id}.pdf", inline=True)


@router.get("/lote.pdf")
async def descargar_lote_pdf(
    request: Request,
    cuota_ids: str = Query(...),
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("cobranza", "recibos", "ver"):
        raise HTTPException(403, "Sin permiso")
    ids = []
    for x in cuota_ids.split(","):
        x = x.strip()
        if x.isdigit():
            ids.append(int(x))
    if not ids:
        raise HTTPException(400, "Sin recibos seleccionados")
    if len(ids) > MAX_LOTE:
        raise HTTPException(400, f"Máximo {MAX_LOTE} recibos por lote.")

    base_url = str(request.base_url).rstrip("/")
    async with tenant_session(user.tenant_schema) as ts:
        try:
            pdf_bytes = await generar_pdf_lote(ts, ids, base_url)
        except ValueError:
            raise HTTPException(404, "No hay recibos válidos")
    return _pdf_response(pdf_bytes, "recibos_lote.pdf", inline=False)
