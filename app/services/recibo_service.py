"""
Generación del recibo formal A5 con ReportLab Platypus (zClaude-fix-18).

- SOLO LECTURA sobre cuotas/pagos: usa el snapshot de la cuota
  (cuota_service.obtener_cuota_completa). La numeración la asigna lote_service.
- Motor: ReportLab Platypus (no WeasyPrint). En Railway WeasyPrint caía al
  fallback de texto plano; ReportLab produce un PDF con tablas/colores.
- QR como PNG embebido; si `qrcode` no está, el recibo se genera sin QR.
- Lote: un único documento, un recibo por página (KeepTogether + PageBreak).
"""
from __future__ import annotations

import io
import logging
from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A5
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image as RLImage,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.cuota_service import obtener_cuota_completa
from app.utils.periodos import nombre_periodo_largo

logger = logging.getLogger(__name__)

# Claves de config_municipio que aparecen en la cabecera/pie del recibo.
_CONFIG_KEYS_RECIBO = (
    "nombre_municipalidad", "logo_url", "ruc",
    "direccion_municipalidad", "telefono_municipalidad", "email_municipalidad",
)

# === Paleta (consistente con la app) ===
COLOR_PRIMARY = colors.HexColor("#1B4FF5")
COLOR_SUCCESS = colors.HexColor("#10b981")
COLOR_WARN = colors.HexColor("#FF6B1A")
COLOR_DANGER = colors.HexColor("#dc2626")
COLOR_TEXT = colors.HexColor("#1a1a1a")
COLOR_TEXT_MUTED = colors.HexColor("#666666")
COLOR_BORDER = colors.HexColor("#e0e0e0")
COLOR_CARD_BG = colors.HexColor("#f8f9ff")

# Cache de logos descargados (por URL) para no re-bajarlos en cada recibo del lote.
_LOGO_CACHE: dict[str, bytes | None] = {}


def _esc(s) -> str:
    """Escapa texto para markup de Paragraph (evita romper con & < >)."""
    return _xml_escape("" if s is None else str(s))


def _estilos() -> dict:
    base = getSampleStyleSheet()
    return {
        "h1": ParagraphStyle("h1", parent=base["Heading1"], fontName="Helvetica-Bold",
                             fontSize=12, leading=14, textColor=COLOR_TEXT, spaceAfter=2),
        "normal": ParagraphStyle("normal", fontName="Helvetica", fontSize=8, leading=11,
                                 textColor=COLOR_TEXT),
        "muted": ParagraphStyle("muted", fontName="Helvetica", fontSize=7, leading=9,
                                textColor=COLOR_TEXT_MUTED),
        "recibo_numero": ParagraphStyle("recibo_numero", fontName="Helvetica-Bold", fontSize=11,
                                        leading=13, textColor=COLOR_PRIMARY, alignment=TA_CENTER),
        "recibo_label": ParagraphStyle("recibo_label", fontName="Helvetica", fontSize=7, leading=9,
                                       textColor=COLOR_TEXT_MUTED, alignment=TA_CENTER),
        "recibo_titulo": ParagraphStyle("recibo_titulo", fontName="Helvetica-Bold", fontSize=10,
                                        leading=12, textColor=COLOR_TEXT, alignment=TA_CENTER),
        "pie": ParagraphStyle("pie", fontName="Helvetica", fontSize=6.5, leading=8.5,
                              textColor=COLOR_TEXT_MUTED, alignment=TA_CENTER),
        "pie_destacado": ParagraphStyle("pie_destacado", fontName="Helvetica-Bold", fontSize=6.5,
                                        leading=8.5, textColor=COLOR_PRIMARY, alignment=TA_CENTER),
    }


# === Número a letras (es-PE), 0..999999 ===
_UNIDADES = ["CERO", "UNO", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE",
             "DIEZ", "ONCE", "DOCE", "TRECE", "CATORCE", "QUINCE", "DIECISEIS", "DIECISIETE",
             "DIECIOCHO", "DIECINUEVE", "VEINTE"]
_DECENAS = ["", "", "VEINTE", "TREINTA", "CUARENTA", "CINCUENTA", "SESENTA", "SETENTA",
            "OCHENTA", "NOVENTA"]
_CENTENAS = ["", "CIENTO", "DOSCIENTOS", "TRESCIENTOS", "CUATROCIENTOS", "QUINIENTOS",
             "SEISCIENTOS", "SETECIENTOS", "OCHOCIENTOS", "NOVECIENTOS"]


def _decenas_letras(n: int) -> str:
    if n <= 20:
        return _UNIDADES[n]
    if n < 30:
        return "VEINTI" + _UNIDADES[n - 20]
    d, u = n // 10, n % 10
    return _DECENAS[d] + (" Y " + _UNIDADES[u] if u else "")


def _centenas_letras(n: int) -> str:
    if n == 0:
        return ""
    if n == 100:
        return "CIEN"
    c, r = n // 100, n % 100
    out = _CENTENAS[c] if c else ""
    if r:
        out = (out + " " if out else "") + _decenas_letras(r)
    return out


def _num2letras(num: float) -> str:
    """Ej: 6.19 -> 'SEIS CON 19/100'. Cubre enteros 0..999999."""
    enteros = int(num)
    decimales = int(round((num - enteros) * 100))
    if decimales == 100:  # redondeo hacia arriba
        enteros += 1
        decimales = 0
    if enteros < 1000:
        letras = _centenas_letras(enteros) or "CERO"
    elif enteros < 1000000:
        miles, resto = enteros // 1000, enteros % 1000
        pref = "MIL" if miles == 1 else _centenas_letras(miles) + " MIL"
        letras = pref + (" " + _centenas_letras(resto) if resto else "")
    else:
        letras = str(enteros)
    return f"{letras} CON {decimales:02d}/100"


def _generar_qr_png_bytes(url: str) -> bytes | None:
    try:
        import qrcode  # type: ignore
    except ImportError:
        logger.warning("Librería 'qrcode' no instalada — recibo sin QR.")
        return None
    try:
        img = qrcode.make(url, box_size=4, border=1)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo generar QR: %s", exc)
        return None


def _cargar_logo_bytes(logo_url: str) -> bytes | None:
    if not logo_url:
        return None
    if logo_url in _LOGO_CACHE:
        return _LOGO_CACHE[logo_url]
    data = None
    try:
        import urllib.request
        with urllib.request.urlopen(logo_url, timeout=3) as resp:  # noqa: S310
            data = resp.read()
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo cargar el logo del recibo: %s", exc)
        data = None
    _LOGO_CACHE[logo_url] = data
    return data


async def datos_recibo(session: AsyncSession, cuota_id: int, base_url: str = "") -> dict:
    """Reúne los datos del recibo desde el snapshot de la cuota (solo lectura)."""
    cuota = await obtener_cuota_completa(session, cuota_id)
    if not cuota:
        raise ValueError(f"Cuota {cuota_id} no encontrada")

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

    cfg_rows = (
        await session.execute(
            text("SELECT clave, valor FROM config_municipio WHERE clave = ANY(:ks)"),
            {"ks": list(_CONFIG_KEYS_RECIBO)},
        )
    ).mappings().all()
    config = {r["clave"]: (r["valor"] or "") for r in cfg_rows}

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

    prov = (
        await session.execute(
            text("SELECT nombre, url FROM public.branding_proveedor ORDER BY id LIMIT 1")
        )
    ).mappings().first() or {"nombre": "Perú Sistemas Pro", "url": "perusistemas.pro"}

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
            "nombre": it.get("nombre", "") or "",
            "cantidad": float(it.get("cantidad", 0) or 0),
            "tarifa": float(it.get("tarifa", 0) or 0),
            "subtotal": float(it.get("importe", 0) or 0),
        })

    numero = cuota["numero_recibo"]
    verify_url = f"{base_url}/verificar/{numero}" if base_url else f"/verificar/{numero}"
    direccion = (cuota.get("direccion_textual") or cuota.get("referencia_fisica") or "—").strip() or "—"

    return {
        "numero_recibo": numero,
        "periodo_label": nombre_periodo_largo(cuota["periodo_anio"], cuota["periodo_mes"]),
        "fecha_emision": cuota["fecha_emision"],
        "fecha_vencimiento": cuota["fecha_vencimiento"],
        "vivienda_codigo": cuota["codigo_interno"],
        "direccion": direccion,
        "comunidad": cuota.get("comunidad_nombre") or "—",
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
        "verify_url": verify_url,
    }


def _sello_info_for(data: dict) -> tuple[str, str] | None:
    if data["estado"] == "pagado" and data.get("pago"):
        p = data["pago"]
        fecha = p["fecha_pago"].strftime("%d/%m/%Y") if p.get("fecha_pago") else ""
        cajero = p.get("cajero_nombre") or ""
        return ("PAGO TOTAL", f"Pagado el {fecha}\nCajero: {cajero}".strip())
    if data["estado"] == "parcial" and data.get("pago"):
        return (
            "PAGO EN PARTE",
            f"S/ {data['pago']['monto']:.2f} de S/ {data['total']:.2f}\n"
            f"Saldo: S/ {data['saldo_pendiente']:.2f}",
        )
    return None


def _build_recibo_flowables(data: dict, estilos: dict) -> list:
    cfg = data["config"]
    nombre_muni = (cfg.get("nombre_municipalidad") or "MUNICIPALIDAD").upper()
    ruc = cfg.get("ruc") or ""
    direccion_muni = cfg.get("direccion_municipalidad") or ""
    telefono = cfg.get("telefono_municipalidad") or ""
    email = cfg.get("email_municipalidad") or ""

    # --- Cabecera: izquierda (logo + datos) / derecha (card RUC + número) ---
    info_muni = [Paragraph(_esc(nombre_muni), estilos["h1"])]
    if direccion_muni:
        info_muni.append(Paragraph(_esc(direccion_muni), estilos["normal"]))
    if telefono:
        info_muni.append(Paragraph("Tel: " + _esc(telefono), estilos["normal"]))
    if ruc:
        info_muni.append(Paragraph("RUC: " + _esc(ruc), estilos["normal"]))
    if email:
        info_muni.append(Paragraph(_esc(email), estilos["normal"]))

    logo_elem = ""
    logo_bytes = _cargar_logo_bytes(cfg.get("logo_url") or "")
    if logo_bytes:
        try:
            logo_elem = RLImage(io.BytesIO(logo_bytes), width=14 * mm, height=14 * mm)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Logo no renderizable: %s", exc)
            logo_elem = ""

    izq_table = Table([[logo_elem, info_muni]], colWidths=[16 * mm, 70 * mm], hAlign="LEFT")
    izq_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))

    card_recibo = Table([
        [Paragraph(f"<b>RUC</b>  {_esc(ruc) or '----------'}", estilos["recibo_label"])],
        [Paragraph("RECIBO DE ENERGÍA", estilos["recibo_titulo"])],
        [Paragraph(_esc(data["numero_recibo"]), estilos["recibo_numero"])],
    ], colWidths=[48 * mm], rowHeights=[6 * mm, 7 * mm, 8 * mm])
    card_recibo.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1, COLOR_BORDER),
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_CARD_BG),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, COLOR_BORDER),
        ("LINEBELOW", (0, 1), (-1, 1), 0.5, COLOR_BORDER),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    cabecera = Table([[izq_table, card_recibo]], colWidths=[86 * mm, 48 * mm])
    cabecera.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))

    # --- Datos morador + fechas ---
    morador_html = (
        "<b>MORADOR</b><br/>"
        f"<b>DNI:</b> {_esc(data['jefe_dni']) or '—'}<br/>"
        f"<b>Nombre:</b> {_esc((data['jefe'] or 'Sin responsable').upper())}<br/>"
        f"<b>Vivienda:</b> {_esc(data['vivienda_codigo'])}<br/>"
        f"<b>Dirección:</b> {_esc(data['direccion'])}<br/>"
        f"<b>Comunidad:</b> {_esc(data['comunidad'])}"
    )
    estado_color = {"pagado": "#10b981", "parcial": "#1B4FF5", "pendiente": "#FF6B1A"}.get(
        data["estado"], "#666666")
    fe = data["fecha_emision"].strftime("%d/%m/%Y") if data["fecha_emision"] else "—"
    fv = data["fecha_vencimiento"].strftime("%d/%m/%Y") if data["fecha_vencimiento"] else "—"
    fechas_html = (
        f"<b>Periodo:</b> {_esc(data['periodo_label'])}<br/>"
        f"<b>Emisión:</b> {fe}<br/>"
        f"<b>Vencimiento:</b> {fv}<br/>"
        f'<b>Estado:</b> <font color="{estado_color}"><b>{_esc(data["estado"].upper())}</b></font>'
    )
    datos_table = Table([
        [Paragraph(morador_html, estilos["normal"]), Paragraph(fechas_html, estilos["normal"])],
    ], colWidths=[80 * mm, 54 * mm])
    datos_table.setStyle(TableStyle([
        ("BOX", (0, 0), (0, 0), 0.5, COLOR_BORDER),
        ("BOX", (1, 0), (1, 0), 0.5, COLOR_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    # --- Tabla de cargos ---
    cargos_data = [["Cant.", "Descripción", "Tarifa", "Importe"]]
    if data["alumbrado"] > 0:
        cargos_data.append(["", Paragraph("<b>ALUMBRADO PÚBLICO</b>", estilos["normal"]),
                            "", f"S/ {data['alumbrado']:.2f}"])
    for item in data["inventario"]:
        cargos_data.append([
            f"{int(item['cantidad'])}",
            Paragraph(_esc(item["nombre"]), estilos["normal"]),
            f"S/ {item['tarifa']:.2f}",
            f"S/ {item['subtotal']:.2f}",
        ])
    if data["n_moradores"] > 0 and data["adicional_morador"] > 0:
        cargos_data.append([
            f"{data['n_moradores']}",
            Paragraph("Adicional por morador", estilos["normal"]),
            f"S/ {data['adicional_morador']:.2f}",
            f"S/ {data['subtotal_moradores']:.2f}",
        ])
    tabla_cargos = Table(cargos_data, colWidths=[14 * mm, 78 * mm, 18 * mm, 24 * mm])
    tabla_cargos.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),
        ("ALIGN", (2, 1), (3, -1), "RIGHT"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, COLOR_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    # --- Totales ---
    totales_data = [["Subtotal consumo:", f"S/ {data['consumo_privado']:.2f}"]]
    if data["descuento"] > 0:
        totales_data.append([f"Subvención ({data['subsidio_pct']:.0f}%):",
                             f"S/ -{data['descuento']:.2f}"])
        totales_data.append(["Consumo neto:", f"S/ {data['consumo_neto']:.2f}"])
    totales_data.append(["", ""])
    totales_data.append(["TOTAL A PAGAR:", f"S/ {data['total']:.2f}"])
    totales_table = Table(totales_data, colWidths=[80 * mm, 28 * mm], hAlign="RIGHT")
    totales_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, 0), (-1, -2), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -2), 8.5),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, -1), (-1, -1), 12),
        ("TEXTCOLOR", (0, -1), (-1, -1), COLOR_PRIMARY),
        ("LINEABOVE", (0, -1), (-1, -1), 1, COLOR_PRIMARY),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))

    # --- Importe en letras ---
    letras = _num2letras(data["total"])
    importe_letras = Table([
        [Paragraph(f"<b>IMPORTE EN LETRAS:</b>  {_esc(letras)} SOLES", estilos["normal"])],
    ], colWidths=[134 * mm])
    importe_letras.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_CARD_BG),
        ("BOX", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    # --- Sello + QR ---
    qr_bytes = _generar_qr_png_bytes(data["verify_url"])
    qr_elem = ""
    if qr_bytes:
        try:
            qr_elem = RLImage(io.BytesIO(qr_bytes), width=22 * mm, height=22 * mm)
        except Exception:  # noqa: BLE001
            qr_elem = ""
    sello_html = "<b>Sello y firma del cajero</b><br/><br/><br/><br/>_______________________________"
    sello_qr = Table([[Paragraph(sello_html, estilos["normal"]), qr_elem]],
                     colWidths=[100 * mm, 30 * mm])
    sello_qr.setStyle(TableStyle([
        ("BOX", (0, 0), (0, 0), 0.5, COLOR_BORDER),
        ("BOX", (1, 0), (1, 0), 0.5, COLOR_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    prov = data.get("proveedor") or {"nombre": "Perú Sistemas Pro", "url": "perusistemas.pro"}

    flow = [
        cabecera, Spacer(1, 4 * mm),
        datos_table, Spacer(1, 4 * mm),
        tabla_cargos, Spacer(1, 3 * mm),
        totales_table,
    ]
    if data.get("subsidio_ord"):
        flow.append(Spacer(1, 2 * mm))
        flow.append(Paragraph(f"<i>Subvención respaldada por {_esc(data['subsidio_ord'])}</i>",
                              estilos["muted"]))
    flow += [
        Spacer(1, 3 * mm), importe_letras, Spacer(1, 3 * mm),
        sello_qr, Spacer(1, 3 * mm),
        Paragraph("Recibo interno municipal sin valor tributario.", estilos["pie"]),
        Paragraph("Válido únicamente con sello de caja y firma del cajero.", estilos["pie"]),
        Paragraph(f'Verificable en: <font color="#1B4FF5">{_esc(data["verify_url"])}</font>',
                  estilos["pie"]),
        Spacer(1, 2 * mm),
        Paragraph(f"Sistema operado por {_esc(prov['nombre'])} · {_esc(prov['url'])}",
                  estilos["pie_destacado"]),
    ]
    return flow


def _draw_sello(c, sello_info: tuple[str, str]) -> None:
    page_w, page_h = A5
    c.saveState()
    c.translate(page_w / 2, page_h * 0.55)
    c.rotate(-15)
    c.setStrokeColor(COLOR_DANGER)
    c.setLineWidth(3)
    c.setFillColor(colors.Color(220 / 255, 38 / 255, 38 / 255, alpha=0.12))
    w, h = 80 * mm, 30 * mm
    c.roundRect(-w / 2, -h / 2, w, h, 4 * mm, fill=1)
    c.setFillColor(COLOR_DANGER)
    c.setFont("Helvetica-Bold", 22)
    c.drawCentredString(0, 2 * mm, sello_info[0])
    c.setFont("Helvetica", 6.5)
    for i, linea in enumerate((sello_info[1] or "").split("\n")):
        c.drawCentredString(0, -6 * mm - i * 3 * mm, linea)
    c.restoreState()


def _render_pdf(datos_list: list[dict]) -> bytes:
    estilos = _estilos()
    story: list = []
    sellos: list = []
    for idx, data in enumerate(datos_list):
        story.append(KeepTogether(_build_recibo_flowables(data, estilos)))
        sellos.append(_sello_info_for(data))
        if idx < len(datos_list) - 1:
            story.append(PageBreak())

    buf = io.BytesIO()
    titulo = (f"Recibo {datos_list[0]['numero_recibo']}" if len(datos_list) == 1
              else f"Recibos ({len(datos_list)})")
    doc = SimpleDocTemplate(
        buf, pagesize=A5,
        leftMargin=8 * mm, rightMargin=8 * mm, topMargin=8 * mm, bottomMargin=8 * mm,
        title=titulo,
    )

    def _on_page(c, doc_obj):
        # Cada recibo ocupa una página (KeepTogether + PageBreak); page i -> recibo i-1.
        i = doc_obj.page - 1
        if 0 <= i < len(sellos) and sellos[i]:
            _draw_sello(c, sellos[i])

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes


async def generar_pdf_recibo(session: AsyncSession, cuota_id: int, base_url: str) -> bytes:
    """PDF A5 de un recibo individual (ReportLab Platypus)."""
    data = await datos_recibo(session, cuota_id, base_url)
    return _render_pdf([data])


async def generar_pdf_lote(session: AsyncSession, cuota_ids: list[int], base_url: str) -> bytes:
    """PDF combinado: un recibo por página."""
    datos_list = []
    for cid in cuota_ids:
        try:
            datos_list.append(await datos_recibo(session, cid, base_url))
        except ValueError:
            logger.warning("Cuota %s omitida del lote (no encontrada)", cid)
    if not datos_list:
        raise ValueError("No hay recibos válidos para generar")
    return _render_pdf(datos_list)
