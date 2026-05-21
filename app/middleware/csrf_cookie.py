"""
app/middleware/csrf_cookie.py

Middleware ligero que asegura la cookie _csrf en cada request.

IMPORTANTE - Por qué este middleware NO rompe los Form (a diferencia del
intento anterior de CSRF middleware):

- NO lee request.body() ni request.form()
- Solo lee cookies (esto es seguro y no consume el stream ASGI)
- Solo setea cookies en la response (también seguro)

El dependency verify_csrf en app/services/csrf.py sigue siendo la fuente
de verdad para validar tokens en POSTs. Este middleware solo se encarga
de generar el token y propagarlo al template a tiempo (vía request.state),
para que el <input hidden> tenga el valor correcto cuando se renderiza.

Flujo completo:

1. Request entra. Middleware ve si hay cookie _csrf.
2. Si NO hay, genera token nuevo, lo pone en request.state.csrf_token.
3. Si SÍ hay, copia su valor a request.state.csrf_token.
4. La request llega a la ruta. La ruta renderiza un template.
5. build_context() lee request.state.csrf_token y lo inyecta en ctx.
6. Template renderiza <input value="{{ ctx.csrf_token }}"> con valor real.
7. Después del render, middleware setea la cookie en la response
   (solo si era una request sin cookie previa).
8. Browser recibe HTML con valor de _csrf y la cookie con el mismo valor.
9. Al hacer POST, ambos coinciden, verify_csrf lo valida.
"""

import logging
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger(__name__)

CSRF_COOKIE_NAME = "_csrf"
COOKIE_MAX_AGE = 60 * 60 * 8  # 8 horas, alineado con la sesión


class CSRFCookieMiddleware(BaseHTTPMiddleware):
    """
    Garantiza que cada request tenga acceso a un token CSRF vía
    request.state.csrf_token, y que la cookie _csrf esté seteada
    en la response cuando sea necesario.
    """

    async def dispatch(self, request: Request, call_next):
        existing = request.cookies.get(CSRF_COOKIE_NAME)

        if existing:
            # Ya hay cookie. Solo propagamos su valor a state para
            # que build_context lo pueda leer durante el render.
            request.state.csrf_token = existing
            response = await call_next(request)
            return response

        # No hay cookie. Generamos token nuevo ANTES del render
        # para que el template ya tenga el valor correcto.
        new_token = secrets.token_urlsafe(32)
        request.state.csrf_token = new_token

        response = await call_next(request)

        # Después del render, setear la cookie en la response.
        response.set_cookie(
            CSRF_COOKIE_NAME,
            new_token,
            max_age=COOKIE_MAX_AGE,
            httponly=False,
            samesite="lax",
            secure=False,  # cambiar a True cuando se asegure HTTPS estricto en prod
        )

        return response
