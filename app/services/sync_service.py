"""
Servicio de sincronización: recibe payloads creados offline y los aplica a la BD
preservando el uuid_cliente para garantizar idempotencia.

procesar_empadronamiento_offline():
1. Si uuid_cliente ya existe → retorna la vivienda existente (ya_existia=True).
2. Si el DNI del jefe ya es jefe activo en otra vivienda no anulada → SyncConflict.
3. Sube foto fachada y foto DNI a GCS si vienen en base64.
4. Calcula siguiente codigo_interno (V-NNNN).
5. INSERT vivienda con uuid_cliente.
6. INSERT moradores con uuid_cliente (cada uno).
7. INSERT inventario inicial vía vivienda_inventario.
8. INSERT vivienda_fotos si hay foto.
9. INSERT vivienda_eventos con tipo='empadronamiento_offline'.
10. COMMIT.

NOTAS de diseño respecto al schema real:
- viviendas usa gps_precision_metros (INT), no gps_accuracy_m.
- vivienda_inventario NO tiene tarifa_snapshot: solo cantidad, vigente_desde,
  motivo_alta y artefacto_nombre_snapshot. La tarifa se resuelve en facturación.
- moradores tiene UNIQUE(vivienda_id, dni) — un DNI puede repetirse entre viviendas
  pero el conflicto a vigilar es "ese DNI ya es jefe de otra vivienda activa".
"""
from __future__ import annotations

import base64
import json as _json
import logging
import time
from datetime import date, datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.security import hash_password
from app.services.gcs_uploader import GCSUploaderError, get_gcs_uploader

logger = logging.getLogger(__name__)


class SyncConflict(Exception):
    """Conflicto de sincronización (ej.: DNI duplicado).

    El cliente debe mostrar este conflicto al usuario y NO reintentar
    automáticamente; el item queda con status='conflict' en la cola.
    """

    def __init__(self, message: str, detalle: Optional[dict] = None):
        super().__init__(message)
        self.detalle = detalle or {}


def _parse_fecha(value) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except (ValueError, AttributeError):
        return None


def _parse_dt(value) -> datetime:
    if not value:
        return datetime.now()
    if isinstance(value, datetime):
        return value
    try:
        # Acepta 'YYYY-MM-DDTHH:MM:SS' o con timezone
        s = str(value).rstrip("Z")
        return datetime.fromisoformat(s)
    except (ValueError, AttributeError):
        return datetime.now()


def _decode_b64(s: Optional[str]) -> Optional[bytes]:
    if not s:
        return None
    # Tolerar prefijo data:image/...;base64,
    if "," in s and s.lstrip().startswith("data:"):
        s = s.split(",", 1)[1]
    try:
        return base64.b64decode(s)
    except Exception:
        logger.warning("base64 inválido; ignorando")
        return None


async def _subir_foto(
    img_bytes: bytes,
    ubigeo: str,
    subdir: str,
    uuid_cliente: str,
) -> tuple[Optional[str], Optional[str]]:
    """Sube bytes a GCS. Retorna (url, path) o (None, None) si falla."""
    try:
        uploader = get_gcs_uploader()
        ts_epoch = int(time.time())
        path = f"electro/{ubigeo}/{subdir}/sync_{uuid_cliente}_{ts_epoch}.jpg"
        url = uploader.subir_imagen(img_bytes, path, content_type="image/jpeg")
        return url, path
    except GCSUploaderError as exc:
        logger.warning("Subida a GCS falló (%s): %s", subdir, exc)
        return None, None


async def procesar_empadronamiento_offline(
    session: AsyncSession,
    payload: dict,
    user_id: int,
    tenant_schema: str,
) -> dict:
    uuid_cliente_str = payload.get("uuid_cliente")
    if not uuid_cliente_str:
        raise ValueError("uuid_cliente requerido en payload")

    ubigeo = tenant_schema.removeprefix("muni_")

    # 1. Idempotencia: ¿ya está esta vivienda?
    existing = (
        await session.execute(
            text(
                "SELECT id, codigo_interno FROM viviendas WHERE uuid_cliente = :u"
            ),
            {"u": uuid_cliente_str},
        )
    ).mappings().first()
    if existing:
        logger.info(
            "Empadronamiento offline ya existía: uuid=%s codigo=%s",
            uuid_cliente_str, existing["codigo_interno"],
        )
        return {
            "vivienda_id": existing["id"],
            "codigo_interno": existing["codigo_interno"],
            "ya_existia": True,
        }

    # 2. Conflicto: DNI del jefe ya es jefe activo en otra vivienda
    moradores_payload = payload.get("moradores", []) or []
    jefe = next((m for m in moradores_payload if m.get("es_jefe_familia")), None)
    if jefe and jefe.get("dni"):
        dup = (
            await session.execute(
                text(
                    "SELECT v.id, v.codigo_interno "
                    "FROM moradores m JOIN viviendas v ON v.id = m.vivienda_id "
                    "WHERE m.dni = :dni AND m.es_jefe_familia = TRUE "
                    "  AND m.activo = TRUE AND v.activa = TRUE "
                    "  AND v.anulada_at IS NULL"
                ),
                {"dni": jefe["dni"]},
            )
        ).mappings().first()
        if dup:
            raise SyncConflict(
                f"El DNI {jefe['dni']} ya es jefe de la vivienda {dup['codigo_interno']}",
                {"vivienda_existente": dict(dup)},
            )

    # 3. Subir fotos
    foto_url = None
    foto_path = None
    foto_dni_url = None
    foto_dni_path = None
    foto_bytes = _decode_b64(payload.get("foto_fachada_base64"))
    if foto_bytes:
        foto_url, foto_path = await _subir_foto(foto_bytes, ubigeo, "viviendas", uuid_cliente_str)
    dni_bytes = _decode_b64(payload.get("foto_dni_base64"))
    if dni_bytes:
        foto_dni_url, foto_dni_path = await _subir_foto(dni_bytes, ubigeo, "dni", uuid_cliente_str)

    try:
        # 4. Siguiente código interno
        row = (
            await session.execute(
                text(
                    "SELECT COALESCE(MAX(CAST(SUBSTRING(codigo_interno FROM 'V-(\\d+)') AS INT)), 0) + 1 "
                    "AS siguiente FROM viviendas"
                )
            )
        ).first()
        codigo_interno = f"V-{int(row.siguiente):04d}"

        capturado_at = _parse_dt(payload.get("capturado_at"))

        # 5. INSERT vivienda
        v_row = (
            await session.execute(
                text(
                    """
                    INSERT INTO viviendas (
                      codigo_interno, uuid_cliente, comunidad_id, referente_id,
                      fuente_validacion, referencia_fisica, direccion_textual,
                      gps_lat, gps_lng, gps_precision_metros,
                      foto_fachada_url, modo_calculo, estado_servicio,
                      empadronada_por_user_id, empadronada_at, activa
                    ) VALUES (
                      :codigo, :uuid, :com, :ref,
                      :fuente, :refisica, :dirtxt,
                      :lat, :lng, :prec,
                      :foto, 'estimado', 'activo',
                      :uid, :ts, TRUE
                    ) RETURNING id
                    """
                ),
                {
                    "codigo": codigo_interno,
                    "uuid": uuid_cliente_str,
                    "com": payload["comunidad_id"],
                    "ref": payload.get("referente_id"),
                    "fuente": payload.get("fuente_validacion"),
                    "refisica": payload.get("referencia_fisica") or "",
                    "dirtxt": payload.get("direccion_textual"),
                    "lat": payload.get("gps_lat"),
                    "lng": payload.get("gps_lng"),
                    "prec": payload.get("gps_precision_metros") or payload.get("gps_accuracy"),
                    "foto": foto_url,
                    "uid": user_id,
                    "ts": capturado_at,
                },
            )
        ).first()
        vivienda_id = v_row.id

        # 6. INSERT moradores (jefe + opcional segundo)
        for m in moradores_payload:
            jefe_hash = (
                hash_password(m["dni"])
                if m.get("es_jefe_familia") and m.get("acceso_portal") and m.get("dni")
                else None
            )
            await session.execute(
                text(
                    """
                    INSERT INTO moradores (
                      vivienda_id, uuid_cliente, dni, nombre_completo,
                      fecha_nacimiento, sexo, telefono,
                      es_jefe_familia, es_responsable_pago, acceso_portal, access_code,
                      debe_cambiar_clave, activo, created_at
                    ) VALUES (
                      :vid, :uuid, :dni, :nombre,
                      :fnac, :sx, :tel,
                      :jefe, :pago, :portal, :ac,
                      TRUE, TRUE, NOW()
                    )
                    """
                ),
                {
                    "vid": vivienda_id,
                    "uuid": m.get("uuid_cliente"),
                    "dni": m["dni"],
                    "nombre": m["nombre_completo"],
                    "fnac": _parse_fecha(m.get("fecha_nacimiento")),
                    "sx": (m.get("sexo") or "").strip().upper()[:1] or None,
                    "tel": m.get("telefono"),
                    "jefe": bool(m.get("es_jefe_familia")),
                    "pago": bool(
                        m.get("es_responsable_pago", m.get("es_jefe_familia"))
                    ),
                    "portal": bool(m.get("acceso_portal")),
                    "ac": jefe_hash,
                },
            )

        # 7. INSERT inventario inicial
        inventario = payload.get("inventario", []) or []
        inv_creados = 0
        for item in inventario:
            try:
                cant = int(item.get("cantidad", 0))
            except (TypeError, ValueError):
                cant = 0
            if cant <= 0:
                continue
            origen = item.get("origen") or item.get("artefacto_origen")
            codigo = item.get("codigo") or item.get("artefacto_codigo")
            nombre = item.get("nombre") or item.get("artefacto_nombre", "")
            if origen not in ("catalogo", "propio") or not codigo:
                continue
            await session.execute(
                text(
                    """
                    INSERT INTO vivienda_inventario (
                      vivienda_id, artefacto_origen, artefacto_codigo,
                      artefacto_nombre_snapshot, cantidad,
                      vigente_desde, motivo_alta, registrado_por_user_id
                    ) VALUES (
                      :vid, :origen, :cod, :nombre, :cant,
                      CURRENT_DATE, 'empadronamiento_inicial', :uid
                    )
                    """
                ),
                {
                    "vid": vivienda_id,
                    "origen": origen,
                    "cod": str(codigo),
                    "nombre": nombre[:80] if nombre else codigo,
                    "cant": cant,
                    "uid": user_id,
                },
            )
            inv_creados += 1

        # 8. Foto en histórico
        if foto_url:
            await session.execute(
                text(
                    """
                    INSERT INTO vivienda_fotos (vivienda_id, url, tipo, tomada_por_user_id, es_actual)
                    VALUES (:vid, :url, 'fachada', :uid, TRUE)
                    """
                ),
                {"vid": vivienda_id, "url": foto_url, "uid": user_id},
            )
        if foto_dni_url and jefe:
            # Apuntar foto DNI al jefe recién insertado (último insertado con ese DNI).
            await session.execute(
                text(
                    "UPDATE moradores SET dni_foto_url = :url "
                    "WHERE vivienda_id = :vid AND dni = :dni"
                ),
                {"url": foto_dni_url, "vid": vivienda_id, "dni": jefe["dni"]},
            )

        # 9. Evento de auditoría
        metadata = {
            "uuid_cliente": uuid_cliente_str,
            "capturado_at": capturado_at.isoformat(),
            "n_moradores": len(moradores_payload),
            "n_artefactos": inv_creados,
            "tiene_gps": bool(payload.get("gps_lat")),
            "tiene_foto": bool(foto_url),
            "tiene_foto_dni": bool(foto_dni_url),
            "origen": "pwa_offline",
        }
        await session.execute(
            text(
                """
                INSERT INTO vivienda_eventos (vivienda_id, tipo, descripcion, metadata, user_id)
                VALUES (:vid, 'empadronamiento_offline', :desc, CAST(:meta AS JSONB), :uid)
                """
            ),
            {
                "vid": vivienda_id,
                "desc": f"Empadronamiento offline sincronizado (uuid {uuid_cliente_str[:8]}…)",
                "meta": _json.dumps(metadata, ensure_ascii=False, default=str),
                "uid": user_id,
            },
        )

        await session.commit()
        logger.info(
            "Empadronamiento offline OK schema=%s codigo=%s vivienda_id=%s",
            tenant_schema, codigo_interno, vivienda_id,
        )
        return {
            "vivienda_id": vivienda_id,
            "codigo_interno": codigo_interno,
            "ya_existia": False,
        }

    except Exception:
        await session.rollback()
        # Limpiar fotos huérfanas en GCS
        for p in (foto_path, foto_dni_path):
            if p:
                try:
                    get_gcs_uploader().eliminar(p)
                except Exception:
                    logger.exception("No se pudo limpiar foto huérfana path=%s", p)
        raise
