"""
Endpoints API JSON para la PWA offline.

GET  /app/api/bootstrap          — catálogo + comunidades + referentes + subsidios + config
POST /app/api/empadronar-offline — sube un payload de vivienda creada offline
GET  /app/api/sync-status        — pulso simple para verificar conectividad/sesión

CSRF para POST JSON
-------------------
La protección CSRF existente (`app.services.csrf.verify_csrf`) lee el token desde
un campo `_csrf` del FORM. Para endpoints JSON usamos doble-submit por HEADER:
el cliente envía el header `X-CSRF-Token` y debe coincidir con la cookie `_csrf`.
La cookie sigue siendo seteada por las rutas HTML normales (no hace falta
duplicarla aquí).
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.database import tenant_session
from app.dependencies import CurrentUser, require_password_changed
from app.services.csrf import CSRF_COOKIE_NAME
from app.services.sync_service import (
    SyncConflict,
    procesar_empadronamiento_offline,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/app/api")


async def verify_csrf_header(request: Request) -> None:
    """CSRF doble-submit vía header (para endpoints JSON).

    Compara el header `X-CSRF-Token` con la cookie `_csrf`. Falla con 403 si
    falta cualquiera o no coinciden. Misma cookie y mismo token que el flujo
    de formularios; solo cambia el medio de transporte.
    """
    cookie_val = request.cookies.get(CSRF_COOKIE_NAME, "")
    header_val = request.headers.get("X-CSRF-Token", "")
    if not cookie_val or not header_val or cookie_val != header_val:
        logger.warning(
            "CSRF (header) invalido: path=%s cookie=%s header=%s",
            request.url.path, bool(cookie_val), bool(header_val),
        )
        raise HTTPException(status_code=403, detail="Token CSRF invalido")


@router.get("/bootstrap")
async def bootstrap(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
):
    """Retorna toda la data de referencia para operar offline."""
    if not user.puede("padron", "viviendas", "ver"):
        raise HTTPException(403, "Sin permiso")

    async with tenant_session(user.tenant_schema) as ts:
        comunidades = (
            await ts.execute(
                text(
                    "SELECT id, nombre, descripcion FROM comunidades "
                    "WHERE activa = TRUE ORDER BY nombre"
                )
            )
        ).mappings().all()

        referentes = (
            await ts.execute(
                text(
                    "SELECT id, nombre_completo, cargo, dni, telefono "
                    "FROM referentes WHERE activo = TRUE ORDER BY nombre_completo"
                )
            )
        ).mappings().all()

        subsidios = (
            await ts.execute(
                text(
                    "SELECT s.id, s.nombre, s.porcentaje, s.base_legal, "
                    "       s.vigente_desde, s.vigente_hasta, "
                    "       ARRAY(SELECT comunidad_id FROM subsidio_comunidades sc "
                    "             WHERE sc.subsidio_id = s.id) AS comunidad_ids "
                    "FROM subsidios s "
                    "WHERE s.vigente_hasta IS NULL OR s.vigente_hasta >= CURRENT_DATE "
                    "ORDER BY s.vigente_desde DESC"
                )
            )
        ).mappings().all()

        catalogo = (
            await ts.execute(
                text(
                    "SELECT ac.id::text AS id, 'catalogo' AS origen, ac.codigo, "
                    "       ac.nombre, ac.categoria, ac.icono, "
                    "       COALESCE(cfg.tarifa_mensual, ac.tarifa_sugerida) AS tarifa "
                    "FROM public.artefacto_catalogo ac "
                    "LEFT JOIN artefacto_config cfg ON cfg.catalogo_id = ac.id "
                    "WHERE (cfg.habilitado IS NULL AND ac.activo_default = TRUE) "
                    "   OR cfg.habilitado = TRUE "
                    "ORDER BY ac.categoria, ac.orden, ac.nombre"
                )
            )
        ).mappings().all()

        propios = (
            await ts.execute(
                text(
                    "SELECT codigo AS id, 'propio' AS origen, codigo, nombre, "
                    "       categoria, NULL AS icono, tarifa_mensual AS tarifa "
                    "FROM artefacto_propio WHERE habilitado = TRUE "
                    "ORDER BY categoria, orden, nombre"
                )
            )
        ).mappings().all()

        cfg_rows = (
            await ts.execute(
                text(
                    "SELECT clave, valor FROM config_municipio "
                    "WHERE clave IN ('cargo_fijo_mensual', 'adicional_por_morador')"
                )
            )
        ).all()
        config = {r.clave: r.valor for r in cfg_rows}

    def _ser_fecha(v):
        return v.isoformat() if v else None

    payload = {
        "comunidades": [dict(c) for c in comunidades],
        "referentes": [dict(r) for r in referentes],
        "subsidios": [
            {
                **dict(s),
                "vigente_desde": _ser_fecha(s["vigente_desde"]),
                "vigente_hasta": _ser_fecha(s["vigente_hasta"]),
                "porcentaje": float(s["porcentaje"]) if s["porcentaje"] is not None else None,
            }
            for s in subsidios
        ],
        "catalogo": [
            {**dict(a), "tarifa": float(a["tarifa"]) if a["tarifa"] is not None else 0.0}
            for a in catalogo
        ] + [
            {**dict(a), "tarifa": float(a["tarifa"]) if a["tarifa"] is not None else 0.0}
            for a in propios
        ],
        "config": config,
        "user": {
            "id": user.user_id,
            "nombre": user.nombre,
            "tenant_schema": user.tenant_schema,
        },
        "sync_at": datetime.now().isoformat(),
    }
    return JSONResponse(payload)


@router.post("/empadronar-offline", dependencies=[Depends(verify_csrf_header)])
async def empadronar_offline(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
):
    """Recibe y aplica el payload de una vivienda creada offline."""
    if not user.puede("padron", "viviendas", "crear"):
        raise HTTPException(403, "Sin permiso")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Payload JSON inválido")

    if not isinstance(payload, dict):
        raise HTTPException(400, "Payload debe ser un objeto JSON")
    if not payload.get("uuid_cliente"):
        raise HTTPException(400, "uuid_cliente requerido en el payload")
    if not payload.get("comunidad_id"):
        raise HTTPException(400, "comunidad_id requerido")

    async with tenant_session(user.tenant_schema) as ts:
        try:
            result = await procesar_empadronamiento_offline(
                ts, payload, user.user_id, user.tenant_schema
            )
        except SyncConflict as exc:
            return JSONResponse(
                {
                    "ok": False,
                    "error": "conflict",
                    "message": str(exc),
                    "detalle": exc.detalle,
                },
                status_code=409,
            )
        except Exception as exc:
            logger.exception("Error procesando empadronamiento offline")
            return JSONResponse(
                {"ok": False, "error": "internal", "message": str(exc)},
                status_code=500,
            )

    return JSONResponse(
        {
            "ok": True,
            "vivienda_id": result["vivienda_id"],
            "codigo_interno": result["codigo_interno"],
            "ya_existia": result.get("ya_existia", False),
        }
    )


@router.get("/sync-status")
async def sync_status(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
):
    """Heartbeat simple: confirma sesión válida y devuelve hora del servidor."""
    return JSONResponse(
        {
            "ok": True,
            "server_time": datetime.now().isoformat(),
            "user_id": user.user_id,
        }
    )
