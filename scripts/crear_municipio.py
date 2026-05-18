"""
CLI: provisiona un municipio.

Uso:
    python -m scripts.crear_municipio --ubigeo 160101 --nombre "Iquitos" \
        --departamento Loreto --provincia Maynas --distrito Iquitos \
        --admin-dni 12345678 --admin-nombre "Juan Pérez" \
        --superadmin-id 1
"""
import argparse
import getpass
import logging
import sys

from app.config import settings
from app.services.tenant_provisioning import ProvisioningError, crear_municipio

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Provisión de un municipio")
    parser.add_argument("--ubigeo", required=True, help="UBIGEO INEI (6 dígitos)")
    parser.add_argument("--nombre", required=True)
    parser.add_argument("--departamento", default=None)
    parser.add_argument("--provincia", default=None)
    parser.add_argument("--distrito", default=None)
    parser.add_argument("--admin-dni", required=True)
    parser.add_argument("--admin-nombre", required=True)
    parser.add_argument("--admin-email", default=None)
    parser.add_argument("--admin-telefono", default=None)
    parser.add_argument("--admin-password", default=None,
                        help="Si se omite, se pide por prompt seguro")
    parser.add_argument("--superadmin-id", type=int, required=True,
                        help="ID del superadmin que está creando el municipio")
    parser.add_argument("--plan", default="demo")
    parser.add_argument("--precio-mensual", type=float, default=None)
    args = parser.parse_args()

    password = args.admin_password or getpass.getpass("Contraseña inicial del admin del municipio: ")
    if not password:
        print("ERROR: contraseña requerida.", file=sys.stderr)
        return 2

    try:
        result = crear_municipio(
            db_url_sync=settings.DATABASE_URL_SYNC,
            ubigeo=args.ubigeo,
            nombre=args.nombre,
            departamento=args.departamento,
            provincia=args.provincia,
            distrito=args.distrito,
            admin_dni=args.admin_dni,
            admin_nombre=args.admin_nombre,
            admin_email=args.admin_email,
            admin_telefono=args.admin_telefono,
            responsable_telefono=args.admin_telefono,
            admin_password=password,
            creado_por_superadmin_id=args.superadmin_id,
            plan=args.plan,
            precio_mensual=args.precio_mensual,
        )
    except ProvisioningError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(
        "OK Municipio creado:\n"
        f"  municipio_id   = {result['municipio_id']}\n"
        f"  suscripcion_id = {result['suscripcion_id']}\n"
        f"  schema_name    = {result['schema_name']}\n"
        f"  admin_user_id  = {result['admin_user_id']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
