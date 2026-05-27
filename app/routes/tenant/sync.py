"""
Pantalla de cola de sincronización (/app/sync).

La página es un shell HTML; toda la data viene de IndexedDB en el cliente.
Aquí solo verificamos sesión y permisos.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.context_processor import build_context
from app.dependencies import CurrentUser, require_password_changed

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/app/sync")


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def lista_sync(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("padron", "viviendas", "ver"):
        raise HTTPException(403, "Sin permiso")
    return request.app.state.templates.TemplateResponse(
        "tenant/sync/lista.html",
        build_context(request, user=user),
    )
