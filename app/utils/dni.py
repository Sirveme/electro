import re

DNI_RE = re.compile(r"^\d{8}$")


class DniInvalido(ValueError):
    pass


def validar_dni(raw: str) -> str:
    """Normaliza y valida un DNI peruano (8 dígitos). Lanza DniInvalido si no cumple."""
    if raw is None:
        raise DniInvalido("DNI vacío")
    s = str(raw).strip()
    if not DNI_RE.match(s):
        raise DniInvalido(f"DNI inválido: '{raw}' (debe ser 8 dígitos)")
    if s == "00000000":
        raise DniInvalido("DNI no puede ser todo ceros")
    return s


def es_dni_valido(raw: str | None) -> bool:
    try:
        validar_dni(raw or "")
        return True
    except DniInvalido:
        return False
