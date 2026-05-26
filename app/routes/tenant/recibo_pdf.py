"""Endpoint de descarga PDF de un recibo individual."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import text

from app.database import tenant_session
from app.dependencies import CurrentUser, require_password_changed
from app.services.cuota_service import obtener_cuota_completa
from app.services.pdf_service import get_pdf_renderer
from app.utils.periodos import nombre_periodo_largo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/app/recibos")


@router.get("/{cuota_id}/pdf")
async def descargar_recibo(
    request: Request,
    cuota_id: int,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("cobranza", "recibos", "ver"):
        raise HTTPException(403, "Sin permiso")
    async with tenant_session(user.tenant_schema) as ts:
        cuota = await obtener_cuota_completa(ts, cuota_id)
        if not cuota:
            raise HTTPException(404, "Recibo no encontrado")
        muni_nombre = (
            await ts.execute(
                text(
                    "SELECT m.nombre FROM public.municipios m WHERE m.schema_name = :s"
                ),
                {"s": user.tenant_schema},
            )
        ).scalar()
        moradores = (
            await ts.execute(
                text(
                    "SELECT dni, nombre_completo, es_jefe_familia FROM moradores "
                    "WHERE vivienda_id = :v AND activo = TRUE "
                    "ORDER BY es_jefe_familia DESC, nombre_completo"
                ),
                {"v": cuota["vivienda_id"]},
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
