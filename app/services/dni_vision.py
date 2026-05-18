"""
Fallback: extraer datos de DNI peruano con GPT-4o-mini Vision.

- Usa httpx (NO el cliente oficial openai, por estabilidad entre versiones).
- API key desde env OPENAI_API_KEY.
- Devuelve dict con dni, apellido_paterno, apellido_materno, nombres, fecha_nacimiento (ISO),
  sexo (M/F), confianza (0-1) y crudo (raw del modelo).
"""
import base64
import json
import logging
import os
import re
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = (
    "Eres un extractor de datos de DNI peruanos. Te muestran una imagen del frente del DNI "
    "y debes devolver SOLO un objeto JSON (sin markdown, sin texto antes ni después) con los "
    "siguientes campos exactos: dni (string de 8 dígitos), apellido_paterno (string), "
    "apellido_materno (string), nombres (string), fecha_nacimiento (string ISO YYYY-MM-DD), "
    "sexo (string 'M' o 'F'). Si no puedes leer un campo, déjalo en null. "
    "No inventes datos. Responde estrictamente JSON."
)


class DniVisionError(Exception):
    pass


def _coerce_iso_date(value: Any) -> Optional[str]:
    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    # YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", v):
        return v
    # DD/MM/YYYY
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", v)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return None


def _coerce_sexo(value: Any) -> Optional[str]:
    if not value or not isinstance(value, str):
        return None
    v = value.strip().upper()[:1]
    if v in ("M", "F"):
        return v
    return None


def _parse_response(raw: str) -> dict:
    """Acepta tanto JSON puro como JSON envuelto en ```json ... ```."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


async def extraer_datos_dni_desde_imagen(image_bytes: bytes) -> dict:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise DniVisionError("OPENAI_API_KEY no configurada")
    if not image_bytes:
        raise DniVisionError("Imagen vacía")

    b64 = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "model": MODEL,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extrae los datos del DNI mostrado en la imagen."},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                ],
            },
        ],
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        try:
            r = await client.post(OPENAI_API_URL, json=payload, headers=headers)
            r.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.exception("OpenAI status %s: %s", exc.response.status_code, exc.response.text[:500])
            raise DniVisionError(f"OpenAI HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            logger.exception("OpenAI request error")
            raise DniVisionError(f"Error de red con OpenAI: {exc}") from exc

    body = r.json()
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise DniVisionError(f"Respuesta de OpenAI sin contenido: {body}") from exc

    try:
        parsed = _parse_response(content)
    except json.JSONDecodeError as exc:
        logger.warning("OpenAI devolvió no-JSON: %s", content[:300])
        return {
            "dni": None, "apellido_paterno": None, "apellido_materno": None,
            "nombres": None, "fecha_nacimiento": None, "sexo": None,
            "confianza": 0.0, "crudo": content,
            "error": "No se pudo parsear la respuesta del modelo",
        }

    dni_val = parsed.get("dni")
    dni_clean: Optional[str] = None
    if isinstance(dni_val, str) and re.match(r"^\d{8}$", dni_val.strip()):
        dni_clean = dni_val.strip()
    elif isinstance(dni_val, int) and 10_000_000 <= dni_val <= 99_999_999:
        dni_clean = str(dni_val)

    confianza = 1.0 if dni_clean else 0.4

    return {
        "dni": dni_clean,
        "apellido_paterno": parsed.get("apellido_paterno"),
        "apellido_materno": parsed.get("apellido_materno"),
        "nombres": parsed.get("nombres"),
        "fecha_nacimiento": _coerce_iso_date(parsed.get("fecha_nacimiento")),
        "sexo": _coerce_sexo(parsed.get("sexo")),
        "confianza": confianza,
        "crudo": content,
    }
