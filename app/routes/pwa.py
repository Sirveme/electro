"""
Rutas para servir manifest.json y sw.js desde la raiz del dominio.
El navegador exige que el SW este en raiz para tener scope completo.
"""
import logging
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

router = APIRouter()

STATIC_DIR = Path(__file__).parent.parent.parent / "static"


@router.get("/manifest.json")
async def manifest():
    """Sirve el manifest desde raiz para que el browser lo encuentre."""
    return FileResponse(
        STATIC_DIR / "manifest.json",
        media_type="application/manifest+json",
    )


@router.get("/sw.js")
async def service_worker():
    """Sirve el Service Worker desde raiz para que tenga scope /."""
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )
