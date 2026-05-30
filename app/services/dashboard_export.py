"""
Exportación PDF del dashboard del alcalde con ReportLab Platypus (zClaude-fix-19a).

Antes el PDF del dashboard salía como texto plano (HTML→fallback de WeasyPrint en
Railway). Aquí se genera con ReportLab, igual que el recibo (fix-18).
Solo lectura: recibe el `data` ya calculado por reportes_service.dashboard_alcalde.
"""
from __future__ import annotations

import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

COLOR_PRIMARY = colors.HexColor("#1B4FF5")
COLOR_BORDER = colors.HexColor("#e0e0e0")
COLOR_CARD_BG = colors.HexColor("#f8f9ff")


def _kpi_rows(data: dict) -> list[tuple[str, str]]:
    kpis = data.get("kpis", {}) or {}
    mes = data.get("mes_actual", {}) or {}
    periodo = mes.get("periodo", "")

    def money(v):
        try:
            return f"S/ {float(v):.2f}"
        except (TypeError, ValueError):
            return "S/ 0.00"

    return [
        ("Viviendas empadronadas", str(kpis.get("viviendas_activas", 0))),
        ("Moradores activos", str(kpis.get("moradores_activos", 0))),
        ("Comunidades activas", str(kpis.get("comunidades_activas", 0))),
        ("Viviendas con inventario", str(kpis.get("viviendas_con_inventario", 0))),
        (f"Recibos emitidos ({periodo})", str(mes.get("n_recibos", 0))),
        ("Monto emitido", money(mes.get("emitido", 0))),
        ("Monto cobrado", money(mes.get("cobrado", 0))),
        ("Saldo pendiente", money(mes.get("pendiente", 0))),
        ("% cobranza del mes", f"{mes.get('pct_cobranza', 0)}%"),
    ]


def generar_dashboard_pdf(data: dict, branding: dict | None = None) -> bytes:
    branding = branding or {}
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
        title="Dashboard de Reportes",
    )
    base = getSampleStyleSheet()
    est_h1 = ParagraphStyle("h1", parent=base["Heading1"], fontName="Helvetica-Bold",
                            fontSize=18, textColor=COLOR_PRIMARY, spaceAfter=6)
    est_norm = ParagraphStyle("norm", fontName="Helvetica", fontSize=10, leading=13)

    nombre_muni = (branding.get("nombre_municipalidad") or "").strip()
    story = [
        Paragraph("Dashboard de Reportes" + (f" — {nombre_muni}" if nombre_muni else ""), est_h1),
        Paragraph(f"Generado el {date.today().strftime('%d/%m/%Y')}", est_norm),
        Spacer(1, 8 * mm),
    ]

    tabla_data = [["Indicador", "Valor"]]
    for k, v in _kpi_rows(data):
        tabla_data.append([k, v])

    tabla = Table(tabla_data, colWidths=[110 * mm, 60 * mm])
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("ALIGN", (1, 1), (1, -1), "RIGHT"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COLOR_CARD_BG]),
        ("GRID", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(tabla)

    doc.build(story)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes
