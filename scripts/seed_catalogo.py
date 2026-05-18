"""
Siembra public.artefacto_catalogo con artefactos típicos.

Uso:
    python -m scripts.seed_catalogo
"""
import logging
import sys

import psycopg2

from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)


CATALOGO = [
    ("REFRIG",        "Refrigeradora",            "refrigeracion",   "❄️",  8.00, 10),
    ("CONGEL",        "Congeladora",              "refrigeracion",   "🧊", 12.00, 11),
    ("TV_LED",        "Televisor LED",            "entretenimiento", "📺",  3.00, 20),
    ("TV_TUBO",       "Televisor de tubo",        "entretenimiento", "📺",  4.00, 21),
    ("EQUIPO_SONIDO", "Equipo de sonido",         "entretenimiento", "🎵",  2.00, 22),
    ("RADIO",         "Radio",                    "entretenimiento", "📻",  0.50, 23),
    ("COMPUTADORA",   "Computadora de escritorio","entretenimiento", "🖥️",  3.00, 24),
    ("LAPTOP",        "Laptop",                   "entretenimiento", "💻",  1.50, 25),
    ("FOCO_AHORRO",   "Foco ahorrador / LED",     "iluminacion",     "💡",  0.30, 30),
    ("FOCO_INCAND",   "Foco incandescente",       "iluminacion",     "💡",  1.00, 31),
    ("FLUORESCENTE",  "Tubo fluorescente",        "iluminacion",     "💡",  0.80, 32),
    ("VENTILADOR",    "Ventilador",               "climatizacion",   "🌀",  2.00, 40),
    ("AIRE_ACOND",    "Aire acondicionado",       "climatizacion",   "❄️", 25.00, 41),
    ("LICUADORA",     "Licuadora",                "coccion",         "🥤",  1.00, 50),
    ("MICROONDAS",    "Microondas",               "coccion",         "📡",  4.00, 51),
    ("HORNO_ELEC",    "Horno eléctrico",          "coccion",         "🍞",  6.00, 52),
    ("OLLA_ARROCERA", "Olla arrocera",            "coccion",         "🍚",  1.50, 53),
    ("CAFETERA",      "Cafetera",                 "coccion",         "☕",  0.80, 54),
    ("HERVIDOR",      "Hervidor eléctrico",       "coccion",         "🫖",  0.80, 55),
    ("PLANCHA",       "Plancha",                  "lavado",          "👕",  1.50, 60),
    ("LAVADORA",      "Lavadora",                 "lavado",          "🧺",  5.00, 61),
    ("BOMBA_AGUA",    "Bomba de agua",            "herramientas",    "🚰",  6.00, 70),
    ("TALADRO",       "Taladro",                  "herramientas",    "🔧",  0.50, 71),
    ("CARGADOR_CEL",  "Cargador de celular",      "otros",           "🔌",  0.20, 90),
    ("OTROS",         "Otro artefacto",           "otros",           "❓",  1.00, 99),
]


def main() -> int:
    conn = psycopg2.connect(settings.DATABASE_URL_SYNC)
    conn.autocommit = False
    insertados = 0
    actualizados = 0
    try:
        with conn.cursor() as cur:
            for codigo, nombre, categoria, icono, tarifa, orden in CATALOGO:
                cur.execute(
                    """
                    INSERT INTO public.artefacto_catalogo
                        (codigo, nombre, categoria, icono, tarifa_sugerida, activo_default, orden)
                    VALUES (%s, %s, %s, %s, %s, TRUE, %s)
                    ON CONFLICT (codigo) DO UPDATE SET
                        nombre = EXCLUDED.nombre,
                        categoria = EXCLUDED.categoria,
                        icono = EXCLUDED.icono,
                        tarifa_sugerida = EXCLUDED.tarifa_sugerida,
                        orden = EXCLUDED.orden
                    RETURNING (xmax = 0) AS inserted
                    """,
                    (codigo, nombre, categoria, icono, tarifa, orden),
                )
                inserted = cur.fetchone()[0]
                if inserted:
                    insertados += 1
                else:
                    actualizados += 1
        conn.commit()
        logger.info("Catálogo sembrado: %d insertados, %d actualizados", insertados, actualizados)
        return 0
    except Exception:
        conn.rollback()
        logger.exception("Error sembrando catálogo — rollback")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
