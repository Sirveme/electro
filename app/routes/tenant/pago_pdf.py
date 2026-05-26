"""Endpoint de descarga del comprobante PDF de un pago."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import text

from app.database import tenant_session
from app.dependencies import CurrentUser, require_password_changed
from app.services.pago_service import obtener_pago_completo
from app.services.pdf_service import get_pdf_renderer
from app.utils.periodos import nombre_periodo_largo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/app/pagos")


@router.get("/{pago_id}/comprobante")
async def descargar_comprobante(
    request: Request,
    pago_id: int,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("cobranza", "recibos", "ver"):
        raise HTTPException(403, "Sin permiso")
    async with tenant_session(user.tenant_schema) as ts:
        pago = await obtener_pago_completo(ts, pago_id)
        if not pago:
            raise HTTPException(404, "Pago no encontrado")
        muni_nombre = (
            await ts.execute(
                text(
                    "SELECT m.nombre FROM public.municipios m WHERE m.schema_name = :s"
                ),
                {"s": user.tenant_schema},
            )
        ).scalar()

    renderer = get_pdf_renderer()
    ctx = {
        "pago": pago,
        "cuota": {
            "numero_recibo": pago["numero_recibo"],
            "total": pago["total"],
            "monto_pagado": pago["monto_pagado"],
            "saldo_pendiente": pago["saldo_pendiente"],
        },
        "vivienda": {
            "codigo_interno": pago["codigo_interno"],
            "comunidad_nombre": pago["comunidad_nombre"],
            "referencia_fisica": pago["referencia_fisica"],
        },
        "municipio_nombre": muni_nombre or "Municipio",
        "cajero_nombre": pago.get("cajero_nombre") or "",
        "periodo_label": nombre_periodo_largo(pago["periodo_anio"], pago["periodo_mes"]),
    }
    pdf_bytes = renderer.render_comprobante_pago(request.app.state.templates.env, ctx)
    filename = f"comprobante_pago_{pago['id']:06d}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
