"""
Lógica transaccional del wizard de empadronamiento.

crear_vivienda_completa():
1. Calcula siguiente codigo_interno (V-NNNN).
2. Sube foto a GCS (si hay).
3. INSERT vivienda con modo_calculo='estimado'.
4. INSERT jefe de familia (con hash Argon2 del DNI si acceso_portal).
5. INSERT segundo morador opcional.
6. INSERT inventario por cada artefacto con cantidad > 0.
7. INSERT vivienda_fotos.
8. INSERT vivienda_eventos tipo='empadronamiento'.
9. COMMIT.

Si cualquier paso falla → ROLLBACK + eliminar foto huérfana en GCS.
"""
from __future__ import annotations

import json as _json
import logging
import time
from datetime import date
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.security import hash_password
from app.services.gcs_uploader import GCSUploaderError, get_gcs_uploader
from app.services.inventario_service import InventarioError, agregar_artefacto

logger = logging.getLogger(__name__)


class EmpadronamientoError(Exception):
    pass


def _parse_fecha(value) -> Optional[date]:
    """
    Convierte string ISO 'YYYY-MM-DD' a objeto date.
    Acepta str, date o None. Retorna None si no se puede parsear.
    asyncpg exige date real para columnas DATE; strings dan AttributeError.
    """
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except (ValueError, AttributeError):
        return None


def _next_codigo_query() -> str:
    return (
        "SELECT COALESCE(MAX(CAST(SUBSTRING(codigo_interno FROM 'V-(\\d+)') AS INT)), 0) + 1 "
        "AS siguiente FROM viviendas"
    )


async def crear_vivienda_completa(
    session: AsyncSession,
    schema_name: str,
    user_id: int,
    datos_vivienda: dict,
    jefe_familia: dict,
    segundo_morador: Optional[dict],
    artefactos: list[dict],
    foto_fachada_bytes: bytes,
    foto_fachada_content_type: str = "image/jpeg",
) -> dict:
    ubigeo = schema_name.removeprefix("muni_")
    foto_uploaded = False
    foto_path: Optional[str] = None
    foto_url: Optional[str] = None

    # 0. Validaciones rápidas
    if not datos_vivienda.get("comunidad_id"):
        raise EmpadronamientoError("comunidad_id requerido")
    if not datos_vivienda.get("referencia_fisica"):
        raise EmpadronamientoError("referencia_fisica requerida")
    if not jefe_familia.get("dni") or not jefe_familia.get("nombre_completo"):
        raise EmpadronamientoError("DNI y nombre del jefe son requeridos")
    if segundo_morador and segundo_morador.get("dni") == jefe_familia.get("dni"):
        raise EmpadronamientoError("El segundo morador no puede tener el mismo DNI del jefe")

    artefactos_validos = []
    for a in artefactos or []:
        try:
            cant = int(a.get("cantidad", 0))
        except (TypeError, ValueError):
            cant = 0
        if cant <= 0:
            continue
        origen = a.get("origen")
        codigo = a.get("codigo")
        if origen not in ("catalogo", "propio") or not codigo:
            continue
        artefactos_validos.append({"origen": origen, "codigo": str(codigo), "cantidad": cant})

    # 1. Subir foto a GCS
    if foto_fachada_bytes:
        try:
            uploader = get_gcs_uploader()
            ts_epoch = int(time.time())
            foto_path = f"electro/{ubigeo}/viviendas/_pendiente_{ts_epoch}/fachada_{ts_epoch}.jpg"
            foto_url = uploader.subir_imagen(
                foto_fachada_bytes, foto_path, content_type=foto_fachada_content_type
            )
            foto_uploaded = True
        except GCSUploaderError as exc:
            logger.warning("Foto NO subida a GCS, continuando sin foto: %s", exc)
            foto_url = None
            foto_path = None
            foto_uploaded = False

    try:
        # 2. Calcular siguiente código
        row = (await session.execute(text(_next_codigo_query()))).first()
        siguiente = int(row.siguiente)
        codigo_interno = f"V-{siguiente:04d}"

        # 3. INSERT vivienda
        v_row = (
            await session.execute(
                text(
                    """
                    INSERT INTO viviendas (
                        codigo_interno, comunidad_id, referente_id, fuente_validacion,
                        referencia_fisica, direccion_textual, gps_lat, gps_lng, gps_precision_metros,
                        foto_fachada_url, modo_calculo, estado_servicio, empadronada_por_user_id
                    ) VALUES (
                        :c, :com, :ref, :fv, :rf, :dt, :lat, :lng, :prec,
                        :url, 'estimado', 'activo', :u
                    ) RETURNING id
                    """
                ),
                {
                    "c": codigo_interno,
                    "com": datos_vivienda["comunidad_id"],
                    "ref": datos_vivienda.get("referente_id"),
                    "fv": datos_vivienda.get("fuente_validacion"),
                    "rf": datos_vivienda["referencia_fisica"],
                    "dt": datos_vivienda.get("direccion_textual"),
                    "lat": datos_vivienda.get("gps_lat"),
                    "lng": datos_vivienda.get("gps_lng"),
                    "prec": datos_vivienda.get("gps_precision_metros"),
                    "url": foto_url,
                    "u": user_id,
                },
            )
        ).first()
        vivienda_id = v_row.id

        # 4. INSERT jefe
        jefe_hash = hash_password(jefe_familia["dni"]) if jefe_familia.get("acceso_portal") else None
        await session.execute(
            text(
                """
                INSERT INTO moradores (
                    vivienda_id, dni, nombre_completo, fecha_nacimiento, sexo, telefono, whatsapp,
                    es_jefe_familia, es_responsable_pago, acceso_portal, access_code,
                    debe_cambiar_clave, activo
                ) VALUES (
                    :v, :d, :n, :fn, :sx, :tel, :wa, TRUE, TRUE, :ap, :ac, TRUE, TRUE
                )
                """
            ),
            {
                "v": vivienda_id,
                "d": jefe_familia["dni"],
                "n": jefe_familia["nombre_completo"],
                "fn": _parse_fecha(jefe_familia.get("fecha_nacimiento")),
                "sx": jefe_familia.get("sexo"),
                "tel": jefe_familia.get("telefono"),
                "wa": jefe_familia.get("whatsapp") or jefe_familia.get("telefono"),
                "ap": bool(jefe_familia.get("acceso_portal")),
                "ac": jefe_hash,
            },
        )

        # 5. Segundo morador opcional
        if segundo_morador and segundo_morador.get("dni") and segundo_morador.get("nombre_completo"):
            await session.execute(
                text(
                    """
                    INSERT INTO moradores (
                        vivienda_id, dni, nombre_completo, fecha_nacimiento, sexo, telefono, whatsapp,
                        es_jefe_familia, es_responsable_pago, activo
                    ) VALUES (
                        :v, :d, :n, :fn, :sx, :tel, :wa, FALSE, FALSE, TRUE
                    )
                    """
                ),
                {
                    "v": vivienda_id,
                    "d": segundo_morador["dni"],
                    "n": segundo_morador["nombre_completo"],
                    "fn": _parse_fecha(segundo_morador.get("fecha_nacimiento")),
                    "sx": segundo_morador.get("sexo"),
                    "tel": segundo_morador.get("telefono"),
                    "wa": segundo_morador.get("whatsapp") or segundo_morador.get("telefono"),
                },
            )

        # 6. Inventario — fallas individuales NO abortan la vivienda
        logger.info(
            "Procesando %d artefactos para vivienda_id=%s",
            len(artefactos_validos), vivienda_id,
        )
        inventarios_creados = 0
        inventarios_fallidos: list[dict] = []
        for art in artefactos_validos:
            logger.info(
                "Agregando artefacto origen=%s codigo=%s cantidad=%s",
                art["origen"], art["codigo"], art["cantidad"],
            )
            try:
                new_inv_id = await agregar_artefacto(
                    session, schema_name,
                    vivienda_id=vivienda_id,
                    artefacto_origen=art["origen"],
                    artefacto_codigo=art["codigo"],
                    cantidad=art["cantidad"],
                    user_id=user_id,
                    motivo="empadronamiento_inicial",
                    fecha_alta=date.today(),
                )
                logger.info("Artefacto agregado inv_id=%s", new_inv_id)
                inventarios_creados += 1
            except InventarioError as exc:
                logger.exception(
                    "Artefacto omitido en empadronamiento: %s/%s — %s",
                    art["origen"], art["codigo"], exc,
                )
                inventarios_fallidos.append({
                    "origen": art["origen"],
                    "codigo": art["codigo"],
                    "error": str(exc),
                })
        logger.info(
            "Empadronamiento %s: %d artefactos OK, %d fallidos",
            codigo_interno, inventarios_creados, len(inventarios_fallidos),
        )

        # 7. Foto en histórico
        if foto_url:
            await session.execute(
                text(
                    """
                    INSERT INTO vivienda_fotos (vivienda_id, url, tipo, tomada_por_user_id, es_actual)
                    VALUES (:v, :u, 'fachada', :uid, TRUE)
                    """
                ),
                {"v": vivienda_id, "u": foto_url, "uid": user_id},
            )

        # 8. Evento de empadronamiento
        metadata = {
            "codigo_interno": codigo_interno,
            "comunidad_id": datos_vivienda["comunidad_id"],
            "n_moradores": 2 if segundo_morador else 1,
            "n_artefactos_pedidos": len(artefactos_validos),
            "n_artefactos_creados": inventarios_creados,
            "artefactos_fallidos": inventarios_fallidos,
            "tiene_foto": bool(foto_url),
            "tiene_gps": bool(datos_vivienda.get("gps_lat")),
        }
        await session.execute(
            text(
                """
                INSERT INTO vivienda_eventos (vivienda_id, tipo, descripcion, metadata, user_id)
                VALUES (:v, 'empadronamiento', :d, CAST(:m AS JSONB), :u)
                """
            ),
            {
                "v": vivienda_id,
                "d": f"Vivienda empadronada con código {codigo_interno}",
                "m": _json.dumps(metadata),
                "u": user_id,
            },
        )

        await session.commit()

        logger.info(
            "Vivienda empadronada: schema=%s codigo=%s vivienda_id=%s user_id=%s",
            schema_name, codigo_interno, vivienda_id, user_id,
        )
        return {
            "vivienda_id": vivienda_id,
            "codigo_interno": codigo_interno,
            "foto_url": foto_url,
        }

    except (InventarioError, Exception) as exc:
        logger.exception("Error en crear_vivienda_completa — rollback")
        await session.rollback()
        if foto_uploaded and foto_path:
            try:
                get_gcs_uploader().eliminar(foto_path)
            except Exception:
                logger.exception("Error eliminando foto huérfana en GCS path=%s", foto_path)
        raise EmpadronamientoError(str(exc)) from exc