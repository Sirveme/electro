"""
Siembra public.permisos y public.perfiles_plantilla.

Uso:
    python -m scripts.seed_permisos
"""
import logging
import sys

import psycopg2

from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)


PERMISOS: list[tuple[str, str, str, str, str]] = [
    # (codigo, modulo, opcion, accion, descripcion)
    ("padron.viviendas.ver",          "padron",     "viviendas",        "ver",      "Ver listado de viviendas"),
    ("padron.viviendas.crear",        "padron",     "viviendas",        "crear",    "Crear vivienda nueva"),
    ("padron.viviendas.editar",       "padron",     "viviendas",        "editar",   "Editar datos de vivienda"),
    ("padron.viviendas.eliminar",     "padron",     "viviendas",        "eliminar", "Eliminar / desactivar vivienda"),
    ("padron.moradores.ver",          "padron",     "moradores",        "ver",      "Ver moradores de una vivienda"),
    ("padron.moradores.crear",        "padron",     "moradores",        "crear",    "Agregar morador"),
    ("padron.moradores.editar",       "padron",     "moradores",        "editar",   "Editar morador"),
    ("padron.referentes.ver",         "padron",     "referentes",       "ver",      "Ver referentes comunitarios"),
    ("padron.referentes.editar",      "padron",     "referentes",       "editar",   "Crear / editar referentes"),
    ("padron.comunidades.ver",        "padron",     "comunidades",      "ver",      "Ver comunidades"),
    ("padron.comunidades.editar",     "padron",     "comunidades",      "editar",   "Crear / editar comunidades"),

    ("inventario.ver",                "inventario", "ver",              "ver",      "Ver inventario de artefactos"),
    ("inventario.editar",             "inventario", "editar",           "editar",   "Editar inventario de artefactos"),
    ("inventario.aprobar_baja",       "inventario", "aprobar_baja",     "aprobar",  "Aprobar baja de artefacto"),

    ("cobranza.recibos.generar",      "cobranza",   "recibos",          "generar",  "Generar recibos mensuales"),
    ("cobranza.recibos.ver",          "cobranza",   "recibos",          "ver",      "Ver recibos"),
    ("cobranza.recibos.anular",       "cobranza",   "recibos",          "anular",   "Anular recibos"),
    ("cobranza.pagos.cobrar_efectivo","cobranza",   "pagos",            "cobrar",   "Cobrar en efectivo"),
    ("cobranza.pagos.validar_yape",   "cobranza",   "pagos",            "validar",  "Validar pagos por Yape/billetera"),
    ("cobranza.pagos.ver",            "cobranza",   "pagos",            "ver",      "Ver pagos"),

    ("caja.aperturar",                "caja",       "operacion",        "aperturar","Aperturar caja"),
    ("caja.cerrar",                   "caja",       "operacion",        "cerrar",   "Cerrar caja"),
    ("caja.ver",                      "caja",       "operacion",        "ver",      "Ver estado de caja"),

    ("concesiones.crear",             "concesiones","solicitud",        "crear",    "Crear solicitud de concesión"),
    ("concesiones.aprobar",           "concesiones","solicitud",        "aprobar",  "Aprobar concesión"),
    ("concesiones.ver",               "concesiones","solicitud",        "ver",      "Ver concesiones"),

    ("reportes.ver",                  "reportes",   "general",          "ver",      "Ver reportes"),

    ("config.catalogo.editar",        "config",     "catalogo",         "editar",   "Editar catálogo local de artefactos"),
    ("config.tarifas.editar",         "config",     "tarifas",          "editar",   "Editar tarifas"),
    ("config.municipio.editar",       "config",     "municipio",        "editar",   "Editar configuración general del municipio"),
    ("config.usuarios.editar",        "config",     "usuarios",         "editar",   "Crear / editar usuarios internos"),
    ("config.perfiles.editar",        "config",     "perfiles",         "editar",   "Editar perfiles y permisos"),
]


PERFILES: list[tuple[str, str, str, int]] = [
    # (codigo, nombre, descripcion, orden)
    ("admin_municipal", "Administrador municipal", "Acceso total al sistema del municipio", 10),
    ("tesorero",        "Tesorero",                "Cobranza, caja, concesiones, reportes",  20),
    ("cajero",          "Cajero",                  "Cobros en caja, ver recibos",            30),
    ("agente_integral", "Agente integral",         "Empadronamiento + cobros en campo",      40),
    ("empadronador",    "Empadronador",            "Padrón e inventario",                    50),
    ("cobrador",        "Cobrador",                "Solo cobros en efectivo",                60),
]


def _permisos_de_perfil(codigo: str, todos: list[str]) -> list[str]:
    if codigo == "admin_municipal":
        return list(todos)
    if codigo == "tesorero":
        return [p for p in todos if p.startswith("cobranza.") or p.startswith("caja.")
                or p.startswith("concesiones.") or p == "reportes.ver"]
    if codigo == "cajero":
        return [
            "cobranza.pagos.cobrar_efectivo",
            "cobranza.pagos.validar_yape",
            "cobranza.pagos.ver",
            "caja.aperturar", "caja.cerrar", "caja.ver",
            "cobranza.recibos.ver",
        ]
    if codigo == "agente_integral":
        return [p for p in todos if p.startswith("padron.") or p.startswith("inventario.")] + [
            "cobranza.pagos.cobrar_efectivo",
            "cobranza.recibos.ver",
            "cobranza.recibos.generar",
        ]
    if codigo == "empadronador":
        return [p for p in todos if p.startswith("padron.")] + [
            "inventario.ver", "inventario.editar",
        ]
    if codigo == "cobrador":
        return [
            "cobranza.pagos.cobrar_efectivo",
            "cobranza.recibos.ver",
            "padron.viviendas.ver",
        ]
    return []


def main() -> int:
    conn = psycopg2.connect(settings.DATABASE_URL_SYNC)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            for codigo, modulo, opcion, accion, descripcion in PERMISOS:
                cur.execute(
                    """
                    INSERT INTO public.permisos (codigo, modulo, opcion, accion, descripcion)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (codigo) DO UPDATE SET
                        modulo = EXCLUDED.modulo,
                        opcion = EXCLUDED.opcion,
                        accion = EXCLUDED.accion,
                        descripcion = EXCLUDED.descripcion
                    """,
                    (codigo, modulo, opcion, accion, descripcion),
                )

            for codigo, nombre, descripcion, orden in PERFILES:
                cur.execute(
                    """
                    INSERT INTO public.perfiles_plantilla (codigo, nombre, descripcion, orden)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (codigo) DO UPDATE SET
                        nombre = EXCLUDED.nombre,
                        descripcion = EXCLUDED.descripcion,
                        orden = EXCLUDED.orden
                    """,
                    (codigo, nombre, descripcion, orden),
                )

            todos_codigos = [p[0] for p in PERMISOS]
            for codigo_perfil, _, _, _ in PERFILES:
                cur.execute(
                    "SELECT id FROM public.perfiles_plantilla WHERE codigo = %s",
                    (codigo_perfil,),
                )
                perfil_id = cur.fetchone()[0]

                cur.execute(
                    "DELETE FROM public.perfiles_plantilla_permisos WHERE perfil_id = %s",
                    (perfil_id,),
                )
                for permiso_codigo in _permisos_de_perfil(codigo_perfil, todos_codigos):
                    cur.execute(
                        """
                        INSERT INTO public.perfiles_plantilla_permisos (perfil_id, permiso_id)
                        SELECT %s, id FROM public.permisos WHERE codigo = %s
                        ON CONFLICT DO NOTHING
                        """,
                        (perfil_id, permiso_codigo),
                    )

        conn.commit()
        logger.info("Permisos y perfiles plantilla sembrados.")
        return 0
    except Exception:
        conn.rollback()
        logger.exception("Error sembrando permisos — rollback")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
