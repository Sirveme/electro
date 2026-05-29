"""
Rutas públicas (sin autenticación). Verificación de recibos vía QR.

Seguridad: la vista expone solo lo confirmado (P5=B): municipalidad, período,
vivienda, comunidad, responsable, monto y estado. NO expone DNI.
"""
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import text

from app.database import SessionLocal, tenant_session

logger = logging.getLogger(__name__)
router = APIRouter()

_MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "setiembre", "octubre", "noviembre", "diciembre",
]


@router.get("/verificar/{numero}", response_class=HTMLResponse)
async def verificar_recibo(request: Request, numero: str):
    templates = request.app.state.templates

    numero = (numero or "").strip()
    if not numero or len(numero) > 30:
        raise HTTPException(404)

    # Listar tenants (schemas muni_*).
    async with SessionLocal() as pub:
        schemas = (
            await pub.execute(
                text(
                    "SELECT schema_name FROM information_schema.schemata "
                    "WHERE schema_name LIKE 'muni\\_%' ESCAPE '\\'"
                )
            )
        ).all()

    data = None
    for (schema,) in schemas:
        async with tenant_session(schema) as ts:
            row = (
                await ts.execute(
                    text(
                        """
                        SELECT c.numero_recibo, c.periodo_anio, c.periodo_mes,
                               c.total, c.saldo_pendiente, c.estado,
                               v.codigo_interno,
                               com.nombre AS comunidad,
                               m.nombre_completo AS jefe,
                               cfg.valor AS nombre_municipalidad,
                               p.fecha_pago AS pago_at, p.monto AS pago_monto
                        FROM cuotas c
                        JOIN viviendas v ON v.id = c.vivienda_id
                        JOIN comunidades com ON com.id = v.comunidad_id
                        LEFT JOIN moradores m
                          ON m.vivienda_id = v.id AND m.es_jefe_familia = TRUE AND m.activo = TRUE
                        LEFT JOIN config_municipio cfg ON cfg.clave = 'nombre_municipalidad'
                        LEFT JOIN pagos p ON p.cuota_id = c.id AND p.anulado = FALSE
                        WHERE c.numero_recibo = :n
                        ORDER BY p.fecha_pago DESC NULLS LAST
                        LIMIT 1
                        """
                    ),
                    {"n": numero},
                )
            ).mappings().first()
        if row:
            data = dict(row)
            break

    if not data:
        return templates.TemplateResponse(
            "publico/verificar.html",
            {"request": request, "encontrado": False, "numero": numero},
        )

    mes = data["periodo_mes"]
    data["periodo_label"] = f"{_MESES[mes - 1]} {data['periodo_anio']}" if 1 <= mes <= 12 else str(data["periodo_anio"])

    return templates.TemplateResponse(
        "publico/verificar.html",
        {"request": request, "encontrado": True, "recibo": data},
    )
