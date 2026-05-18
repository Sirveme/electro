"""
Provisión de un municipio (tenant): crea schema, aplica migraciones,
copia perfiles plantilla, crea usuario admin del municipio.

Usa conexión sincrónica (psycopg2). Todo en una sola transacción donde sea posible.
"""
import logging
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from app.security import hash_password
from app.services.migrations import aplicar_migraciones_tenant
from app.utils.ubigeo import normalizar_ubigeo, schema_for_ubigeo

logger = logging.getLogger(__name__)


CONFIG_SEED = [
    ("cargo_fijo_mensual", "5.00", "decimal", "Cargo fijo aplicado a toda vivienda"),
    ("adicional_por_morador", "0.00", "decimal", "Monto adicional por cada morador"),
    ("cargo_reconexion", "15.00", "decimal", "Cargo por reconexión del servicio"),
    ("meses_morosidad_corte", "3", "int", "Meses sin pagar antes de autorizar corte"),
    (
        "autoreporte_baja_auto_aplica",
        "false",
        "bool",
        "Si las bajas reportadas por moradores se aplican al instante o esperan validación",
    ),
    ("periodo_facturacion_dia_inicio", "1", "int", "Día del mes en que inicia el período de facturación"),
]


class ProvisioningError(Exception):
    pass


def crear_municipio(
    db_url_sync: str,
    ubigeo: str,
    nombre: str,
    departamento: Optional[str],
    provincia: Optional[str],
    distrito: Optional[str],
    admin_dni: str,
    admin_nombre: str,
    admin_password: str,
    creado_por_superadmin_id: int,
    admin_email: Optional[str] = None,
    admin_telefono: Optional[str] = None,
    responsable_telefono: Optional[str] = None,
    plan: str = "demo",
    precio_mensual: Optional[float] = None,
) -> dict:
    """
    Provisión completa de un municipio. Pasos:
      1. Valida UBIGEO
      2. INSERT en public.municipios + public.suscripciones
      3. CREATE SCHEMA muni_{ubigeo} (vía la migración)
      4. Aplica migraciones del tenant (incluye CREATE SCHEMA dentro del archivo)
      5. Copia perfiles plantilla → perfiles del tenant con sus permisos
      6. Siembra config_municipio
      7. Crea usuario admin con perfil "admin_municipal"

    Si algo falla, hace ROLLBACK incluyendo DROP SCHEMA si llegó a crearse.
    Retorna dict con ids creados.
    """
    ubigeo = normalizar_ubigeo(ubigeo)
    schema_name = schema_for_ubigeo(ubigeo)
    admin_hash = hash_password(admin_password)

    conn = psycopg2.connect(db_url_sync)
    conn.autocommit = False
    schema_creado = False
    municipio_id: Optional[int] = None

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1. INSERT municipio
            cur.execute(
                """
                INSERT INTO public.municipios (
                    ubigeo, nombre, departamento, provincia, distrito,
                    schema_name, responsable_nombre, responsable_dni, responsable_telefono,
                    activo, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s)
                RETURNING id
                """,
                (
                    ubigeo, nombre, departamento, provincia, distrito,
                    schema_name, admin_nombre, admin_dni, responsable_telefono,
                    creado_por_superadmin_id,
                ),
            )
            municipio_id = cur.fetchone()["id"]

            # 2. INSERT suscripcion
            cur.execute(
                """
                INSERT INTO public.suscripciones (municipio_id, plan, vigente_desde, precio_mensual, activa)
                VALUES (%s, %s, CURRENT_DATE, %s, TRUE)
                RETURNING id
                """,
                (municipio_id, plan, precio_mensual),
            )
            suscripcion_id = cur.fetchone()["id"]

        conn.commit()  # cerrar tx antes de las migraciones (cada migración hace su propia tx)

        # 3 + 4. Aplicar migraciones del tenant (crea schema y tablas)
        aplicar_migraciones_tenant(db_url_sync, schema_name)
        schema_creado = True

        # Reabrir tx para sembrar config, copiar perfiles, crear admin
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 5. Copiar perfiles plantilla
            cur.execute(
                "SELECT id, codigo, nombre, descripcion FROM public.perfiles_plantilla ORDER BY orden, id"
            )
            plantillas = cur.fetchall()
            mapping_plantilla_id_to_codigo: dict[int, str] = {}
            mapping_codigo_to_tenant_perfil_id: dict[str, int] = {}

            for p in plantillas:
                mapping_plantilla_id_to_codigo[p["id"]] = p["codigo"]
                cur.execute(
                    f'INSERT INTO "{schema_name}".perfiles (codigo, nombre, descripcion) '
                    "VALUES (%s, %s, %s) RETURNING id",
                    (p["codigo"], p["nombre"], p["descripcion"]),
                )
                mapping_codigo_to_tenant_perfil_id[p["codigo"]] = cur.fetchone()["id"]

            # Copiar relaciones perfil-permiso (resolviendo permiso_id → codigo)
            cur.execute(
                """
                SELECT pp.perfil_id, p.codigo AS permiso_codigo
                FROM public.perfiles_plantilla_permisos pp
                JOIN public.permisos p ON p.id = pp.permiso_id
                """
            )
            relaciones = cur.fetchall()
            for r in relaciones:
                codigo_plantilla = mapping_plantilla_id_to_codigo.get(r["perfil_id"])
                if not codigo_plantilla:
                    continue
                tenant_perfil_id = mapping_codigo_to_tenant_perfil_id.get(codigo_plantilla)
                if not tenant_perfil_id:
                    continue
                cur.execute(
                    f'INSERT INTO "{schema_name}".perfiles_permisos (perfil_id, permiso_codigo) '
                    "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (tenant_perfil_id, r["permiso_codigo"]),
                )

            # 6. Sembrar config_municipio
            for clave, valor, tipo, descripcion in CONFIG_SEED:
                cur.execute(
                    f'INSERT INTO "{schema_name}".config_municipio (clave, valor, tipo, descripcion) '
                    "VALUES (%s, %s, %s, %s) ON CONFLICT (clave) DO NOTHING",
                    (clave, valor, tipo, descripcion),
                )

            # 7. Usuario admin
            perfil_admin_id = mapping_codigo_to_tenant_perfil_id.get("admin_municipal")
            if not perfil_admin_id:
                raise ProvisioningError(
                    "No existe perfil_plantilla 'admin_municipal'. Ejecuta seed_permisos primero."
                )
            cur.execute(
                f'INSERT INTO "{schema_name}".usuarios '
                "(dni, nombre_completo, email, telefono, access_code, perfil_id, debe_cambiar_clave, activo) "
                "VALUES (%s, %s, %s, %s, %s, %s, TRUE, TRUE) RETURNING id",
                (admin_dni, admin_nombre, admin_email, admin_telefono, admin_hash, perfil_admin_id),
            )
            admin_user_id = cur.fetchone()["id"]

        conn.commit()

        logger.info(
            "Municipio creado: ubigeo=%s schema=%s municipio_id=%s admin_user_id=%s",
            ubigeo, schema_name, municipio_id, admin_user_id,
        )
        return {
            "municipio_id": municipio_id,
            "suscripcion_id": suscripcion_id,
            "schema_name": schema_name,
            "admin_user_id": admin_user_id,
        }

    except Exception as exc:
        logger.exception("Error provisionando municipio %s — rollback", ubigeo)
        conn.rollback()
        # Rollback manual del schema si llegó a crearse
        if schema_creado:
            try:
                with conn.cursor() as cur:
                    cur.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
                    cur.execute(
                        "DELETE FROM public.schema_versions WHERE schema_name = %s",
                        (schema_name,),
                    )
                    if municipio_id:
                        cur.execute("DELETE FROM public.municipios WHERE id = %s", (municipio_id,))
                conn.commit()
            except Exception:
                logger.exception("Error en rollback del schema %s", schema_name)
                conn.rollback()
        raise ProvisioningError(str(exc)) from exc
    finally:
        conn.close()
