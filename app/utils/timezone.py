"""
Helpers de zona horaria America/Lima.

La BD y el contenedor de Railway (vía variable TZ=America/Lima) operan en
hora Lima, por lo que `datetime.now()` y `NOW()` ya devuelven Lima local.
Estos helpers se usan cuando se necesita un datetime AWARE (con tzinfo)
explícito — útil al serializar a JSON o al comparar contra valores que
puedan llegar en UTC desde APIs externas.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

LIMA_TZ = ZoneInfo("America/Lima")
UTC_TZ = ZoneInfo("UTC")


def now_lima() -> datetime:
    """datetime aware en hora Lima. Úsalo en lugar de datetime.now()."""
    return datetime.now(LIMA_TZ)


def to_lima(dt: datetime) -> datetime:
    """Convierte un datetime a hora Lima. Si es naive, se asume UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)
    return dt.astimezone(LIMA_TZ)


def format_lima(dt: datetime | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Formatea un datetime en hora Lima. Devuelve '—' si dt es None."""
    if dt is None:
        return "—"
    return to_lima(dt).strftime(fmt)
