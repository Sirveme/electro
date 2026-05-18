from jinja2 import Environment


def _puede(user, modulo: str, opcion: str, accion: str = "ver") -> bool:
    """Filtro Jinja: {{ ctx.user | puede('padron', 'viviendas', 'crear') }}"""
    if user is None:
        return False
    if getattr(user, "is_superadmin", False):
        return True
    if not hasattr(user, "puede"):
        return False
    return user.puede(modulo, opcion, accion)


def register_filters(env: Environment) -> None:
    env.filters["puede"] = _puede
