"""
Endpoint API para extracción de datos de DNI via Vision (fallback).

POST /app/api/dni/extract  (multipart/form-data con campo 'imagen')
Retorna JSON con los datos extraídos.
"""
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.dependencies import CurrentUser, require_password_changed
from app.services.csrf import verify_csrf
from app.services.dni_vision import DniVisionError, extraer_datos_dni_desde_imagen

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/app/api/dni")

MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB


@router.post("/extract", dependencies=[Depends(verify_csrf)])
async def extract(
    user: CurrentUser = Depends(require_password_changed),
    imagen: UploadFile = File(...),
):
    if not user.puede("padron", "viviendas", "crear"):
        raise HTTPException(403, "Sin permiso")

    contenido = await imagen.read()
    if len(contenido) == 0:
        raise HTTPException(400, "Imagen vacía")
    if len(contenido) > MAX_IMAGE_BYTES:
        raise HTTPException(413, f"Imagen demasiado grande (>{MAX_IMAGE_BYTES} bytes)")

    try:
        datos = await extraer_datos_dni_desde_imagen(contenido)
    except DniVisionError as exc:
        logger.warning("DNI Vision falló: %s", exc)
        raise HTTPException(502, str(exc))
    except Exception as exc:
        logger.exception("Error inesperado en DNI Vision")
        raise HTTPException(500, "Error procesando imagen")

    return {
        "dni": datos.get("dni"),
        "apellido_paterno": datos.get("apellido_paterno"),
        "apellido_materno": datos.get("apellido_materno"),
        "nombres": datos.get("nombres"),
        "fecha_nacimiento": datos.get("fecha_nacimiento"),
        "sexo": datos.get("sexo"),
        "confianza": datos.get("confianza", 0.0),
    }
