import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.context_processor import build_context
from app.database import get_session
from app.dependencies import CurrentUser, require_superadmin
from app.services.tenant_provisioning import ProvisioningError, crear_municipio
from app.utils.flash import set_flash
from app.utils.ubigeo import UbigeoError, normalizar_ubigeo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sa/municipios")


@router.get("/", response_class=HTMLResponse)
async def listar(
    request: Request,
    user: CurrentUser = Depends(require_superadmin),
    db: AsyncSession = Depends(get_session),
):
    rows = (
        await db.execute(
            text(
                "SELECT id, ubigeo, nombre, departamento, provincia, distrito, schema_name, activo, created_at "
                "FROM public.municipios ORDER BY created_at DESC"
            )
        )
    ).all()
    return request.app.state.templates.TemplateResponse(
        "superadmin/municipios_list.html",
        build_context(request, user=user, municipios=rows),
    )


@router.get("/nuevo", response_class=HTMLResponse)
async def nuevo_form(
    request: Request,
    user: CurrentUser = Depends(require_superadmin),
):
    return request.app.state.templates.TemplateResponse(
        "superadmin/municipios_form.html",
        build_context(request, user=user, form={}, error=None),
    )


@router.post("/nuevo")
async def nuevo_submit(
    request: Request,
    user: CurrentUser = Depends(require_superadmin),
    ubigeo: str = Form(...),
    nombre: str = Form(...),
    departamento: str = Form(""),
    provincia: str = Form(""),
    distrito: str = Form(""),
    admin_dni: str = Form(...),
    admin_nombre: str = Form(...),
    admin_telefono: str = Form(""),
    admin_email: str = Form(""),
    admin_password: str = Form(...),
    plan: str = Form("demo"),
    precio_mensual: str = Form(""),
):
    form_data = {
        "ubigeo": ubigeo, "nombre": nombre, "departamento": departamento,
        "provincia": provincia, "distrito": distrito,
        "admin_dni": admin_dni, "admin_nombre": admin_nombre,
        "admin_telefono": admin_telefono, "admin_email": admin_email,
        "plan": plan, "precio_mensual": precio_mensual,
    }

    def _render_error(msg: str, status: int = 400):
        return request.app.state.templates.TemplateResponse(
            "superadmin/municipios_form.html",
            build_context(request, user=user, form=form_data, error=msg),
            status_code=status,
        )

    try:
        ubigeo_n = normalizar_ubigeo(ubigeo)
    except UbigeoError as exc:
        return _render_error(str(exc))

    precio_val = None
    if precio_mensual.strip():
        try:
            precio_val = float(precio_mensual)
        except ValueError:
            return _render_error("Precio mensual inválido.")

    try:
        result = crear_municipio(
            db_url_sync=settings.DATABASE_URL_SYNC,
            ubigeo=ubigeo_n,
            nombre=nombre.strip(),
            departamento=departamento.strip() or None,
            provincia=provincia.strip() or None,
            distrito=distrito.strip() or None,
            admin_dni=admin_dni.strip(),
            admin_nombre=admin_nombre.strip(),
            admin_password=admin_password,
            admin_email=admin_email.strip() or None,
            admin_telefono=admin_telefono.strip() or None,
            responsable_telefono=admin_telefono.strip() or None,
            creado_por_superadmin_id=user.user_id,
            plan=plan,
            precio_mensual=precio_val,
        )
    except ProvisioningError as exc:
        logger.warning("Provisioning falló: %s", exc)
        return _render_error(f"No se pudo crear el municipio: {exc}", status=500)
    except Exception as exc:
        logger.exception("Error inesperado provisionando municipio")
        return _render_error(f"Error inesperado: {exc}", status=500)

    set_flash(request, "success", f"Municipio '{nombre}' creado. Schema: {result['schema_name']}.")
    return RedirectResponse("/sa/municipios/", status_code=303)
