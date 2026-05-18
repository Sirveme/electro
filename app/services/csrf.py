"""
app/services/csrf.py

Protección CSRF por doble-submit cookie, implementada como Dependency de FastAPI.

Por qué dependency y no middleware:
- Un middleware que lea request.form() o request.body() consume el stream ASGI.
- Starlette no rebobina automáticamente, así que cuando FastAPI parsea los
  Form(...) de la ruta, encuentra el body vacío → 422 Unprocessable Content.
- Como dependency, FastAPI parsea el form UNA sola vez y todos los campos
  (incluido _csrf) llegan correctamente.

Uso en rutas:

    from app.services.csrf import verify_csrf, ensure_csrf_cookie

    @router.get("/login")
    async def login_form(request: Request):
        response = templates.TemplateResponse(...)
        ensure_csrf_cookie(request, response)
        return response

    @router.post("/login", dependencies=[Depends(verify_csrf)])
    async def login_submit(usuario: str = Form(...), password: str = Form(...)):
        ...
"""

import logging
import secrets

from fastapi import Form, HTTPException, Request, Response

logger = logging.getLogger(__name__)

CSRF_COOKIE_NAME = "_csrf"
TOKEN_BYTES = 32
COOKIE_MAX_AGE = 60 * 60 * 8  # 8 horas, alineado con la sesión


def generate_token() -> str:
    """Genera un token CSRF urlsafe de 32 bytes (~43 caracteres)."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def ensure_csrf_cookie(request: Request, response: Response) -> str:
    """
    Si la request no trae cookie _csrf, genera una nueva y la setea en la response.
    Retorna el token vigente para que el caller pueda inyectarlo en plantillas.

    Llamar en GETs que renderizan formularios (login, wizards, etc.).
    """
    token = request.cookies.get(CSRF_COOKIE_NAME)
    if not token:
        token = generate_token()
        response.set_cookie(
            CSRF_COOKIE_NAME,
            token,
            max_age=COOKIE_MAX_AGE,
            httponly=False,
            samesite="lax",
            secure=False,  # cambiar a True cuando aseguremos HTTPS estricto en prod
        )
    return token


async def verify_csrf(
    request: Request,
    _csrf: str = Form(...),
) -> None:
    """
    Dependency para rutas POST/PUT/PATCH/DELETE.
    Valida que el campo _csrf del form coincida con la cookie _csrf.

    Lanza 403 si:
    - No hay cookie _csrf
    - El form no incluye _csrf
    - Los valores no coinciden
    """
    cookie_val = request.cookies.get(CSRF_COOKIE_NAME, "")
    if not cookie_val or not _csrf or cookie_val != _csrf:
        logger.warning(
            "CSRF invalido: path=%s cookie_presente=%s form_presente=%s",
            request.url.path,
            bool(cookie_val),
            bool(_csrf),
        )
        raise HTTPException(status_code=403, detail="Token CSRF invalido")
