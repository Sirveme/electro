import hmac
import logging
import secrets
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

logger = logging.getLogger(__name__)

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash de password usando Argon2id (parámetros por defecto del PasswordHasher)."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verifica password contra su hash Argon2. Retorna False si no coincide."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, Exception) as exc:
        logger.debug("verify_password fallido: %s", exc.__class__.__name__)
        return False


def needs_rehash(password_hash: str) -> bool:
    """Indica si el hash debería re-generarse (cambió la política Argon2)."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except Exception:
        return False


def generate_csrf_token() -> str:
    """Genera un token CSRF de 32 bytes hex."""
    return secrets.token_hex(32)


def verify_csrf_token(cookie_token: str | None, form_token: str | None) -> bool:
    """Compara tokens con comparación de tiempo constante."""
    if not cookie_token or not form_token:
        return False
    return hmac.compare_digest(cookie_token, form_token)
