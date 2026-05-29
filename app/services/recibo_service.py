"""
Generación del recibo formal A5 (HTML→PDF) con QR de verificación.

Diseño:
- Es SOLO LECTURA sobre cuotas/pagos: usa el snapshot ya guardado en la cuota
  (cuota_service.obtener_cuota_completa), no recalcula nada. La numeración la
  asigna lote_service (no se toca aquí).
- Reutiliza el renderer de pdf_service (WeasyPrint con fallback a ReportLab).
- El QR se incrusta como data-URI base64; si la librería `qrcode` no está
  instalada, el recibo se genera igual sin QR (degradación elegante).
"""
from __future__ import annotations

import base64
import io
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.cuota_service import obtener_cuota_completa
from app.services.pdf_service import get_pdf_renderer
from app.utils.periodos import nombre_periodo_largo

logger = logging.getLogger(__name__)

# Claves de config_municipio que aparecen en la cabecera/pie del recibo.
_CONFIG_KEYS_RECIBO = (
    "nombre_municipalidad", "logo_url", "ruc",
    "direccion_municipalidad", "telefono_municipalidad", "email_municipalidad",
)


def generar_qr_base64(url: str) -> Optional[str]:
    """Genera un QR como data-URI PNG base64. Retorna None si `qrcode` no está."""
    try:
        import qrcode  # type: ignore
    except ImportError:
        logger.warning("Librería 'qrcode' no instalada — recibo sin QR.")
        return None
    try:
        img = qrcode.make(url, box_size=4, border=2)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo generar el QR para %s", url)
        return None


async def datos_recibo(session: AsyncSession, cuota_id: int, base_url: str = "") -> dict:
    """
    Reúne los datos del recibo desde el snapshot de la cuota (solo lectura).
    """
    cuota = await obtener_cuota_completa(session, cuota_id)
    if not cuota:
        raise ValueError(f"Cuota {cuota_id} no encontrada")

    # Jefe de familia (responsable) de la vivienda.
    jefe = (
        await session.execute(
            text(
                "SELECT nombre_completo, dni FROM moradores "
                "WHERE vivienda_id = :v AND es_jefe_familia = TRUE AND activo = TRUE "
                "ORDER BY id LIMIT 1"
            ),
            {"v": cuota["vivienda_id"]},
        )
    ).mappings().first()

    # Config del municipio (cabecera/pie).
    cfg_rows = (
        await session.execute(
            text("SELECT clave, valor FROM config_municipio WHERE clave = ANY(:ks)"),
            {"ks": list(_CONFIG_KEYS_RECIBO)},
        )
    ).mappings().all()
    config = {r["clave"]: r["valor"] for r in cfg_rows}

    # Último pago no anulado (para el sello "PAGO TOTAL").
    pago = (
        await session.execute(
            text(
                "SELECT p.monto, p.fecha_pago, u.nombre_completo AS cajero_nombre "
                "FROM pagos p "
                "LEFT JOIN usuarios u ON u.id = p.cobrado_por_user_id "
                "WHERE p.cuota_id = :cid AND p.anulado = FALSE "
                "ORDER BY p.fecha_pago DESC LIMIT 1"
            ),
            {"cid": cuota_id},
        )
    ).mappings().first()

    # Branding del proveedor (Perú Sistemas Pro).
    prov = (
        await session.execute(
            text("SELECT nombre, url FROM public.branding_proveedor ORDER BY id LIMIT 1")
        )
    ).mappings().first() or {"nombre": "Perú Sistemas Pro", "url": "perusistemas.pro"}

    # Desglose desde el snapshot.
    alumbrado = float(cuota["cargo_fijo"] or 0)
    subtotal = float(cuota["subtotal"] or 0)
    adicional_total = float(cuota["adicional_morador"] or 0)
    n_moradores = int(cuota["n_moradores"] or 0)
    adicional_unit = round(adicional_total / n_moradores, 2) if n_moradores else 0.0
    descuento = float(cuota["subsidio_monto"] or 0)
    consumo_privado = round(subtotal - alumbrado, 2)
    consumo_neto = round(consumo_privado - descuento, 2)

    inventario = []
    for it in (cuota.get("detalle_aparatos_json") or []):
        inventario.append({
            "nombre": it.get("nombre", ""),
            "cantidad": float(it.get("cantidad", 0) or 0),
            "tarifa": float(it.get("tarifa", 0) or 0),
            "subtotal": float(it.get("importe", 0) or 0),
        })

    numero = cuota["numero_recibo"]
    verify_url = f"{base_url}/verificar/{numero}" if base_url else f"/verificar/{numero}"

    return {
        "numero_recibo": numero,
        "periodo_label": nombre_periodo_largo(cuota["periodo_anio"], cuota["periodo_mes"]),
        "fecha_emision": cuota["fecha_emision"],
        "fecha_vencimiento": cuota["fecha_vencimiento"],
        "vivienda_codigo": cuota["codigo_interno"],
        "direccion": cuota.get("direccion_textual") or cuota.get("referencia_fisica") or "",
        "comunidad": cuota.get("comunidad_nombre") or "",
        "jefe": (jefe["nombre_completo"] if jefe else None) or "Sin responsable registrado",
        "jefe_dni": (jefe["dni"] if jefe else "") or "",
        "alumbrado": round(alumbrado, 2),
        "inventario": inventario,
        "n_moradores": n_moradores,
        "adicional_morador": adicional_unit,
        "subtotal_moradores": round(adicional_total, 2),
        "consumo_privado": consumo_privado,
        "subsidio_pct": float(cuota["subsidio_porcentaje"] or 0),
        "subsidio_ord": cuota.get("subsidio_base_legal"),
        "descuento": round(descuento, 2),
        "consumo_neto": consumo_neto,
        "total": float(cuota["total"] or 0),
        "saldo_pendiente": float(cuota["saldo_pendiente"] or 0),
        "estado": cuota["estado"],
        "pago": dict(pago) if pago else None,
        "config": config,
        "proveedor": dict(prov),
        "qr_base64": generar_qr_base64(verify_url),
        "verify_url": verify_url,
    }


def _render_html(env, recibos: list[dict]) -> str:
    template = env.get_template("tenant/recibos/_recibo_a5.html")
    return template.render(recibos=recibos)


async def generar_pdf_recibo(env, session: AsyncSession, cuota_id: int, base_url: str) -> bytes:
    """PDF A5 de un recibo individual."""
    data = await datos_recibo(session, cuota_id, base_url)
    html = _render_html(env, [data])
    return get_pdf_renderer().render_html_to_pdf(html)


async def generar_pdf_lote(env, session: AsyncSession, cuota_ids: list[int], base_url: str) -> bytes:
    """
    PDF combinado con N recibos (un recibo por página, sin librería de merge:
    se concatenan en un único documento HTML con salto de página).
    """
    recibos = []
    for cid in cuota_ids:
        try:
            recibos.append(await datos_recibo(session, cid, base_url))
        except ValueError:
            logger.warning("Cuota %s omitida del lote (no encontrada)", cid)
    if not recibos:
        raise ValueError("No hay recibos válidos para generar")
    html = _render_html(env, recibos)
    return get_pdf_renderer().render_html_to_pdf(html)
