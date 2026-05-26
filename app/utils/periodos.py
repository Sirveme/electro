"""
Utilidades de fechas y periodos de facturación.

Convención del proyecto:
- Periodo facturado = mes que termina (ejecutar el 30/junio factura junio).
- Vencimiento = último día del mes SIGUIENTE al periodo.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date


MESES_ES = {
    1: "Enero",  2: "Febrero",  3: "Marzo",     4: "Abril",
    5: "Mayo",   6: "Junio",    7: "Julio",     8: "Agosto",
    9: "Setiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}

MES_ABREV_ES = {
    1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr",  5: "May",  6: "Jun",
    7: "Jul", 8: "Ago", 9: "Set", 10: "Oct", 11: "Nov", 12: "Dic",
}


def ultimo_dia_del_mes(anio: int, mes: int) -> date:
    return date(anio, mes, monthrange(anio, mes)[1])


def primer_dia_del_mes(anio: int, mes: int) -> date:
    return date(anio, mes, 1)


def mes_siguiente(anio: int, mes: int) -> tuple[int, int]:
    if mes == 12:
        return (anio + 1, 1)
    return (anio, mes + 1)


def vencimiento_por_periodo(anio: int, mes: int) -> date:
    """Último día del mes siguiente al periodo facturado."""
    a2, m2 = mes_siguiente(anio, mes)
    return ultimo_dia_del_mes(a2, m2)


def nombre_periodo(anio: int, mes: int) -> str:
    """Devuelve 'Jun 2026'."""
    return f"{MES_ABREV_ES.get(mes, str(mes))} {anio}"


def nombre_periodo_largo(anio: int, mes: int) -> str:
    """Devuelve 'Junio 2026'."""
    return f"{MESES_ES.get(mes, str(mes))} {anio}"


def periodo_actual_a_facturar(hoy: date | None = None) -> tuple[int, int]:
    """
    Periodo que se factura HOY. Si hoy está dentro del mes, asume que se factura
    ese mes (a fin de mes). Equivalente a (hoy.year, hoy.month).
    """
    h = hoy or date.today()
    return (h.year, h.month)
