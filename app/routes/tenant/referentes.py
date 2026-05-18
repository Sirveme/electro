"""CRUD de referentes (párroco, líderes, etc.)."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text

from app.context_processor import build_context
from app.database import tenant_session
from app.dependencies import CurrentUser, require_password_changed
from app.utils.flash import set_flash

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/app/referentes")

CARGOS_VALIDOS = ["parroco", "lider_religioso", "lider_politico", "repr_municipal", "otro"]


@router.get("/", response_class=HTMLResponse)
async def listar(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("padron", "referentes", "ver"):
        raise HTTPException(403, "Sin permiso")
    async with tenant_session(user.tenant_schema) as ts:
        rows = (
            await ts.execute(
                text(
                    "SELECT id, nombre_completo, cargo, dni, telefono, activo "
                    "FROM referentes ORDER BY activo DESC, nombre_completo"
                )
            )
        ).all()
    return request.app.state.templates.TemplateResponse(
        "tenant/referentes/lista.html",
        build_context(request, user=user, referentes=rows),
    )


@router.get("/nuevo", response_class=HTMLResponse)
async def nuevo_form(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("padron", "referentes", "editar"):
        raise HTTPException(403, "Sin permiso")
    return request.app.state.templates.TemplateResponse(
        "tenant/referentes/form.html",
        build_context(request, user=user, referente=None, cargos=CARGOS_VALIDOS),
    )


@router.post("/nuevo")
async def nuevo_submit(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
    nombre_completo: str = Form(...),
    cargo: str = Form(...),
    dni: str = Form(""),
    telefono: str = Form(""),
    foto_url: str = Form(""),
):
    if not user.puede("padron", "referentes", "editar"):
        raise HTTPException(403, "Sin permiso")
    if cargo not in CARGOS_VALIDOS:
        set_flash(request, "error", "Cargo inválido.")
        return RedirectResponse("/app/referentes/nuevo", status_code=303)
    async with tenant_session(user.tenant_schema) as ts:
        await ts.execute(
            text(
                "INSERT INTO referentes (nombre_completo, cargo, dni, telefono, foto_url, activo) "
                "VALUES (:n, :c, :d, :t, :f, TRUE)"
            ),
            {
                "n": nombre_completo.strip(), "c": cargo,
                "d": dni.strip() or None, "t": telefono.strip() or None,
                "f": foto_url.strip() or None,
            },
        )
        await ts.commit()
    set_flash(request, "success", "Referente creado.")
    return RedirectResponse("/app/referentes/", status_code=303)


@router.get("/{ref_id}/editar", response_class=HTMLResponse)
async def editar_form(
    request: Request,
    ref_id: int,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("padron", "referentes", "editar"):
        raise HTTPException(403, "Sin permiso")
    async with tenant_session(user.tenant_schema) as ts:
        row = (
            await ts.execute(
                text(
                    "SELECT id, nombre_completo, cargo, dni, telefono, foto_url, activo "
                    "FROM referentes WHERE id = :id"
                ),
                {"id": ref_id},
            )
        ).first()
    if not row:
        raise HTTPException(404, "Referente no encontrado")
    return request.app.state.templates.TemplateResponse(
        "tenant/referentes/form.html",
        build_context(request, user=user, referente=row, cargos=CARGOS_VALIDOS),
    )


@router.post("/{ref_id}/editar")
async def editar_submit(
    request: Request,
    ref_id: int,
    user: CurrentUser = Depends(require_password_changed),
    nombre_completo: str = Form(...),
    cargo: str = Form(...),
    dni: str = Form(""),
    telefono: str = Form(""),
    foto_url: str = Form(""),
    activo: Optional[str] = Form(None),
):
    if not user.puede("padron", "referentes", "editar"):
        raise HTTPException(403, "Sin permiso")
    if cargo not in CARGOS_VALIDOS:
        set_flash(request, "error", "Cargo inválido.")
        return RedirectResponse(f"/app/referentes/{ref_id}/editar", status_code=303)
    async with tenant_session(user.tenant_schema) as ts:
        await ts.execute(
            text(
                "UPDATE referentes SET nombre_completo = :n, cargo = :c, dni = :d, "
                "telefono = :t, foto_url = :f, activo = :a WHERE id = :id"
            ),
            {
                "n": nombre_completo.strip(), "c": cargo,
                "d": dni.strip() or None, "t": telefono.strip() or None,
                "f": foto_url.strip() or None,
                "a": activo == "on", "id": ref_id,
            },
        )
        await ts.commit()
    set_flash(request, "success", "Referente actualizado.")
    return RedirectResponse("/app/referentes/", status_code=303)
