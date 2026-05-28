"""
Endpoint de version-check para clientes PWA.

El cliente JS (static/js/version_check.js) compara la version del meta tag
`app-version` con `version_servidor` y muestra banner sugerido o critico
segun corresponda.

El changelog se lee al vuelo de CHANGELOG.md en la raiz del repo.
"""
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.dependencies import CurrentUser, require_password_changed
from app.version import APP_VERSION, MIN_COMPATIBLE_VERSION, RELEASE_DATE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/app/api")

CHANGELOG_PATH = Path(__file__).resolve().parents[3] / "CHANGELOG.md"


def _leer_changelog(n: int = 3) -> list[dict]:
    """Lee las ultimas n entradas del CHANGELOG.md.

    Estructura esperada:
        ## [X.Y.Z] - YYYY-MM-DD
        notas...

        ## [...]
    """
    if not CHANGELOG_PATH.exists():
        return []
    try:
        content = CHANGELOG_PATH.read_text(encoding="utf-8")
    except OSError:
        return []

    versiones: list[dict] = []
    current: dict | None = None
    for line in content.splitlines():
        if line.startswith("## ["):
            if current:
                versiones.append(current)
                if len(versiones) >= n:
                    return versiones
            try:
                ver = line.split("[", 1)[1].split("]", 1)[0]
                fecha = line.split("- ", 1)[1].strip() if " - " in line else ""
            except IndexError:
                continue
            current = {"version": ver, "fecha": fecha, "notas": []}
        elif current is not None and line.strip() and not line.startswith("# "):
            current["notas"].append(line.rstrip())
    if current and len(versiones) < n:
        versiones.append(current)
    return versiones[:n]


@router.get("/version-check")
async def version_check(
    request: Request,
    user: CurrentUser = Depends(require_password_changed),
):
    return JSONResponse(
        {
            "version_servidor": APP_VERSION,
            "version_minima_compatible": MIN_COMPATIBLE_VERSION,
            "fecha_release": RELEASE_DATE,
            "changelog": _leer_changelog(3),
        }
    )
