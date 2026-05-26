"""Subsidios: CRUD con confirmación escalonada según porcentaje."""
import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text

from app.context_processor import build_context
from app.database import tenant_session
from app.dependencies import CurrentUser, require_password_changed
from app.services.csrf import verify_csrf
from app.services.subsidio_service import (
    SubsidioError,
    crear_subsidio,
    listar_subsidios,
    obtener_subsidio,
    suspender_subsidio,
)
from app.utils.flash import set_flash

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/app/subsidios")


def _parse_porcentaje(raw: str) -> Decimal:
    try:
        v = Decimal(str(raw).strip().replace(",", "."))
    except (InvalidOperation, AttributeError, ValueError) as exc:
        raise SubsidioError(f"Porcentaje inválido: '{raw}'") from exc
    if v < 0 or v > 100:
        raise SubsidioError("Porcentaje debe estar entre 0 y 100.")
    return v


def _parse_fecha(raw: str, campo: str) -> date:
    raw = (raw or "").strip()
    if not raw:
        raise SubsidioError(f"{campo} es obligatorio.")
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise SubsidioError(f"{campo} inválido (formato YYYY-MM-DD).") from exc


@router.get("/", response_class=HTMLResponse)
async def listar(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("subsidios", "config", "ver"):
        raise HTTPException(403, "Sin permiso")
    async with tenant_session(user.tenant_schema) as ts:
        subsidios = await listar_subsidios(ts, solo_vigentes=False)
    return request.app.state.templates.TemplateResponse(
        "tenant/subsidios/lista.html",
        build_context(request, user=user, subsidios=subsidios, today=date.today()),
    )


@router.get("/nuevo", response_class=HTMLResponse)
async def nuevo_form(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("subsidios", "config", "crear"):
        raise HTTPException(403, "Sin permiso")
    async with tenant_session(user.tenant_schema) as ts:
        comunidades = (
            await ts.execute(
                text("SELECT id, nombre FROM comunidades WHERE activa = TRUE ORDER BY nombre")
            )
        ).all()
    return request.app.state.templates.TemplateResponse(
        "tenant/subsidios/form.html",
        build_context(
            request, user=user, comunidades=comunidades,
            datos={"vigente_desde": date.today().isoformat()},
        ),
    )


@router.post("/nuevo", dependencies=[Depends(verify_csrf)])
async def nuevo_submit(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
    nombre: str = Form(...),
    porcentaje: str = Form(...),
    base_legal: str = Form(...),
    vigente_desde: str = Form(...),
    observaciones: str = Form(""),
    comunidad_ids: list[int] = Form(default=[]),
):
    if not user.puede("subsidios", "config", "crear"):
        raise HTTPException(403, "Sin permiso")
    try:
        porcentaje_dec = _parse_porcentaje(porcentaje)
        vd = _parse_fecha(vigente_desde, "Vigente desde")
        async with tenant_session(user.tenant_schema) as ts:
            subsidio_id = await crear_subsidio(
                ts,
                nombre=nombre,
                porcentaje=porcentaje_dec,
                base_legal=base_legal,
                vigente_desde=vd,
                observaciones=observaciones or None,
                comunidad_ids=comunidad_ids,
                user_id=user.user_id,
            )
            await ts.commit()
    except SubsidioError as exc:
        set_flash(request, "error", str(exc))
        return RedirectResponse("/app/subsidios/nuevo", status_code=303)
    set_flash(request, "success", f"Subsidio creado (id {subsidio_id}).")
    return RedirectResponse(f"/app/subsidios/{subsidio_id}", status_code=303)


@router.get("/{subsidio_id}", response_class=HTMLResponse)
async def detalle(
    request: Request,
    subsidio_id: int,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("subsidios", "config", "ver"):
        raise HTTPException(403, "Sin permiso")
    async with tenant_session(user.tenant_schema) as ts:
        subsidio = await obtener_subsidio(ts, subsidio_id)
    if not subsidio:
        raise HTTPException(404, "Subsidio no encontrado")
    return request.app.state.templates.TemplateResponse(
        "tenant/subsidios/detalle.html",
        build_context(request, user=user, subsidio=subsidio, today=date.today()),
    )


@router.post("/{subsidio_id}/suspender", dependencies=[Depends(verify_csrf)])
async def suspender(
    request: Request,
    subsidio_id: int,
    user: CurrentUser = Depends(require_password_changed),
    motivo: str = Form(...),
):
    if not user.puede("subsidios", "config", "suspender"):
        raise HTTPException(403, "Sin permiso")
    try:
        async with tenant_session(user.tenant_schema) as ts:
            await suspender_subsidio(ts, subsidio_id, motivo, user.user_id)
            await ts.commit()
    except SubsidioError as exc:
        set_flash(request, "error", str(exc))
        return RedirectResponse(f"/app/subsidios/{subsidio_id}", status_code=303)
    set_flash(request, "success", "Subsidio suspendido.")
    return RedirectResponse(f"/app/subsidios/{subsidio_id}", status_code=303)
