"""
Padrón de viviendas: listado, ficha, wizard de empadronamiento (4 pasos),
edición y baja de artefactos.

El wizard guarda progreso parcial en request.session['empadronamiento'] y
solo escribe a la BD en el paso 4 a través de empadronamiento_service.
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text

from app.context_processor import build_context
from app.database import tenant_session
from app.dependencies import CurrentUser, require_password_changed
from app.services.csrf import verify_csrf
from app.services.empadronamiento_service import (
    EmpadronamientoError,
    crear_vivienda_completa,
)
from app.services.inventario_service import (
    InventarioError,
    dar_de_baja_artefacto,
    inventario_actual_de_vivienda,
)
from app.utils.dni import DniInvalido, validar_dni
from app.utils.flash import set_flash

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/app/padron")

SESSION_KEY = "empadronamiento"
MOTIVOS_BAJA = ["vendido", "malogrado", "autoreporte_morador", "correccion"]


# ---------- listado ----------

@router.get("/", response_class=HTMLResponse)
async def listar(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
    comunidad: Optional[int] = None,
    estado: Optional[str] = None,
    q: Optional[str] = None,
    page: int = 1,
):
    if not user.puede("padron", "viviendas", "ver"):
        raise HTTPException(403, "Sin permiso")
    page = max(1, page)
    page_size = 25
    offset = (page - 1) * page_size

    filtros_sql = ["v.activa = TRUE"]
    params: dict = {"limit": page_size, "offset": offset}

    if comunidad:
        filtros_sql.append("v.comunidad_id = :comunidad")
        params["comunidad"] = comunidad
    if estado in ("activo", "cortado", "suspendido"):
        filtros_sql.append("v.estado_servicio = :estado")
        params["estado"] = estado
    if q:
        q_clean = q.strip()
        params["q"] = f"%{q_clean}%"
        if q_clean.isdigit() and len(q_clean) == 8:
            params["dni"] = q_clean
            filtros_sql.append(
                "(v.codigo_interno ILIKE :q OR EXISTS ("
                "SELECT 1 FROM moradores m WHERE m.vivienda_id = v.id AND m.dni = :dni))"
            )
        else:
            filtros_sql.append("v.codigo_interno ILIKE :q")

    where = " AND ".join(filtros_sql)

    async with tenant_session(user.tenant_schema) as ts:
        rows = (
            await ts.execute(
                text(
                    f"SELECT v.id, v.codigo_interno, v.estado_servicio, v.referencia_fisica, "
                    f"       v.empadronada_at, c.nombre AS comunidad_nombre, "
                    f"       (SELECT m.nombre_completo FROM moradores m "
                    f"        WHERE m.vivienda_id = v.id AND m.es_jefe_familia = TRUE "
                    f"        AND m.activo = TRUE LIMIT 1) AS jefe_nombre "
                    f"FROM viviendas v LEFT JOIN comunidades c ON c.id = v.comunidad_id "
                    f"WHERE {where} "
                    f"ORDER BY v.empadronada_at DESC LIMIT :limit OFFSET :offset"
                ),
                params,
            )
        ).all()
        total = (
            await ts.execute(
                text(f"SELECT COUNT(*) FROM viviendas v WHERE {where}"),
                {k: v for k, v in params.items() if k not in ("limit", "offset")},
            )
        ).scalar_one()
        comunidades = (
            await ts.execute(
                text("SELECT id, nombre FROM comunidades WHERE activa = TRUE ORDER BY nombre")
            )
        ).all()

    return request.app.state.templates.TemplateResponse(
        "tenant/padron/lista.html",
        build_context(
            request, user=user,
            viviendas=rows, total=total,
            page=page, page_size=page_size,
            comunidades=comunidades,
            filtros={"comunidad": comunidad, "estado": estado, "q": q or ""},
        ),
    )


# ---------- ficha ----------

@router.get("/{codigo}", response_class=HTMLResponse)
async def ficha(
    request: Request,
    codigo: str,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("padron", "viviendas", "ver"):
        raise HTTPException(403, "Sin permiso")
    async with tenant_session(user.tenant_schema) as ts:
        vivienda = (
            await ts.execute(
                text(
                    "SELECT v.*, c.nombre AS comunidad_nombre, "
                    "       r.nombre_completo AS referente_nombre "
                    "FROM viviendas v LEFT JOIN comunidades c ON c.id = v.comunidad_id "
                    "LEFT JOIN referentes r ON r.id = v.referente_id "
                    "WHERE v.codigo_interno = :c"
                ),
                {"c": codigo},
            )
        ).first()
        if not vivienda:
            raise HTTPException(404, "Vivienda no encontrada")

        moradores = (
            await ts.execute(
                text(
                    "SELECT id, dni, nombre_completo, fecha_nacimiento, sexo, telefono, "
                    "       es_jefe_familia, es_responsable_pago, acceso_portal, activo "
                    "FROM moradores WHERE vivienda_id = :v AND activo = TRUE "
                    "ORDER BY es_jefe_familia DESC, nombre_completo"
                ),
                {"v": vivienda.id},
            )
        ).all()

        inv_actual = await inventario_actual_de_vivienda(ts, vivienda.id)

        historico = (
            await ts.execute(
                text(
                    "SELECT id, artefacto_nombre_snapshot, cantidad, vigente_desde, "
                    "       vigente_hasta, motivo_baja "
                    "FROM vivienda_inventario "
                    "WHERE vivienda_id = :v AND vigente_hasta IS NOT NULL "
                    "ORDER BY vigente_hasta DESC LIMIT 50"
                ),
                {"v": vivienda.id},
            )
        ).all()

        eventos = (
            await ts.execute(
                text(
                    "SELECT tipo, descripcion, created_at FROM vivienda_eventos "
                    "WHERE vivienda_id = :v ORDER BY created_at DESC LIMIT 50"
                ),
                {"v": vivienda.id},
            )
        ).all()

    return request.app.state.templates.TemplateResponse(
        "tenant/padron/ficha.html",
        build_context(
            request, user=user,
            vivienda=vivienda, moradores=moradores,
            inventario_actual=inv_actual, inventario_historico=historico,
            eventos=eventos,
            motivos_baja=MOTIVOS_BAJA,
        ),
    )


# ---------- wizard ----------

def _wizard_session(request: Request) -> dict:
    return request.session.get(SESSION_KEY, {"paso": 1, "datos": {}})


def _save_wizard(request: Request, w: dict) -> None:
    request.session[SESSION_KEY] = w


def _clear_wizard(request: Request) -> None:
    request.session.pop(SESSION_KEY, None)


@router.get("/nuevo", response_class=HTMLResponse)
async def wizard_inicio(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("padron", "viviendas", "crear"):
        raise HTTPException(403, "Sin permiso")
    _clear_wizard(request)
    return RedirectResponse("/app/padron/nuevo/paso1", status_code=303)


# Paso 1: vivienda + referente
@router.get("/nuevo/paso1", response_class=HTMLResponse)
async def wizard_paso1_form(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("padron", "viviendas", "crear"):
        raise HTTPException(403, "Sin permiso")
    w = _wizard_session(request)
    async with tenant_session(user.tenant_schema) as ts:
        comunidades = (
            await ts.execute(
                text("SELECT id, nombre FROM comunidades WHERE activa = TRUE ORDER BY nombre")
            )
        ).all()
        referentes = (
            await ts.execute(
                text("SELECT id, nombre_completo, cargo FROM referentes WHERE activo = TRUE ORDER BY nombre_completo")
            )
        ).all()
    return request.app.state.templates.TemplateResponse(
        "tenant/padron/wizard_paso1_vivienda.html",
        build_context(
            request, user=user,
            comunidades=comunidades, referentes=referentes,
            datos=w.get("datos", {}),
        ),
    )


@router.post("/nuevo/paso1", dependencies=[Depends(verify_csrf)])
async def wizard_paso1_submit(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
    comunidad_id: int = Form(...),
    referente_id: str = Form(""),
    fuente_validacion: str = Form(""),
    referencia_fisica: str = Form(...),
    direccion_textual: str = Form(""),
    gps_lat: str = Form(""),
    gps_lng: str = Form(""),
    gps_precision: str = Form(""),
):
    if not user.puede("padron", "viviendas", "crear"):
        raise HTTPException(403, "Sin permiso")
    w = _wizard_session(request)
    w["datos"] = w.get("datos", {})
    w["datos"]["paso1"] = {
        "comunidad_id": comunidad_id,
        "referente_id": int(referente_id) if referente_id.strip() else None,
        "fuente_validacion": fuente_validacion.strip() or None,
        "referencia_fisica": referencia_fisica.strip(),
        "direccion_textual": direccion_textual.strip() or None,
        "gps_lat": gps_lat.strip() or None,
        "gps_lng": gps_lng.strip() or None,
        "gps_precision": int(gps_precision) if gps_precision.strip().isdigit() else None,
    }
    w["paso"] = 2
    _save_wizard(request, w)
    return RedirectResponse("/app/padron/nuevo/paso2", status_code=303)


# Paso 2: jefe de familia
@router.get("/nuevo/paso2", response_class=HTMLResponse)
async def wizard_paso2_form(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("padron", "viviendas", "crear"):
        raise HTTPException(403, "Sin permiso")
    w = _wizard_session(request)
    if "paso1" not in w.get("datos", {}):
        return RedirectResponse("/app/padron/nuevo/paso1", status_code=303)
    return request.app.state.templates.TemplateResponse(
        "tenant/padron/wizard_paso2_jefe.html",
        build_context(request, user=user, datos=w.get("datos", {})),
    )


@router.post("/nuevo/paso2", dependencies=[Depends(verify_csrf)])
async def wizard_paso2_submit(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
    dni: str = Form(...),
    nombre_completo: str = Form(...),
    fecha_nacimiento: str = Form(""),
    sexo: str = Form(""),
    telefono: str = Form(""),
    acceso_portal: Optional[str] = Form(None),
):
    if not user.puede("padron", "viviendas", "crear"):
        raise HTTPException(403, "Sin permiso")
    w = _wizard_session(request)
    if "paso1" not in w.get("datos", {}):
        return RedirectResponse("/app/padron/nuevo/paso1", status_code=303)

    try:
        dni_clean = validar_dni(dni)
    except DniInvalido as exc:
        set_flash(request, "error", str(exc))
        return RedirectResponse("/app/padron/nuevo/paso2", status_code=303)

    w["datos"]["paso2"] = {
        "dni": dni_clean,
        "nombre_completo": nombre_completo.strip(),
        "fecha_nacimiento": fecha_nacimiento.strip() or None,
        "sexo": sexo.strip().upper()[:1] if sexo.strip() else None,
        "telefono": telefono.strip() or None,
        "acceso_portal": acceso_portal == "on",
    }
    w["paso"] = 3
    _save_wizard(request, w)
    return RedirectResponse("/app/padron/nuevo/paso3", status_code=303)


# Paso 3: segundo morador (opcional)
@router.get("/nuevo/paso3", response_class=HTMLResponse)
async def wizard_paso3_form(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("padron", "viviendas", "crear"):
        raise HTTPException(403, "Sin permiso")
    w = _wizard_session(request)
    if "paso2" not in w.get("datos", {}):
        return RedirectResponse("/app/padron/nuevo/paso2", status_code=303)
    return request.app.state.templates.TemplateResponse(
        "tenant/padron/wizard_paso3_segundo.html",
        build_context(request, user=user, datos=w.get("datos", {})),
    )


@router.post("/nuevo/paso3", dependencies=[Depends(verify_csrf)])
async def wizard_paso3_submit(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
    accion: str = Form("continuar"),
    dni: str = Form(""),
    nombre_completo: str = Form(""),
    fecha_nacimiento: str = Form(""),
    sexo: str = Form(""),
    telefono: str = Form(""),
):
    if not user.puede("padron", "viviendas", "crear"):
        raise HTTPException(403, "Sin permiso")
    w = _wizard_session(request)
    if "paso2" not in w.get("datos", {}):
        return RedirectResponse("/app/padron/nuevo/paso2", status_code=303)

    if accion == "omitir" or not dni.strip():
        w["datos"]["paso3"] = None
    else:
        try:
            dni_clean = validar_dni(dni)
        except DniInvalido as exc:
            set_flash(request, "error", str(exc))
            return RedirectResponse("/app/padron/nuevo/paso3", status_code=303)
        if dni_clean == w["datos"]["paso2"]["dni"]:
            set_flash(request, "error", "El segundo morador no puede tener el mismo DNI del jefe.")
            return RedirectResponse("/app/padron/nuevo/paso3", status_code=303)
        w["datos"]["paso3"] = {
            "dni": dni_clean,
            "nombre_completo": nombre_completo.strip(),
            "fecha_nacimiento": fecha_nacimiento.strip() or None,
            "sexo": sexo.strip().upper()[:1] if sexo.strip() else None,
            "telefono": telefono.strip() or None,
        }
    w["paso"] = 4
    _save_wizard(request, w)
    return RedirectResponse("/app/padron/nuevo/paso4", status_code=303)


# Paso 4: inventario + foto
@router.get("/nuevo/paso4", response_class=HTMLResponse)
async def wizard_paso4_form(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("padron", "viviendas", "crear"):
        raise HTTPException(403, "Sin permiso")
    w = _wizard_session(request)
    if "paso2" not in w.get("datos", {}):
        return RedirectResponse("/app/padron/nuevo/paso1", status_code=303)

    async with tenant_session(user.tenant_schema) as ts:
        catalogo = (
            await ts.execute(
                text(
                    "SELECT ac.id, ac.codigo, ac.nombre, ac.categoria, ac.icono, "
                    "       COALESCE(cfg.tarifa_mensual, ac.tarifa_sugerida) AS tarifa "
                    "FROM public.artefacto_catalogo ac "
                    "LEFT JOIN artefacto_config cfg ON cfg.catalogo_id = ac.id "
                    "WHERE (cfg.habilitado IS NULL AND ac.activo_default = TRUE) "
                    "   OR cfg.habilitado = TRUE "
                    "ORDER BY ac.categoria, ac.orden, ac.nombre"
                )
            )
        ).all()
        propios = (
            await ts.execute(
                text(
                    "SELECT codigo, nombre, categoria, tarifa_mensual AS tarifa "
                    "FROM artefacto_propio WHERE habilitado = TRUE "
                    "ORDER BY categoria, orden, nombre"
                )
            )
        ).all()

        cfg_rows = (
            await ts.execute(
                text(
                    "SELECT clave, valor FROM config_municipio "
                    "WHERE clave IN ('cargo_fijo_mensual', 'adicional_por_morador')"
                )
            )
        ).all()
        config = {r.clave: r.valor for r in cfg_rows}

    return request.app.state.templates.TemplateResponse(
        "tenant/padron/wizard_paso4_inventario.html",
        build_context(
            request, user=user,
            datos=w.get("datos", {}),
            catalogo=catalogo, propios=propios, config=config,
        ),
    )


@router.post("/nuevo/paso4", dependencies=[Depends(verify_csrf)])
async def wizard_paso4_submit(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
    inventario_json: str = Form(...),
    foto_fachada: UploadFile = File(...),
):
    if not user.puede("padron", "viviendas", "crear"):
        raise HTTPException(403, "Sin permiso")
    w = _wizard_session(request)
    datos = w.get("datos", {})
    if "paso1" not in datos or "paso2" not in datos:
        return RedirectResponse("/app/padron/nuevo/paso1", status_code=303)

    try:
        items = json.loads(inventario_json)
        if not isinstance(items, list):
            raise ValueError("inventario_json debe ser lista")
    except (json.JSONDecodeError, ValueError) as exc:
        set_flash(request, "error", f"Inventario inválido: {exc}")
        return RedirectResponse("/app/padron/nuevo/paso4", status_code=303)

    foto_bytes = await foto_fachada.read()
    if not foto_bytes:
        set_flash(request, "error", "La foto de fachada es obligatoria.")
        return RedirectResponse("/app/padron/nuevo/paso4", status_code=303)

    p1 = datos["paso1"]
    p2 = datos["paso2"]
    p3 = datos.get("paso3")

    datos_vivienda = {
        "comunidad_id": p1["comunidad_id"],
        "referente_id": p1.get("referente_id"),
        "fuente_validacion": p1.get("fuente_validacion"),
        "referencia_fisica": p1["referencia_fisica"],
        "direccion_textual": p1.get("direccion_textual"),
        "gps_lat": p1.get("gps_lat"),
        "gps_lng": p1.get("gps_lng"),
        "gps_precision_metros": p1.get("gps_precision"),
    }

    async with tenant_session(user.tenant_schema) as ts:
        try:
            result = await crear_vivienda_completa(
                ts,
                schema_name=user.tenant_schema,
                user_id=user.user_id,
                datos_vivienda=datos_vivienda,
                jefe_familia=p2,
                segundo_morador=p3,
                artefactos=items,
                foto_fachada_bytes=foto_bytes,
                foto_fachada_content_type=foto_fachada.content_type or "image/jpeg",
            )
        except EmpadronamientoError as exc:
            set_flash(request, "error", f"No se pudo guardar la vivienda: {exc}")
            return RedirectResponse("/app/padron/nuevo/paso4", status_code=303)

    _clear_wizard(request)
    set_flash(request, "success", f"Vivienda {result['codigo_interno']} empadronada correctamente.")
    return RedirectResponse(f"/app/padron/{result['codigo_interno']}", status_code=303)


# ---------- baja artefacto ----------

@router.post("/{codigo}/inventario/{inv_id}/baja", dependencies=[Depends(verify_csrf)])
async def baja_artefacto(
    request: Request,
    codigo: str,
    inv_id: int,
    user: CurrentUser = Depends(require_password_changed),
    motivo: str = Form(...),
):
    if not user.puede("inventario", "aprobar_baja", "aprobar") and not user.puede("inventario", "editar", "editar"):
        raise HTTPException(403, "Sin permiso")
    if motivo not in MOTIVOS_BAJA:
        set_flash(request, "error", "Motivo de baja inválido.")
        return RedirectResponse(f"/app/padron/{codigo}", status_code=303)
    async with tenant_session(user.tenant_schema) as ts:
        try:
            await dar_de_baja_artefacto(ts, inv_id, user.user_id, motivo)
            await ts.commit()
        except InventarioError as exc:
            await ts.rollback()
            set_flash(request, "error", str(exc))
            return RedirectResponse(f"/app/padron/{codigo}", status_code=303)
    set_flash(request, "success", "Artefacto dado de baja.")
    return RedirectResponse(f"/app/padron/{codigo}", status_code=303)
