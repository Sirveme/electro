"""CRUD de comunidades del municipio."""
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
router = APIRouter(prefix="/app/comunidades")


@router.get("/", response_class=HTMLResponse)
async def listar(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("padron", "comunidades", "ver"):
        raise HTTPException(403, "Sin permiso")
    async with tenant_session(user.tenant_schema) as ts:
        rows = (
            await ts.execute(
                text(
                    "SELECT id, nombre, activa, created_at "
                    "FROM comunidades ORDER BY activa DESC, nombre"
                )
            )
        ).all()
    return request.app.state.templates.TemplateResponse(
        "tenant/comunidades/lista.html",
        build_context(request, user=user, comunidades=rows),
    )


async def _listar_referentes(ts):
    return (
        await ts.execute(
            text(
                "SELECT id, nombre_completo, cargo FROM referentes "
                "WHERE activo = TRUE ORDER BY nombre_completo"
            )
        )
    ).all()


def _parse_alumbrado(raw: str) -> str:
    """Normaliza el monto de alumbrado a string decimal válido (>= 0)."""
    from decimal import Decimal, InvalidOperation
    try:
        val = Decimal(str(raw or "0").strip().replace(",", "."))
    except (InvalidOperation, AttributeError, ValueError):
        val = Decimal("0")
    if val < 0:
        val = Decimal("0")
    return str(val)


@router.get("/nuevo", response_class=HTMLResponse)
async def nueva_form(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("padron", "comunidades", "editar"):
        raise HTTPException(403, "Sin permiso")
    async with tenant_session(user.tenant_schema) as ts:
        referentes = await _listar_referentes(ts)
    return request.app.state.templates.TemplateResponse(
        "tenant/comunidades/form.html",
        build_context(request, user=user, comunidad=None, referentes=referentes, error=None),
    )


@router.post("/nuevo")
async def nueva_submit(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
    nombre: str = Form(...),
    alumbrado_publico_mensual: str = Form("0"),
    referente_principal_id: str = Form(""),
):
    if not user.puede("padron", "comunidades", "editar"):
        raise HTTPException(403, "Sin permiso")
    nombre_clean = nombre.strip()
    if not nombre_clean:
        set_flash(request, "error", "El nombre es obligatorio.")
        return RedirectResponse("/app/comunidades/nuevo", status_code=303)
    ref_id = int(referente_principal_id) if referente_principal_id.strip().isdigit() else None
    alumbrado = _parse_alumbrado(alumbrado_publico_mensual)
    async with tenant_session(user.tenant_schema) as ts:
        try:
            await ts.execute(
                text(
                    "INSERT INTO comunidades (nombre, activa, alumbrado_publico_mensual, referente_principal_id) "
                    "VALUES (:n, TRUE, :al, :ref)"
                ),
                {"n": nombre_clean, "al": alumbrado, "ref": ref_id},
            )
            await ts.commit()
        except Exception:
            logger.exception("Error creando comunidad")
            await ts.rollback()
            set_flash(request, "error", "No se pudo crear la comunidad.")
            return RedirectResponse("/app/comunidades/nuevo", status_code=303)
    set_flash(request, "success", f"Comunidad '{nombre_clean}' creada.")
    return RedirectResponse("/app/comunidades/", status_code=303)


@router.get("/{comunidad_id}/editar", response_class=HTMLResponse)
async def editar_form(
    request: Request,
    comunidad_id: int,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("padron", "comunidades", "editar"):
        raise HTTPException(403, "Sin permiso")
    async with tenant_session(user.tenant_schema) as ts:
        row = (
            await ts.execute(
                text(
                    "SELECT id, nombre, activa, "
                    "       COALESCE(alumbrado_publico_mensual, 0) AS alumbrado_publico_mensual, "
                    "       referente_principal_id "
                    "FROM comunidades WHERE id = :id"
                ),
                {"id": comunidad_id},
            )
        ).mappings().first()
        if not row:
            raise HTTPException(404, "Comunidad no encontrada")
        referentes = await _listar_referentes(ts)
    return request.app.state.templates.TemplateResponse(
        "tenant/comunidades/form.html",
        build_context(request, user=user, comunidad=dict(row), referentes=referentes, error=None),
    )


@router.post("/{comunidad_id}/editar")
async def editar_submit(
    request: Request,
    comunidad_id: int,
    user: CurrentUser = Depends(require_password_changed),
    nombre: str = Form(...),
    activa: Optional[str] = Form(None),
    alumbrado_publico_mensual: str = Form("0"),
    referente_principal_id: str = Form(""),
):
    if not user.puede("padron", "comunidades", "editar"):
        raise HTTPException(403, "Sin permiso")
    activa_bool = activa == "on"
    ref_id = int(referente_principal_id) if referente_principal_id.strip().isdigit() else None
    alumbrado = _parse_alumbrado(alumbrado_publico_mensual)
    async with tenant_session(user.tenant_schema) as ts:
        await ts.execute(
            text(
                "UPDATE comunidades SET nombre = :n, activa = :a, "
                "alumbrado_publico_mensual = :al, referente_principal_id = :ref "
                "WHERE id = :id"
            ),
            {"n": nombre.strip(), "a": activa_bool, "al": alumbrado, "ref": ref_id, "id": comunidad_id},
        )
        await ts.commit()
    set_flash(request, "success", "Comunidad actualizada.")
    return RedirectResponse("/app/comunidades/", status_code=303)
