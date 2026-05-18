from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.context_processor import build_context
from app.dependencies import CurrentUser, require_password_changed

router = APIRouter(prefix="/app")


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
):
    return request.app.state.templates.TemplateResponse(
        "tenant/dashboard.html",
        build_context(request, user=user),
    )
