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
    """Retorna data de referencia para operar offline:
    comunidades, referentes, subsidios vigentes, catalogo de artefactos
    habilitados y config del municipio.

    Cada bloque corre en su propio `tenant_session` para que un error en
    uno (SQL malformado, columna inexistente, etc.) no aborte la transaccion
    de los demas — la causa raiz del bug original. El cliente recibe
    `errors: [{section, error}]` con lo que fallo, si algo fallo.
    """
    if not user.puede("padron", "viviendas", "ver"):
        raise HTTPException(403, "Sin permiso")

    result: dict = {
        "comunidades": [],
        "referentes": [],
        "subsidios": [],
        "catalogo": [],
        "config": {},
        "user": {
            "id": user.user_id,
            "nombre": user.nombre,
            "tenant_schema": user.tenant_schema,
        },
        "sync_at": datetime.now().isoformat(),
        "errors": [],
    }

    # === 1. Comunidades ===
    try:
        async with tenant_session(user.tenant_schema) as ts:
            rows = (await ts.execute(text(
                "SELECT id, nombre, referente_principal_id, activa "
                "FROM comunidades WHERE activa = TRUE ORDER BY nombre"
            ))).mappings().all()
            result["comunidades"] = [dict(r) for r in rows]
    except Exception as exc:
        logger.exception("Bootstrap: comunidades")
        result["errors"].append({"section": "comunidades", "error": str(exc)})

    # === 2. Referentes ===
    try:
        async with tenant_session(user.tenant_schema) as ts:
            rows = (await ts.execute(text(
                "SELECT id, nombre_completo, cargo, dni, telefono, foto_url "
                "FROM referentes WHERE activo = TRUE ORDER BY nombre_completo"
            ))).mappings().all()
            result["referentes"] = [dict(r) for r in rows]
    except Exception as exc:
        logger.exception("Bootstrap: referentes")
        result["errors"].append({"section": "referentes", "error": str(exc)})

    # === 3. Subsidios vigentes (+ comunidades cubiertas, query separada) ===
    try:
        async with tenant_session(user.tenant_schema) as ts:
            sub_rows = (await ts.execute(text(
                "SELECT id, nombre, porcentaje, base_legal, "
                "       vigente_desde, vigente_hasta, observaciones "
                "FROM subsidios "
                "WHERE vigente_hasta IS NULL OR vigente_hasta >= CURRENT_DATE "
                "ORDER BY vigente_desde DESC"
            ))).mappings().all()

            subsidios: list[dict] = []
            for s in sub_rows:
                d = dict(s)
                d["vigente_desde"] = d["vigente_desde"].isoformat() if d.get("vigente_desde") else None
                d["vigente_hasta"] = d["vigente_hasta"].isoformat() if d.get("vigente_hasta") else None
                d["porcentaje"] = float(d["porcentaje"]) if d.get("porcentaje") is not None else None

                com_rows = (await ts.execute(
                    text("SELECT comunidad_id FROM subsidio_comunidades WHERE subsidio_id = :sid"),
                    {"sid": d["id"]},
                )).all()
                d["comunidad_ids"] = [r[0] for r in com_rows]
                subsidios.append(d)
            result["subsidios"] = subsidios
    except Exception as exc:
        logger.exception("Bootstrap: subsidios")
        result["errors"].append({"section": "subsidios", "error": str(exc)})

    # === 4. Catalogo de artefactos (publico + propios) ===
    # Dos SELECTs porque las columnas no coinciden 1:1 con artefacto_propio.
    # Nota: la columna real del catalogo publico es `tarifa_sugerida`
    # (verificado en empadronamiento_service y wizard paso4), no `tarifa_default`.
    try:
        async with tenant_session(user.tenant_schema) as ts:
            cat_publico = (await ts.execute(text(
                "SELECT ac.id AS catalogo_id, 'catalogo' AS origen, "
                "       ac.codigo, ac.nombre, ac.categoria, ac.icono, "
                "       COALESCE(cfg.tarifa_mensual, ac.tarifa_sugerida) AS tarifa, "
                "       TRUE AS habilitado "
                "FROM public.artefacto_catalogo ac "
                "LEFT JOIN artefacto_config cfg ON cfg.catalogo_id = ac.id "
                "WHERE COALESCE(cfg.habilitado, ac.activo_default) = TRUE "
                "ORDER BY ac.categoria, ac.orden, ac.nombre"
            ))).mappings().all()

            cat_propios = (await ts.execute(text(
                "SELECT id, 'propio' AS origen, codigo, nombre, categoria, "
                "       NULL AS icono, tarifa_mensual AS tarifa, habilitado "
                "FROM artefacto_propio WHERE habilitado = TRUE "
                "ORDER BY categoria, orden, nombre"
            ))).mappings().all()

            catalogo: list[dict] = []
            for r in cat_publico:
                d = dict(r)
                d["tarifa"] = float(d["tarifa"]) if d.get("tarifa") is not None else 0.0
                d["key"] = f"catalogo:{d['codigo']}"
                catalogo.append(d)
            for r in cat_propios:
                d = dict(r)
                d["tarifa"] = float(d["tarifa"]) if d.get("tarifa") is not None else 0.0
                d["key"] = f"propio:{d['codigo']}"
                catalogo.append(d)
            result["catalogo"] = catalogo
    except Exception as exc:
        logger.exception("Bootstrap: catalogo")
        result["errors"].append({"section": "catalogo", "error": str(exc)})

    # === 5. Configuracion del municipio (key-value) ===
    try:
        async with tenant_session(user.tenant_schema) as ts:
            rows = (await ts.execute(text(
                "SELECT clave, valor, tipo FROM config_municipio"
            ))).mappings().all()

            config: dict = {}
            for r in rows:
                clave = r["clave"]
                valor = r["valor"]
                tipo = (r.get("tipo") or "string").lower()
                if tipo in ("decimal", "numeric", "float"):
                    try:
                        config[clave] = float(valor) if valor is not None else 0.0
                    except (TypeError, ValueError):
                        config[clave] = 0.0
                elif tipo in ("int", "integer"):
                    try:
                        config[clave] = int(valor) if valor is not None else 0
                    except (TypeError, ValueError):
                        config[clave] = 0
                elif tipo in ("bool", "boolean"):
                    config[clave] = str(valor).lower() in ("true", "1", "si", "yes")
                else:
                    config[clave] = valor
            result["config"] = config
    except Exception as exc:
        logger.exception("Bootstrap: config")
        result["errors"].append({"section": "config", "error": str(exc)})

    total = (
        len(result["comunidades"]) + len(result["referentes"])
        + len(result["subsidios"]) + len(result["catalogo"])
    )
    logger.info(
        "Bootstrap user_id=%s tenant=%s: %s items, %s errores",
        user.user_id, user.tenant_schema, total, len(result["errors"]),
    )
    return JSONResponse(result)


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


@router.get("/dni-check")
async def dni_check(
    request: Request,
    dni: str,
    user: CurrentUser = Depends(require_password_changed),
):
    """Devuelve si un DNI ya es jefe de familia de alguna vivienda activa.

    Usado por el wizard paso 2 para avisar al usuario apenas escribe los 8
    digitos — evita llegar al paso 4 y descubrir el conflicto al sincronizar.
    """
    if not dni or len(dni) != 8 or not dni.isdigit():
        return JSONResponse({"existe": False})

    async with tenant_session(user.tenant_schema) as ts:
        row = (await ts.execute(text(
            "SELECT v.codigo_interno "
            "FROM moradores m JOIN viviendas v ON v.id = m.vivienda_id "
            "WHERE m.dni = :dni AND m.es_jefe_familia = TRUE "
            "  AND m.activo = TRUE AND v.activa = TRUE "
            "  AND v.anulada_at IS NULL "
            "LIMIT 1"
        ), {"dni": dni})).mappings().first()

    if row:
        return JSONResponse({"existe": True, "codigo_interno": row["codigo_interno"]})
    return JSONResponse({"existe": False})
