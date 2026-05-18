import re

UBIGEO_RE = re.compile(r"^\d{6}$")


class UbigeoError(ValueError):
    pass


def normalizar_ubigeo(raw: str) -> str:
    """Quita espacios y valida que sean 6 dígitos. Lanza UbigeoError si no es válido."""
    if raw is None:
        raise UbigeoError("UBIGEO vacío")
    s = str(raw).strip()
    if not UBIGEO_RE.match(s):
        raise UbigeoError(f"UBIGEO inválido: '{raw}' (debe ser 6 dígitos)")
    return s


def schema_for_ubigeo(ubigeo: str) -> str:
    """Retorna el nombre del schema PostgreSQL para un UBIGEO."""
    return f"muni_{normalizar_ubigeo(ubigeo)}"
