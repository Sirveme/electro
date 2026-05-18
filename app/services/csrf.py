"""
CSRF doble-submit token.

- generate_token() crea un nuevo token urlsafe de 32 bytes (~43 chars).
- verify_pair() compara cookie vs valor del form con hmac.compare_digest.
"""
import hmac
import secrets

CSRF_COOKIE_NAME = "_csrf"
CSRF_FORM_FIELD = "_csrf"


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def verify_pair(cookie_val: str | None, form_val: str | None) -> bool:
    if not cookie_val or not form_val:
        return False
    return hmac.compare_digest(cookie_val, form_val)
