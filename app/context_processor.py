from typing import Optional
from fastapi import Request

from app.dependencies import CurrentUser
from app.services.csrf import CSRF_COOKIE_NAME
from app.utils.flash import pop_flashes


def build_context(
    request: Request,
    user: Optional[CurrentUser] = None,
    **extra,
) -> dict:
    """
    Construye el contexto base que se inyecta a TODOS los templates Jinja.
    Uso en una ruta:
        return templates.TemplateResponse("foo.html", build_context(request, user=user, ...))
    """
    # Prioridad: request.state (token generado en este request por el middleware)
    # fallback: cookie existente (request con cookie previa)
    csrf_token = getattr(request.state, "csrf_token", None) or request.cookies.get(CSRF_COOKIE_NAME, "")
    flashes = pop_flashes(request) if hasattr(request, "session") else []
    ctx = {
        "request": request,
        "ctx": {
            "user": user,
            "tenant_schema": user.tenant_schema if user else None,
            "is_superadmin": bool(user and user.is_superadmin),
            "is_tenant": bool(user and user.is_tenant),
            "permisos": user.permisos if user else [],
            "perfil_codigo": user.perfil_codigo if user else None,
            "csrf_token": csrf_token,
            "flashes": flashes,
        },
        "flashes": flashes,
    }
    ctx.update(extra)
    return ctx
