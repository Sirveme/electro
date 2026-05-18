"""
Configuración del cálculo de recibo (cargo fijo + adicional por morador).

GET  /app/configuracion        formulario con los valores actuales
POST /app/configuracion        guarda los valores
"""
import logging
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.context_processor import build_context
from app.database import tenant_session
from app.dependencies import CurrentUser, require_password_changed
from app.services.csrf import verify_csrf
from app.services.tarifa_service import (
    TarifaError,
    guardar_config_calculo,
    obtener_config_calculo,
)
from app.utils.flash import set_flash

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/app/configuracion")


def _parse_decimal(raw: str, etiqueta: str) -> Decimal:
    try:
        return Decimal(str(raw).strip().replace(",", "."))
    except (InvalidOperation, AttributeError, ValueError) as exc:
        raise TarifaError(f"{etiqueta} inválido: '{raw}'") from exc


@router.get("", response_class=HTMLResponse)
async def index_form(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
):
    if not user.puede("config", "municipio", "editar"):
        raise HTTPException(403, "Sin permiso")
    async with tenant_session(user.tenant_schema) as ts:
        config = await obtener_config_calculo(ts)
    return request.app.state.templates.TemplateResponse(
        "tenant/configuracion/index.html",
        build_context(request, user=user, config=config),
    )


@router.post("", dependencies=[Depends(verify_csrf)])
async def index_submit(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
    cargo_fijo_mensual: str = Form(...),
    adicional_por_morador: str = Form(...),
):
    if not user.puede("config", "municipio", "editar"):
        raise HTTPException(403, "Sin permiso")
    try:
        cargo = _parse_decimal(cargo_fijo_mensual, "Cargo fijo")
        adicional = _parse_decimal(adicional_por_morador, "Adicional por morador")
        async with tenant_session(user.tenant_schema) as ts:
            await guardar_config_calculo(ts, cargo, adicional)
            await ts.commit()
    except TarifaError as exc:
        set_flash(request, "error", str(exc))
        return RedirectResponse("/app/configuracion", status_code=303)
    set_flash(request, "success", "Configuración guardada.")
    return RedirectResponse("/app/configuracion", status_code=303)
