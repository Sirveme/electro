"""
Sistema de flash messages basado en request.session.

Tipos válidos: success, error, warning, info.
"""
from typing import Literal

from fastapi import Request

FlashType = Literal["success", "error", "warning", "info"]

_KEY = "_flashes"


def set_flash(request: Request, tipo: FlashType, texto: str) -> None:
    flashes = request.session.get(_KEY, [])
    flashes.append({"tipo": tipo, "texto": texto})
    request.session[_KEY] = flashes


def pop_flashes(request: Request) -> list[dict]:
    flashes = request.session.pop(_KEY, [])
    return flashes
