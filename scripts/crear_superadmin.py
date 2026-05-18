"""
CLI interactivo: crea un superadmin en public.superadmin_users.

Uso:
    python -m scripts.crear_superadmin
"""
import getpass
import logging
import re
import sys

import psycopg2

from app.config import settings
from app.security import hash_password

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_RE = re.compile(r"^[a-z0-9_]{3,40}$")


def _prompt_nonempty(label: str) -> str:
    while True:
        v = input(f"{label}: ").strip()
        if v:
            return v
        print("  ⚠ No puede estar vacío.")


def _prompt_username() -> str:
    while True:
        v = input("Username (a-z, 0-9, _; 3-40): ").strip().lower()
        if USERNAME_RE.match(v):
            return v
        print("  ⚠ Username inválido.")


def _prompt_email() -> str:
    while True:
        v = input("Email: ").strip().lower()
        if EMAIL_RE.match(v):
            return v
        print("  ⚠ Email inválido.")


def _prompt_password() -> str:
    while True:
        p1 = getpass.getpass("Contraseña (mín 8): ")
        if len(p1) < 8:
            print("  ⚠ Mínimo 8 caracteres.")
            continue
        p2 = getpass.getpass("Repetir contraseña: ")
        if p1 != p2:
            print("  ⚠ No coinciden.")
            continue
        return p1


def main() -> int:
    print("== Crear superadmin de electro.perusistemas.pro ==")
    username = _prompt_username()
    email = _prompt_email()
    nombre = _prompt_nonempty("Nombre completo")
    password = _prompt_password()
    access_code = hash_password(password)

    conn = psycopg2.connect(settings.DATABASE_URL_SYNC)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM public.superadmin_users WHERE username = %s OR email = %s",
                (username, email),
            )
            if cur.fetchone():
                print("ERROR: ya existe un superadmin con ese username o email.")
                return 2

            cur.execute(
                """
                INSERT INTO public.superadmin_users (username, email, nombre, access_code, activo)
                VALUES (%s, %s, %s, %s, TRUE)
                RETURNING id
                """,
                (username, email, nombre, access_code),
            )
            new_id = cur.fetchone()[0]
        conn.commit()
        print(f"OK Superadmin creado (id={new_id}).")
        return 0
    except Exception as exc:
        conn.rollback()
        logger.exception("Error creando superadmin")
        print(f"ERROR: {exc}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
