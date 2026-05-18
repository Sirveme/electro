"""
CLI para aplicar migraciones.

Uso:
    python -m scripts.ejecutar_migracion --target public
    python -m scripts.ejecutar_migracion --target tenant --schema muni_160101
"""
import argparse
import logging
import sys

from app.config import settings
from app.services.migrations import (
    aplicar_migraciones_public,
    aplicar_migraciones_tenant,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Aplicar migraciones SQL versionadas")
    parser.add_argument("--target", choices=["public", "tenant"], required=True)
    parser.add_argument("--schema", help="Nombre del schema (requerido si target=tenant)")
    args = parser.parse_args()

    if args.target == "public":
        aplicadas = aplicar_migraciones_public(settings.DATABASE_URL_SYNC)
    else:
        if not args.schema:
            print("ERROR: --schema es requerido cuando --target=tenant", file=sys.stderr)
            return 2
        aplicadas = aplicar_migraciones_tenant(settings.DATABASE_URL_SYNC, args.schema)

    if aplicadas:
        print(f"Aplicadas {len(aplicadas)} migracion(es):")
        for nombre in aplicadas:
            print(f"  - {nombre}")
    else:
        print("Sin migraciones pendientes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
