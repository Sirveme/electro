"""
CRUD de tarifas / catálogo de artefactos del municipio.

Pantalla principal /app/tarifas/ lista todo unificado y permite editar inline
la tarifa de cada fila (HTMX). Toggle de habilitado por fila.

Para artefactos NO en el catálogo público, el municipio puede crearlos en
/app/tarifas/propio/nuevo.

Permisos:
- ver/listar:  config.catalogo.editar  o  config.tarifas.editar
- editar:      mismos
"""
import logging
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.context_processor import build_context
from app.database import tenant_session
from app.dependencies import CurrentUser, require_password_changed
from app.services.csrf import verify_csrf
from app.services.tarifa_service import (
    TarifaError,
    crear_propio,
    editar_propio_tarifa,
    editar_tarifa_catalogo,
    listar_unificado,
    toggle_catalogo,
    toggle_propio,
)
from app.utils.flash import set_flash

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/app/tarifas")


def _puede_editar(user: CurrentUser) -> bool:
    return (
        user.puede("config", "catalogo", "editar")
        or user.puede("config", "tarifas", "editar")
    )


def _parse_decimal(raw: str) -> Decimal:
    try:
        return Decimal(str(raw).strip().replace(",", "."))
    except (InvalidOperation, AttributeError, ValueError) as exc:
        raise TarifaError(f"Tarifa inválida: '{raw}'") from exc


@router.get("/", response_class=HTMLResponse)
async def listar(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
):
    if not _puede_editar(user):
        raise HTTPException(403, "Sin permiso")
    async with tenant_session(user.tenant_schema) as ts:
        items = await listar_unificado(ts)
    return request.app.state.templates.TemplateResponse(
        "tenant/tarifas/lista.html",
        build_context(request, user=user, items=items),
    )


@router.post("/catalogo/{codigo}/tarifa", dependencies=[Depends(verify_csrf)])
async def editar_tarifa_catalogo_route(
    request: Request,
    codigo: str,
    user: CurrentUser = Depends(require_password_changed),
    tarifa: str = Form(...),
):
    if not _puede_editar(user):
        raise HTTPException(403, "Sin permiso")
    try:
        nueva = _parse_decimal(tarifa)
        async with tenant_session(user.tenant_schema) as ts:
            await editar_tarifa_catalogo(ts, codigo, nueva)
            items = await listar_unificado(ts)
            await ts.commit()
        item = next((i for i in items if i["origen"] == "catalogo" and i["codigo"] == codigo), None)
    except TarifaError as exc:
        raise HTTPException(400, str(exc))
    if not item:
        raise HTTPException(404, "Artefacto no encontrado")
    return request.app.state.templates.TemplateResponse(
        "tenant/tarifas/_frag_tarifa_row.html",
        build_context(request, user=user, item=item),
    )


@router.post("/catalogo/{codigo}/toggle", dependencies=[Depends(verify_csrf)])
async def toggle_catalogo_route(
    request: Request,
    codigo: str,
    user: CurrentUser = Depends(require_password_changed),
):
    if not _puede_editar(user):
        raise HTTPException(403, "Sin permiso")
    try:
        async with tenant_session(user.tenant_schema) as ts:
            await toggle_catalogo(ts, codigo)
            items = await listar_unificado(ts)
            await ts.commit()
        item = next((i for i in items if i["origen"] == "catalogo" and i["codigo"] == codigo), None)
    except TarifaError as exc:
        raise HTTPException(400, str(exc))
    if not item:
        raise HTTPException(404, "Artefacto no encontrado")
    return request.app.state.templates.TemplateResponse(
        "tenant/tarifas/_frag_tarifa_row.html",
        build_context(request, user=user, item=item),
    )


@router.post("/propio/{codigo}/tarifa", dependencies=[Depends(verify_csrf)])
async def editar_tarifa_propio_route(
    request: Request,
    codigo: str,
    user: CurrentUser = Depends(require_password_changed),
    tarifa: str = Form(...),
):
    if not _puede_editar(user):
        raise HTTPException(403, "Sin permiso")
    try:
        nueva = _parse_decimal(tarifa)
        async with tenant_session(user.tenant_schema) as ts:
            await editar_propio_tarifa(ts, codigo, nueva)
            items = await listar_unificado(ts)
            await ts.commit()
        item = next((i for i in items if i["origen"] == "propio" and i["codigo"] == codigo), None)
    except TarifaError as exc:
        raise HTTPException(400, str(exc))
    if not item:
        raise HTTPException(404, "Artefacto no encontrado")
    return request.app.state.templates.TemplateResponse(
        "tenant/tarifas/_frag_tarifa_row.html",
        build_context(request, user=user, item=item),
    )


@router.post("/propio/{codigo}/toggle", dependencies=[Depends(verify_csrf)])
async def toggle_propio_route(
    request: Request,
    codigo: str,
    user: CurrentUser = Depends(require_password_changed),
):
    if not _puede_editar(user):
        raise HTTPException(403, "Sin permiso")
    try:
        async with tenant_session(user.tenant_schema) as ts:
            await toggle_propio(ts, codigo)
            items = await listar_unificado(ts)
            await ts.commit()
        item = next((i for i in items if i["origen"] == "propio" and i["codigo"] == codigo), None)
    except TarifaError as exc:
        raise HTTPException(400, str(exc))
    if not item:
        raise HTTPException(404, "Artefacto no encontrado")
    return request.app.state.templates.TemplateResponse(
        "tenant/tarifas/_frag_tarifa_row.html",
        build_context(request, user=user, item=item),
    )


@router.get("/propio/nuevo", response_class=HTMLResponse)
async def propio_nuevo_form(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
):
    if not _puede_editar(user):
        raise HTTPException(403, "Sin permiso")
    return request.app.state.templates.TemplateResponse(
        "tenant/tarifas/form_propio.html",
        build_context(request, user=user, form={}),
    )


@router.post("/propio/nuevo", dependencies=[Depends(verify_csrf)])
async def propio_nuevo_submit(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
    codigo: str = Form(...),
    nombre: str = Form(...),
    categoria: str = Form(...),
    tarifa: str = Form(...),
    habilitado: Optional[str] = Form(None),
):
    if not _puede_editar(user):
        raise HTTPException(403, "Sin permiso")
    try:
        tarifa_dec = _parse_decimal(tarifa)
        async with tenant_session(user.tenant_schema) as ts:
            await crear_propio(
                ts,
                codigo=codigo,
                nombre=nombre,
                categoria=categoria,
                tarifa=tarifa_dec,
                habilitado=(habilitado == "on"),
            )
            await ts.commit()
    except TarifaError as exc:
        set_flash(request, "error", str(exc))
        return request.app.state.templates.TemplateResponse(
            "tenant/tarifas/form_propio.html",
            build_context(
                request, user=user,
                form={
                    "codigo": codigo, "nombre": nombre, "categoria": categoria,
                    "tarifa": tarifa, "habilitado": habilitado,
                },
            ),
            status_code=400,
        )
    set_flash(request, "success", f"Artefacto propio '{codigo}' creado.")
    return RedirectResponse("/app/tarifas/", status_code=303)
