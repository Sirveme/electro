"""
Middleware CSRF doble-submit.

- GET / HEAD / OPTIONS: si no existe la cookie _csrf, la setea con un token nuevo.
- POST / PUT / PATCH / DELETE: compara cookie vs form field _csrf. Si difiere, 403.

Excepciones (no requieren validación):
- Si la request no tiene Content-Type form-urlencoded ni multipart, se valida igual SOLO si es modificadora;
  pero permitimos POST de application/json siempre que traigan el header X-CSRF-Token coincidente con la cookie.

NOTA: las requests OPTIONS, GET, HEAD nunca se validan (seguras según RFC).
"""
import logging
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, PlainTextResponse

from app.config import settings
from app.services.csrf import CSRF_COOKIE_NAME, CSRF_FORM_FIELD, generate_token, verify_pair

logger = logging.getLogger(__name__)

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        cookie_val = request.cookies.get(CSRF_COOKIE_NAME)

        if request.method in SAFE_METHODS:
            response = await call_next(request)
            if not cookie_val:
                new_token = generate_token()
                response.set_cookie(
                    key=CSRF_COOKIE_NAME,
                    value=new_token,
                    max_age=settings.SESSION_MAX_AGE_SECONDS,
                    httponly=False,  # debe ser leíble por JS para que HTMX/forms lo manden si quieren
                    samesite="lax",
                    secure=(settings.ENVIRONMENT == "production"),
                    path="/",
                )
            return response

        # Métodos modificadores: validar
        form_val: str | None = None
        ctype = request.headers.get("content-type", "")

        if "application/x-www-form-urlencoded" in ctype or "multipart/form-data" in ctype:
            form_data = await request.form()
            form_val = form_data.get(CSRF_FORM_FIELD)
            # Reinyectar el body para que la ruta destino lo vuelva a leer
            request._form = form_data  # type: ignore[attr-defined]
        else:
            form_val = request.headers.get("X-CSRF-Token")

        if not verify_pair(cookie_val, form_val):
            logger.warning(
                "CSRF mismatch on %s %s (cookie=%s form=%s)",
                request.method, request.url.path,
                bool(cookie_val), bool(form_val),
            )
            return PlainTextResponse("CSRF inválido o ausente.", status_code=403)

        return await call_next(request)
