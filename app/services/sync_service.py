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
from decimal import Decimal, InvalidOperation
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


# ============================================================================
# COBRANZA OFFLINE
# ============================================================================


async def procesar_pago_offline(
    session: AsyncSession,
    payload: dict,
    user_id: int,
    tenant_schema: str,
) -> dict:
    """Procesa un cobro creado offline.

    Schema real del proyecto:
    - `pagos` es una fila por cuota (FK NOT NULL a `cuotas`). No existe
      `cuota_pagos`. Si el cobro offline cubre varias cuotas, generamos
      varios `pagos` que comparten el mismo `uuid_cliente` (lote logico).
    - `caja_aperturas` usa `cajero_user_id` (no `usuario_id`).
    - `cuotas` usa `saldo_pendiente` (no `monto_pendiente`).
    - Reusamos `pago_service.registrar_pago` para no duplicar validaciones
      (sobrepago, caja, metodo) y despues hacemos UPDATE del uuid_cliente.

    Payload esperado:
    - uuid_pago        : UUID v4 generado en cliente (idempotencia)
    - codigo_interno   : preferido para resolver vivienda
    - vivienda_id      : alternativa si el cliente lo conoce
    - cuota_ids        : lista de cuotas a pagar
    - monto_total      : suma a distribuir FIFO
    - metodo_pago      : 'efectivo'|'yape'|'plin'
    - referencia_externa
    - capturado_at     : timestamp del cobro original (informativo)

    Reglas:
    - Si uuid_pago ya existe en `pagos.uuid_cliente`, retorna ya_existia=True.
    - Si el cajero NO tiene caja abierta y el metodo es efectivo → conflict.
    - Si una cuota no existe, pertenece a otra vivienda, esta anulada o ya
      pagada → conflict (el lote completo falla — un cobro multi-cuota es
      atomico).
    """
    from app.services.pago_service import registrar_pago, PagoError
    from app.services.caja_service import caja_abierta_de

    uuid_pago = payload.get("uuid_pago") or payload.get("uuid_cliente")
    if not uuid_pago:
        raise SyncConflict("uuid_pago requerido en payload")

    # 1. Idempotencia
    existing = (
        await session.execute(
            text("SELECT id FROM pagos WHERE uuid_cliente = :u LIMIT 1"),
            {"u": uuid_pago},
        )
    ).mappings().first()
    if existing:
        logger.info("Pago offline ya existía: uuid=%s pago_id=%s", uuid_pago, existing["id"])
        return {"pago_id": existing["id"], "ya_existia": True}

    # 2. Resolver vivienda_id (preferimos codigo_interno)
    vivienda_id = payload.get("vivienda_id")
    if not vivienda_id and payload.get("codigo_interno"):
        row = (
            await session.execute(
                text("SELECT id FROM viviendas WHERE codigo_interno = :c"),
                {"c": payload["codigo_interno"]},
            )
        ).mappings().first()
        if not row:
            raise SyncConflict(
                f"Vivienda {payload['codigo_interno']} no encontrada"
            )
        vivienda_id = row["id"]
    if not vivienda_id:
        raise SyncConflict("vivienda_id o codigo_interno requerido")

    # 3. Vivienda no anulada
    v = (
        await session.execute(
            text("SELECT codigo_interno, anulada_at FROM viviendas WHERE id = :vid"),
            {"vid": vivienda_id},
        )
    ).mappings().first()
    if not v:
        raise SyncConflict("Vivienda no encontrada")
    if v["anulada_at"]:
        raise SyncConflict(f"Vivienda {v['codigo_interno']} esta anulada")

    # 4. Validar cuotas
    cuota_ids_raw = payload.get("cuota_ids") or []
    if isinstance(cuota_ids_raw, (int, str)):
        cuota_ids_raw = [cuota_ids_raw]
    try:
        cuota_ids = [int(c) for c in cuota_ids_raw if c]
    except (TypeError, ValueError) as exc:
        raise SyncConflict(f"cuota_ids invalidos: {exc}") from exc
    if not cuota_ids:
        # Soporte legacy: pago de una sola cuota via 'cuota_id'
        single = payload.get("cuota_id")
        if single:
            cuota_ids = [int(single)]
    if not cuota_ids:
        raise SyncConflict("Sin cuotas para cobrar")

    rows = (
        await session.execute(
            text(
                "SELECT id, vivienda_id, estado, saldo_pendiente "
                "FROM cuotas WHERE id = ANY(:ids)"
            ),
            {"ids": cuota_ids},
        )
    ).mappings().all()
    cuotas_dict = {r["id"]: dict(r) for r in rows}
    for cid in cuota_ids:
        if cid not in cuotas_dict:
            raise SyncConflict(f"Cuota {cid} no existe")
        c = cuotas_dict[cid]
        if c["vivienda_id"] != vivienda_id:
            raise SyncConflict(f"Cuota {cid} pertenece a otra vivienda")
        if c["estado"] == "pagado":
            raise SyncConflict(f"Cuota {cid} ya esta pagada")
        if c["estado"] == "anulada":
            raise SyncConflict(f"Cuota {cid} esta anulada")

    # 5. Caja abierta del cajero AHORA (no la del momento del cobro original)
    metodo = (payload.get("metodo_pago") or payload.get("metodo") or "efectivo").lower()
    caja = await caja_abierta_de(session, user_id)
    if metodo == "efectivo" and not caja:
        raise SyncConflict(
            "No tienes caja abierta. Abre caja antes de sincronizar pagos en efectivo."
        )
    caja_id = caja["id"] if caja else None

    # 6. Distribuir monto FIFO y registrar cada pago (reusa pago_service)
    try:
        monto_total = Decimal(str(payload.get("monto_total", "0")))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SyncConflict(f"monto_total invalido: {exc}") from exc
    if monto_total <= 0:
        raise SyncConflict("monto_total debe ser > 0")

    referencia = payload.get("referencia_externa") or None
    obs_base = payload.get("observaciones") or ""
    obs_offline = (
        f"[Offline sincronizado · uuid {uuid_pago[:8]}…"
        + (f" · capturado {payload.get('capturado_at')}" if payload.get("capturado_at") else "")
        + "]"
    )
    observaciones = (obs_base + " " + obs_offline).strip() if obs_base else obs_offline

    pago_ids: list[int] = []
    restante = monto_total.quantize(Decimal("0.01"))
    for cid in cuota_ids:
        if restante <= 0:
            break
        pendiente = Decimal(str(cuotas_dict[cid]["saldo_pendiente"]))
        aplicar = min(restante, pendiente).quantize(Decimal("0.01"))
        if aplicar <= 0:
            continue
        try:
            pago_id = await registrar_pago(
                session,
                cuota_id=cid,
                monto=aplicar,
                metodo=metodo,
                user_id=user_id,
                caja_apertura_id=caja_id,
                observaciones=observaciones,
                referencia_externa=referencia,
            )
        except PagoError as exc:
            # Cualquier validacion fallida vuelve la transaccion atras y
            # marca el item como conflict para revision manual.
            raise SyncConflict(f"Cuota {cid}: {exc}") from exc

        # Marcar el pago recién creado con el uuid_cliente del lote logico.
        await session.execute(
            text("UPDATE pagos SET uuid_cliente = :u WHERE id = :id"),
            {"u": uuid_pago, "id": pago_id},
        )
        pago_ids.append(pago_id)
        restante -= aplicar

    if not pago_ids:
        raise SyncConflict("No se aplico ningun pago (todas las cuotas sin saldo)")

    await session.commit()
    logger.info(
        "Pago offline OK schema=%s uuid=%s pagos=%s monto=%s caja=%s",
        tenant_schema, uuid_pago, pago_ids, monto_total, caja_id,
    )
    return {
        "pago_id": pago_ids[0],          # compatibilidad con cliente
        "pago_ids": pago_ids,            # lista completa para auditoria
        "caja_apertura_id": caja_id,
        "ya_existia": False,
    }
