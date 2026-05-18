from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.context_processor import build_context
from app.database import get_session
from app.dependencies import CurrentUser, require_superadmin

router = APIRouter(prefix="/sa")


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: CurrentUser = Depends(require_superadmin),
    db: AsyncSession = Depends(get_session),
):
    total_activos = (
        await db.execute(text("SELECT COUNT(*) FROM public.municipios WHERE activo = TRUE"))
    ).scalar_one()
    return request.app.state.templates.TemplateResponse(
        "superadmin/dashboard.html",
        build_context(request, user=user, total_municipios_activos=total_activos),
    )
