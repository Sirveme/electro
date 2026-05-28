"""
Cobranza v2 — Tablero simple y rápido para el cobrador en campo.

Rutas (todas bajo /app/cobranza, coexisten con las viejas de cobranza.py):
- GET  /app/cobranza/                     tablero principal
- GET  /app/cobranza/vivienda/{c}/cuotas  cuotas impagas (JSON) para el modal
- POST /app/cobranza/registrar            registra cobro multi-cuota
- POST /app/cobranza/abrir-caja-rapido    abre caja con monto inicial 0 (1 click)

NO duplica funcionalidad de cobranza.py: la ruta /app/cobranza/ no existia
antes y las nuevas /cuotas y /registrar son JSON-only. El form viejo de
cobro inline (vivienda/{c}/cobrar) sigue funcionando por compatibilidad.

Schema real (no el del spec):
- `cuotas.saldo_pendiente` (no monto_pendiente), `cuotas.total` (no monto_total),
  `cuotas.periodo_anio + periodo_mes` (no `periodo` único).
- `cuotas.estado = 'pagado'` (no 'pagada').
- `caja_aperturas.cajero_user_id` (no usuario_id).
- `registrar_pago` signature: (session, cuota_id, monto, metodo, user_id,
  caja_apertura_id, observaciones, referencia_externa).
"""
from __future__ import annotations

import logging
from collections import Counter
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text

from app.context_processor import build_context
from app.database import tenant_session
from app.dependencies import CurrentUser, require_password_changed
from app.services.csrf import verify_csrf
from app.services.caja_service import abrir_caja, caja_abierta_de, CajaError
from app.services.pago_service import registrar_pago, PagoError
from app.utils.periodos import nombre_periodo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/app/cobranza")


# Stopwords para el extractor de etiquetas. Palabras de relleno comunes en
# referencias fisicas que NO aportan informacion de zona.
_STOPWORDS = {
    "de", "la", "el", "en", "a", "con", "por", "del", "al", "los", "las",
    "un", "una", "y", "o", "casa", "frente", "costado", "lado", "cerca",
    "espaldas", "principal", "esquina", "calle", "avenida", "jiron", "jr",
    "av", "para", "sin", "sobre", "entre", "hacia", "izquierda", "derecha",
    "metros", "metro", "inercepcion", "interseccion", "interseccion",
}


def _extraer_etiquetas(referencias: list[str], top_n: int = 6) -> list[str]:
    """Top palabras frecuentes (>=1 vivienda) que sirvan como etiqueta.

    Umbral en 1: con pocas viviendas (al inicio del despliegue) ninguna
    palabra se repetia y la barra de etiquetas quedaba vacia, perdiendo
    su utilidad. Bajado a 1 — las etiquetas aparecen desde la primera
    vivienda empadronada.
    """
    contador: Counter[str] = Counter()
    for ref in referencias:
        if not ref:
            continue
        # Normalizacion liviana — minusculas, separadores por espacio
        cleaned = ref.lower().replace(",", " ").replace(".", " ").replace("/", " ")
        for palabra in cleaned.split():
            palabra = palabra.strip("()[]\"'")
            if len(palabra) < 4 or palabra in _STOPWORDS or palabra.isdigit():
                continue
            contador[palabra] += 1
    return [p.capitalize() for p, freq in contador.most_common(top_n) if freq >= 1]


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def tablero(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
    q: str = "",
    etiqueta: str = "",
):
    """Tablero principal de cobranza: stats + filtros + lista de viviendas."""
    if not user.puede("cobranza", "recibos", "ver"):
        raise HTTPException(403, "Sin permiso")

    async with tenant_session(user.tenant_schema) as ts:
        caja = await caja_abierta_de(ts, user.user_id)

        cobrado_hoy = 0.0
        if caja:
            r = (
                await ts.execute(
                    text(
                        "SELECT COALESCE(SUM(monto), 0) AS total "
                        "FROM pagos WHERE caja_apertura_id = :cid AND anulado = FALSE"
                    ),
                    {"cid": caja["id"]},
                )
            ).first()
            cobrado_hoy = float(r.total) if r else 0.0

        totales = (
            await ts.execute(
                text(
                    "SELECT "
                    "  COUNT(*) FILTER (WHERE activa = TRUE AND anulada_at IS NULL) AS activas, "
                    "  COUNT(*) FILTER ("
                    "    WHERE activa = TRUE AND anulada_at IS NULL "
                    "    AND id IN (SELECT DISTINCT vivienda_id FROM cuotas WHERE estado != 'pagado')"
                    "  ) AS con_deuda "
                    "FROM viviendas"
                )
            )
        ).first()

        refs = (
            await ts.execute(
                text(
                    "SELECT referencia_fisica FROM viviendas "
                    "WHERE activa = TRUE AND anulada_at IS NULL "
                    "  AND referencia_fisica IS NOT NULL"
                )
            )
        ).all()
        etiquetas = _extraer_etiquetas([r[0] for r in refs])

        # Lista de viviendas con filtros
        where_clauses = ["v.activa = TRUE", "v.anulada_at IS NULL"]
        params: dict = {}
        if q:
            # Buscar tambien en referencia_fisica — el usuario reportó que no
            # encontraba "iglesia" / "puente" aunque estaban en la referencia.
            where_clauses.append(
                "(v.codigo_interno ILIKE :q OR m.dni ILIKE :q "
                "OR m.nombre_completo ILIKE :q OR v.referencia_fisica ILIKE :q)"
            )
            params["q"] = f"%{q.strip()}%"
        if etiqueta:
            where_clauses.append("v.referencia_fisica ILIKE :etiqueta")
            params["etiqueta"] = f"%{etiqueta}%"
        where_sql = " AND ".join(where_clauses)

        viviendas = (
            await ts.execute(
                text(
                    f"SELECT DISTINCT "
                    f"  v.id, v.codigo_interno, v.referencia_fisica, "
                    f"  c.nombre AS comunidad, "
                    f"  m.nombre_completo AS jefe, m.dni AS jefe_dni, "
                    f"  (SELECT COUNT(*) FROM cuotas cu "
                    f"   WHERE cu.vivienda_id = v.id AND cu.estado != 'pagado') AS meses_deuda, "
                    f"  (SELECT COALESCE(SUM(cu.saldo_pendiente), 0) FROM cuotas cu "
                    f"   WHERE cu.vivienda_id = v.id AND cu.estado != 'pagado') AS deuda_total "
                    f"FROM viviendas v "
                    f"LEFT JOIN comunidades c ON c.id = v.comunidad_id "
                    f"LEFT JOIN moradores m "
                    f"  ON m.vivienda_id = v.id AND m.es_jefe_familia = TRUE AND m.activo = TRUE "
                    f"WHERE {where_sql} "
                    f"ORDER BY v.codigo_interno "
                    f"LIMIT 100"
                ),
                params,
            )
        ).mappings().all()

    return request.app.state.templates.TemplateResponse(
        "tenant/cobranza/tablero.html",
        build_context(
            request, user=user,
            caja=dict(caja) if caja else None,
            cobrado_hoy=cobrado_hoy,
            total_activas=int(totales.activas) if totales else 0,
            total_con_deuda=int(totales.con_deuda) if totales else 0,
            etiquetas=etiquetas,
            viviendas=[dict(v) for v in viviendas],
            q=q,
            etiqueta_activa=etiqueta,
            puede_cobrar=user.puede("cobranza", "pagos", "cobrar"),
            puede_abrir_caja=user.puede("caja", "diaria", "abrir"),
        ),
    )


@router.get("/vivienda/{codigo}/cuotas")
async def cuotas_impagas(
    request: Request,
    codigo: str,
    user: CurrentUser = Depends(require_password_changed),
):
    """JSON con las cuotas impagas de la vivienda (para el modal de cobro)."""
    if not user.puede("cobranza", "recibos", "ver"):
        raise HTTPException(403, "Sin permiso")

    async with tenant_session(user.tenant_schema) as ts:
        rows = (
            await ts.execute(
                text(
                    "SELECT cu.id, cu.periodo_anio, cu.periodo_mes, cu.numero_recibo, "
                    "       cu.total, cu.monto_pagado, cu.saldo_pendiente, cu.estado, "
                    "       cu.fecha_vencimiento "
                    "FROM cuotas cu "
                    "JOIN viviendas v ON v.id = cu.vivienda_id "
                    "WHERE v.codigo_interno = :c AND cu.estado != 'pagado' "
                    "ORDER BY cu.periodo_anio, cu.periodo_mes"
                ),
                {"c": codigo},
            )
        ).mappings().all()

    cuotas = [
        {
            "id": r["id"],
            "periodo": nombre_periodo(r["periodo_anio"], r["periodo_mes"]),
            "periodo_anio": r["periodo_anio"],
            "periodo_mes": r["periodo_mes"],
            "numero_recibo": r["numero_recibo"],
            "total": float(r["total"]),
            "monto_pagado": float(r["monto_pagado"]),
            "saldo_pendiente": float(r["saldo_pendiente"]),
            "estado": r["estado"],
            "vencimiento": r["fecha_vencimiento"].isoformat() if r["fecha_vencimiento"] else None,
        }
        for r in rows
    ]
    return JSONResponse({"cuotas": cuotas})


@router.post("/registrar", dependencies=[Depends(verify_csrf)])
async def registrar_cobro(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
    codigo_interno: str = Form(...),
    cuota_ids: str = Form(...),          # CSV: "12,13,14"
    metodo: str = Form("efectivo"),
    referencia_externa: str = Form(""),
    observacion: str = Form(""),
    abrir_caja_si_falta: int = Form(0),
):
    """Registra un cobro sobre 1+ cuotas. Cada cuota se paga al 100%.

    Si no hay caja abierta y abrir_caja_si_falta=1, abre caja con monto 0
    automaticamente (1 click — decision de producto P2=B).
    """
    if not user.puede("cobranza", "pagos", "cobrar"):
        raise HTTPException(403, "Sin permiso")

    try:
        ids = [int(x) for x in cuota_ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(400, "cuota_ids invalidos")
    if not ids:
        raise HTTPException(400, "Sin cuotas seleccionadas")

    async with tenant_session(user.tenant_schema) as ts:
        vid = (
            await ts.execute(
                text("SELECT id FROM viviendas WHERE codigo_interno = :c"),
                {"c": codigo_interno},
            )
        ).scalar()
        if not vid:
            raise HTTPException(404, "Vivienda no encontrada")

        # Caja: si no hay y el flag esta puesto, abrir automatica.
        caja = await caja_abierta_de(ts, user.user_id)
        if not caja and metodo == "efectivo":
            if not abrir_caja_si_falta:
                return JSONResponse(
                    {"ok": False, "error": "sin_caja",
                     "message": "No tienes caja abierta"},
                    status_code=409,
                )
            try:
                caja_id = await abrir_caja(ts, user.user_id, Decimal("0"))
            except CajaError as exc:
                return JSONResponse(
                    {"ok": False, "error": "caja_error", "message": str(exc)},
                    status_code=409,
                )
            caja = {"id": caja_id}

        # Leer saldos de las cuotas (full payment por cuota)
        cuotas_rows = (
            await ts.execute(
                text(
                    "SELECT id, vivienda_id, saldo_pendiente, estado "
                    "FROM cuotas WHERE id = ANY(:ids)"
                ),
                {"ids": ids},
            )
        ).mappings().all()
        cuotas_dict = {r["id"]: dict(r) for r in cuotas_rows}

        pago_ids: list[int] = []
        try:
            for cid in ids:
                c = cuotas_dict.get(cid)
                if not c:
                    raise PagoError(f"Cuota {cid} no existe")
                if c["vivienda_id"] != vid:
                    raise PagoError(f"Cuota {cid} no pertenece a esta vivienda")
                if c["estado"] == "pagado":
                    continue  # ya pagada por concurrencia
                monto = Decimal(str(c["saldo_pendiente"]))
                if monto <= 0:
                    continue
                pago_id = await registrar_pago(
                    ts,
                    cuota_id=cid,
                    monto=monto,
                    metodo=metodo,
                    user_id=user.user_id,
                    caja_apertura_id=caja["id"] if caja else None,
                    observaciones=observacion or None,
                    referencia_externa=referencia_externa or None,
                )
                pago_ids.append(pago_id)
            await ts.commit()
        except PagoError as exc:
            await ts.rollback()
            return JSONResponse(
                {"ok": False, "error": "pago_error", "message": str(exc)},
                status_code=409,
            )
        except Exception as exc:
            await ts.rollback()
            logger.exception("Error registrando cobro v2")
            return JSONResponse(
                {"ok": False, "error": "internal", "message": str(exc)},
                status_code=500,
            )

    return JSONResponse(
        {"ok": True, "pago_ids": pago_ids,
         "caja_apertura_id": caja["id"] if caja else None,
         "redirect": "/app/cobranza/"}
    )


@router.post("/abrir-caja-rapido", dependencies=[Depends(verify_csrf)])
async def abrir_caja_rapido(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
):
    """Abre caja con monto inicial 0 desde el tablero (1 click)."""
    if not user.puede("caja", "diaria", "abrir"):
        raise HTTPException(403, "Sin permiso")
    async with tenant_session(user.tenant_schema) as ts:
        try:
            caja_id = await abrir_caja(ts, user.user_id, Decimal("0"))
            await ts.commit()
        except CajaError as exc:
            return JSONResponse(
                {"ok": False, "message": str(exc)},
                status_code=409,
            )
    return JSONResponse({"ok": True, "caja_id": caja_id})
