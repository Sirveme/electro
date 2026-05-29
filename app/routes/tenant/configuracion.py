"""
Configuración del cálculo de recibo + branding del municipio (logo y nombre).

GET  /app/configuracion        formulario con todos los valores actuales
POST /app/configuracion        guarda cargo fijo + adicional por morador
POST /app/configuracion/logo   sube logo a GCS y guarda nombre municipalidad
"""
import logging
import time
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app.context_processor import build_context
from app.database import tenant_session
from app.dependencies import CurrentUser, require_password_changed
from app.services.csrf import verify_csrf
from app.services.gcs_uploader import GCSUploaderError, get_gcs_uploader
from app.services.tarifa_service import (
    TarifaError,
    guardar_branding,
    guardar_config_calculo,
    obtener_branding,
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
    from sqlalchemy import text
    async with tenant_session(user.tenant_schema) as ts:
        config = await obtener_config_calculo(ts)
        branding = await obtener_branding(ts)
        comunidades = (
            await ts.execute(
                text(
                    "SELECT c.id, c.nombre, c.activa, "
                    "       COALESCE(c.alumbrado_publico_mensual, 0) AS alumbrado_publico_mensual, "
                    "       r.nombre_completo AS referente_nombre "
                    "FROM comunidades c "
                    "LEFT JOIN referentes r ON r.id = c.referente_principal_id "
                    "ORDER BY c.activa DESC, c.nombre"
                )
            )
        ).mappings().all()
    return request.app.state.templates.TemplateResponse(
        "tenant/configuracion/index.html",
        build_context(
            request, user=user, config=config, branding_actual=branding,
            comunidades=[dict(c) for c in comunidades],
        ),
    )


@router.post("", dependencies=[Depends(verify_csrf)])
async def index_submit(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
    adicional_por_morador: str = Form(...),
):
    # zClaude-fix-16: el cargo fijo por municipio fue reemplazado por el
    # alumbrado público por comunidad (se configura por comunidad). Aquí solo se
    # edita el adicional por morador; se preserva el valor de cargo_fijo en BD.
    if not user.puede("config", "municipio", "editar"):
        raise HTTPException(403, "Sin permiso")
    try:
        adicional = _parse_decimal(adicional_por_morador, "Adicional por morador")
        async with tenant_session(user.tenant_schema) as ts:
            config_actual = await obtener_config_calculo(ts)
            cargo = _parse_decimal(str(config_actual.get("cargo_fijo_mensual", 0)), "Cargo fijo")
            await guardar_config_calculo(ts, cargo, adicional)
            await ts.commit()
    except TarifaError as exc:
        set_flash(request, "error", str(exc))
        return RedirectResponse("/app/configuracion", status_code=303)
    set_flash(request, "success", "Configuración guardada.")
    return RedirectResponse("/app/configuracion", status_code=303)


@router.post("/logo", dependencies=[Depends(verify_csrf)])
async def actualizar_branding(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
    nombre_municipalidad: str = Form(""),
    nombre_corto: str = Form(""),
    logo: UploadFile = File(None),
):
    """Sube logo a GCS (si viene) y guarda los nombres del municipio."""
    if not user.puede("config", "municipio", "editar"):
        raise HTTPException(403, "Sin permiso")

    ubigeo = user.tenant_schema.removeprefix("muni_")
    logo_url: str | None = None

    if logo and logo.filename:
        data = await logo.read()
        if not data:
            set_flash(request, "error", "El archivo de logo está vacío.")
            return RedirectResponse("/app/configuracion", status_code=303)
        if len(data) > 2 * 1024 * 1024:
            set_flash(request, "error", "El logo no puede pesar más de 2 MB.")
            return RedirectResponse("/app/configuracion", status_code=303)
        try:
            uploader = get_gcs_uploader()
            ts_epoch = int(time.time())
            ext = (logo.filename.rsplit(".", 1)[-1] or "png").lower()
            if ext not in ("png", "jpg", "jpeg", "svg", "webp"):
                ext = "png"
            content_type = logo.content_type or "image/png"
            path = f"electro/{ubigeo}/branding/logo_{ts_epoch}.{ext}"
            logo_url = uploader.subir_imagen(data, path, content_type=content_type)
        except GCSUploaderError as exc:
            logger.warning("Subida de logo fallo: %s", exc)
            set_flash(request, "error", f"No se pudo subir el logo: {exc}")
            return RedirectResponse("/app/configuracion", status_code=303)

    async with tenant_session(user.tenant_schema) as ts:
        await guardar_branding(
            ts,
            logo_url=logo_url,  # solo se actualiza si subimos uno nuevo
            nombre_municipalidad=(nombre_municipalidad or "").strip(),
            nombre_corto=(nombre_corto or "").strip(),
        )
        branding_actual = await obtener_branding(ts)
        await ts.commit()

    # Refrescar la sesion del admin para que vea el cambio sin relogueo.
    request.session["branding"] = branding_actual

    set_flash(request, "success", "Branding del municipio actualizado.")
    return RedirectResponse("/app/configuracion", status_code=303)
