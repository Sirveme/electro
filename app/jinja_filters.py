from datetime import datetime

from jinja2 import Environment

from app.utils.timezone import format_lima


def _puede(user, modulo: str, opcion: str, accion: str = "ver") -> bool:
    """Filtro Jinja: {{ ctx.user | puede('padron', 'viviendas', 'crear') }}"""
    if user is None:
        return False
    if getattr(user, "is_superadmin", False):
        return True
    if not hasattr(user, "puede"):
        return False
    return user.puede(modulo, opcion, accion)


def _fmt_lima(value, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Filtro Jinja: {{ caja.abierta_at | fmt_lima }}.

    Convierte un datetime (aware o naive) a hora Lima. Si el valor es None,
    devuelve "—". Si Python recibe un TIMESTAMPTZ de Postgres en UTC, este
    filtro lo presenta en hora local del cliente final.
    """
    if value is None:
        return "—"
    if not isinstance(value, datetime):
        return str(value)
    return format_lima(value, fmt)


def register_filters(env: Environment) -> None:
    env.filters["puede"] = _puede
    env.filters["fmt_lima"] = _fmt_lima
