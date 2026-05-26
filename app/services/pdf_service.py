"""
Generación de PDFs (recibo y comprobante de pago) en formato media carta.

Estrategia:
- Intentamos WeasyPrint primero (HTML+CSS, mejor presentación).
- Si las libs nativas no están disponibles (Cairo/Pango/GDK), caemos a ReportLab.
- La elección se hace en cold-start y se cachea en este módulo.
"""
from __future__ import annotations

import io
import logging
from typing import Any

logger = logging.getLogger(__name__)

_RENDERER: "PdfRenderer | None" = None
_RENDERER_KIND: str = "none"


def render_template(env, name: str, context: dict) -> str:
    """Renderiza una plantilla Jinja del proyecto. `env` es jinja2.Environment."""
    template = env.get_template(name)
    return template.render(**context)


class PdfRenderer:
    kind: str = "abstract"

    def render_recibo(self, env, ctx: dict[str, Any]) -> bytes:
        raise NotImplementedError

    def render_comprobante_pago(self, env, ctx: dict[str, Any]) -> bytes:
        raise NotImplementedError

    def render_html_to_pdf(self, html: str) -> bytes:
        raise NotImplementedError


class WeasyPrintRenderer(PdfRenderer):
    kind = "weasyprint"

    def __init__(self) -> None:
        from weasyprint import HTML  # noqa
        self._HTML = HTML

    def render_recibo(self, env, ctx: dict[str, Any]) -> bytes:
        html = render_template(env, "tenant/recibos_pdf/recibo.html", ctx)
        return self._HTML(string=html, base_url=".").write_pdf()

    def render_comprobante_pago(self, env, ctx: dict[str, Any]) -> bytes:
        html = render_template(env, "tenant/recibos_pdf/comprobante_pago.html", ctx)
        return self._HTML(string=html, base_url=".").write_pdf()

    def render_html_to_pdf(self, html: str) -> bytes:
        return self._HTML(string=html, base_url=".").write_pdf()


class ReportLabRenderer(PdfRenderer):
    kind = "reportlab"

    def __init__(self) -> None:
        from reportlab.lib.pagesizes import letter  # noqa
        from reportlab.pdfgen import canvas  # noqa
        self._canvas = canvas
        self._letter = letter

    def _draw_kv(self, c, x: float, y: float, k: str, v: str) -> float:
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x, y, k)
        c.setFont("Helvetica", 9)
        c.drawString(x + 110, y, v)
        return y - 14

    def render_recibo(self, env, ctx: dict[str, Any]) -> bytes:
        buf = io.BytesIO()
        # Media carta = letter[0]/2 horizontal aprox; usamos letter completo dividido a la mitad
        from reportlab.lib.pagesizes import letter as _letter
        page_w, page_h = _letter
        media_w, media_h = page_w, page_h / 2.0
        c = self._canvas.Canvas(buf, pagesize=(media_w, media_h))

        muni = ctx.get("municipio_nombre") or "Municipio"
        cuota = ctx["cuota"]
        vivienda = ctx.get("vivienda") or {}
        moradores = ctx.get("moradores") or []
        detalle_aparatos = cuota.get("detalle_aparatos_json") or []

        c.setFont("Helvetica-Bold", 14)
        c.drawString(20, media_h - 25, f"RECIBO  N° {cuota['numero_recibo']}")
        c.setFont("Helvetica", 9)
        c.drawString(20, media_h - 40, muni)
        c.drawString(20, media_h - 52, f"Periodo: {ctx.get('periodo_label', '')}")
        c.drawString(20, media_h - 64, f"Emisión: {cuota['fecha_emision']}    Vto: {cuota['fecha_vencimiento']}")

        y = media_h - 90
        y = self._draw_kv(c, 20, y, "Vivienda:", str(vivienda.get("codigo_interno") or ""))
        y = self._draw_kv(c, 20, y, "Comunidad:", str(vivienda.get("comunidad_nombre") or ""))
        if moradores:
            y = self._draw_kv(c, 20, y, "Titular:", str(moradores[0].get("nombre_completo") or ""))

        y -= 6
        c.setFont("Helvetica-Bold", 10)
        c.drawString(20, y, "DETALLE")
        y -= 14
        y = self._draw_kv(c, 20, y, "Cargo fijo:", f"S/ {cuota['cargo_fijo']:.2f}")
        y = self._draw_kv(c, 20, y, f"Adicional moradores ({cuota['n_moradores']}):", f"S/ {cuota['adicional_morador']:.2f}")
        for ap in detalle_aparatos:
            label = f"{ap.get('nombre','')} x{ap.get('cantidad',0)}"
            y = self._draw_kv(c, 20, y, label, f"S/ {float(ap.get('importe',0)):.2f}")

        y -= 4
        y = self._draw_kv(c, 20, y, "Subtotal:", f"S/ {cuota['subtotal']:.2f}")
        if cuota.get("subsidio_id"):
            y = self._draw_kv(
                c, 20, y,
                f"Subsidio {cuota['subsidio_porcentaje']}% ({cuota['subsidio_nombre']}):",
                f"- S/ {cuota['subsidio_monto']:.2f}",
            )
        c.setFont("Helvetica-Bold", 12)
        c.drawString(20, y - 4, f"TOTAL A PAGAR:  S/ {cuota['total']:.2f}")

        c.setFont("Helvetica-Oblique", 7)
        c.drawString(20, 14, "Documento informativo. No es comprobante de pago.")

        c.showPage()
        c.save()
        return buf.getvalue()

    def render_comprobante_pago(self, env, ctx: dict[str, Any]) -> bytes:
        buf = io.BytesIO()
        from reportlab.lib.pagesizes import letter as _letter
        page_w, page_h = _letter
        media_w, media_h = page_w, page_h / 2.0
        c = self._canvas.Canvas(buf, pagesize=(media_w, media_h))

        pago = ctx["pago"]
        cuota = ctx["cuota"]
        muni = ctx.get("municipio_nombre") or "Municipio"
        vivienda = ctx.get("vivienda") or {}
        cajero = ctx.get("cajero_nombre") or ""

        c.setFont("Helvetica-Bold", 14)
        c.drawString(20, media_h - 25, f"COMPROBANTE DE PAGO  #{pago['id']:06d}")
        c.setFont("Helvetica", 9)
        c.drawString(20, media_h - 40, muni)
        c.drawString(20, media_h - 52, f"Fecha: {pago['fecha_pago']}")

        y = media_h - 80
        y = self._draw_kv(c, 20, y, "Recibo:", str(cuota.get("numero_recibo") or ""))
        y = self._draw_kv(c, 20, y, "Periodo:", str(ctx.get("periodo_label", "")))
        y = self._draw_kv(c, 20, y, "Vivienda:", str(vivienda.get("codigo_interno") or ""))
        y = self._draw_kv(c, 20, y, "Comunidad:", str(vivienda.get("comunidad_nombre") or ""))
        y = self._draw_kv(c, 20, y, "Método:", str(pago.get("metodo") or "efectivo"))
        if pago.get("referencia_externa"):
            y = self._draw_kv(c, 20, y, "Referencia:", str(pago["referencia_externa"]))
        y = self._draw_kv(c, 20, y, "Cajero:", cajero)

        y -= 6
        c.setFont("Helvetica-Bold", 12)
        c.drawString(20, y, f"MONTO COBRADO:  S/ {float(pago['monto']):.2f}")
        y -= 16
        c.setFont("Helvetica", 9)
        c.drawString(20, y, f"Total del recibo: S/ {float(cuota['total']):.2f}")
        y -= 12
        c.drawString(20, y, f"Pagado acumulado: S/ {float(cuota['monto_pagado']):.2f}")
        y -= 12
        c.drawString(20, y, f"Saldo pendiente:  S/ {float(cuota['saldo_pendiente']):.2f}")

        if pago.get("observaciones"):
            y -= 16
            c.setFont("Helvetica-Oblique", 8)
            c.drawString(20, y, f"Obs: {pago['observaciones']}")

        c.setFont("Helvetica-Oblique", 7)
        c.drawString(20, 14, "Comprobante interno. Conserve este documento.")

        c.showPage()
        c.save()
        return buf.getvalue()

    def render_html_to_pdf(self, html: str) -> bytes:
        """
        Fallback simple cuando WeasyPrint no está disponible:
        extrae el texto plano del HTML y lo imprime en una hoja carta.
        Suficiente para que los reportes "siempre" exporten algo.
        """
        from html.parser import HTMLParser
        from reportlab.lib.pagesizes import letter as _letter

        class TextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.lines: list[str] = []
                self._skip_depth = 0
                self._buf: list[str] = []

            def handle_starttag(self, tag, attrs):
                if tag in ("script", "style"):
                    self._skip_depth += 1
                if tag in ("br", "tr", "li", "p", "h1", "h2", "h3", "div"):
                    self._flush()

            def handle_endtag(self, tag):
                if tag in ("script", "style") and self._skip_depth > 0:
                    self._skip_depth -= 1
                if tag in ("tr", "li", "p", "h1", "h2", "h3", "div"):
                    self._flush()

            def handle_data(self, data):
                if self._skip_depth > 0:
                    return
                if data.strip():
                    self._buf.append(data.strip())

            def _flush(self):
                if self._buf:
                    self.lines.append(" ".join(self._buf))
                    self._buf = []

        parser = TextExtractor()
        parser.feed(html)
        parser._flush()

        buf = io.BytesIO()
        page_w, page_h = _letter
        c = self._canvas.Canvas(buf, pagesize=_letter)
        y = page_h - 40
        c.setFont("Helvetica", 9)
        for line in parser.lines:
            for chunk_start in range(0, len(line), 110):
                c.drawString(40, y, line[chunk_start:chunk_start + 110])
                y -= 12
                if y < 40:
                    c.showPage()
                    c.setFont("Helvetica", 9)
                    y = page_h - 40
        c.save()
        return buf.getvalue()


def get_pdf_renderer() -> PdfRenderer:
    """Resuelve y cachea el renderer. Prioriza WeasyPrint."""
    global _RENDERER, _RENDERER_KIND
    if _RENDERER is not None:
        return _RENDERER
    try:
        _RENDERER = WeasyPrintRenderer()
        _RENDERER_KIND = "weasyprint"
        logger.info("PDF renderer: WeasyPrint OK")
        return _RENDERER
    except Exception as exc:
        logger.warning("WeasyPrint no disponible (%s) — uso ReportLab.", exc)
    try:
        _RENDERER = ReportLabRenderer()
        _RENDERER_KIND = "reportlab"
        logger.info("PDF renderer: ReportLab OK")
        return _RENDERER
    except Exception as exc:
        logger.exception("Ningún renderer PDF disponible: %s", exc)
        raise RuntimeError("No hay backend PDF instalado (weasyprint o reportlab).") from exc


def renderer_kind() -> str:
    """Para diagnóstico: cuál se está usando."""
    return _RENDERER_KIND
