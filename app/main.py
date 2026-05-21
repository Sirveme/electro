import logging

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.dependencies import RedirectException
from app.jinja_filters import register_filters
from app.middleware.csrf_cookie import CSRFCookieMiddleware
from app.routes import auth as auth_routes
from app.routes.superadmin import dashboard as sa_dashboard
from app.routes.superadmin import municipios as sa_municipios
from app.routes.tenant import dashboard as tenant_dashboard
from app.routes.tenant import cuenta as tenant_cuenta
from app.routes.tenant import comunidades as tenant_comunidades
from app.routes.tenant import referentes as tenant_referentes
from app.routes.tenant import padron as tenant_padron
from app.routes.tenant import api_dni as tenant_api_dni
from app.routes.tenant import tarifas as tenant_tarifas
from app.routes.tenant import configuracion as tenant_configuracion

logging.basicConfig(
    level=logging.INFO if settings.ENVIRONMENT == "production" else logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="electro.perusistemas.pro",
    version="0.2.0",
    docs_url=None if settings.ENVIRONMENT == "production" else "/docs",
    redoc_url=None,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    max_age=settings.SESSION_MAX_AGE_SECONDS,
    same_site="lax",
    https_only=(settings.ENVIRONMENT == "production"),
)
app.add_middleware(CSRFCookieMiddleware)


@app.exception_handler(RedirectException)
async def redirect_exception_handler(request: Request, exc: RedirectException):
    return RedirectResponse(url=exc.location, status_code=303)


app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")
register_filters(templates.env)
app.state.templates = templates


@app.get("/")
async def root(request: Request):
    kind = request.session.get("kind")
    if kind == "superadmin":
        return RedirectResponse("/sa/", status_code=303)
    if kind == "tenant":
        return RedirectResponse("/app/", status_code=303)
    return RedirectResponse("/login", status_code=303)


@app.get("/healthz")
async def healthz():
    return {"ok": True, "env": settings.ENVIRONMENT}


app.include_router(auth_routes.router)
app.include_router(sa_dashboard.router)
app.include_router(sa_municipios.router)
app.include_router(tenant_dashboard.router)
app.include_router(tenant_cuenta.router)
app.include_router(tenant_comunidades.router)
app.include_router(tenant_referentes.router)
app.include_router(tenant_padron.router)
app.include_router(tenant_api_dni.router)
app.include_router(tenant_tarifas.router)
app.include_router(tenant_configuracion.router)
