"""
Administración de moradores: modificar datos personales con auditoría.

Reglas de negocio:
- DNI NO es editable (es el identificador).
- Solo un morador puede ser `es_jefe_familia=TRUE` por vivienda. Si se marca
  como jefe a un morador, el resto de moradores de la misma vivienda se
  desmarcan automáticamente.
- Lo mismo aplica a `es_responsable_pago` (solo uno por vivienda).
- `acceso_portal` NO tiene restricción (varios moradores pueden tener acceso).

Toda mutación se audita en vivienda_eventos (tipo='morador_modificacion').
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class MoradorError(Exception):
    """Error de negocio al editar un morador."""


# Campos editables y su tipo Python.
CAMPOS_EDITABLES_MORADOR: dict[str, type] = {
    "nombre_completo":     str,
    "sexo":                str,
    "fecha_nacimiento":    str,   # 'YYYY-MM-DD' o None
    "telefono":            str,
    "es_jefe_familia":     bool,
    "es_responsable_pago": bool,
    "acceso_portal":       bool,
}

# Flags de unicidad por vivienda.
FLAGS_UNICOS = ("es_jefe_familia", "es_responsable_pago")

SEXO_VALIDOS = {"M", "F", "V", ""}


async def _registrar_evento(
    session: AsyncSession,
    vivienda_id: int,
    user_id: int,
    descripcion: str,
    metadata: dict,
) -> None:
    await session.execute(
        text(
            "INSERT INTO vivienda_eventos (vivienda_id, tipo, descripcion, metadata, user_id) "
            "VALUES (:v, 'morador_modificacion', :d, CAST(:m AS JSONB), :u)"
        ),
        {
            "v": vivienda_id,
            "d": descripcion,
            "m": json.dumps(metadata, ensure_ascii=False, default=str),
            "u": user_id,
        },
    )


async def modificar_morador(
    session: AsyncSession,
    morador_id: int,
    cambios: dict,
    user_id: int,
) -> list[str]:
    """
    Modifica campos editables del morador. Cada cambio real se audita.

    Si se cambia es_jefe_familia o es_responsable_pago a TRUE, se desmarca
    automáticamente cualquier otro morador de la misma vivienda con ese flag.

    Retorna la lista de campos efectivamente modificados.
    """
    if not cambios:
        raise MoradorError("No hay cambios para aplicar")

    row = (
        await session.execute(
            text(
                "SELECT m.*, v.anulada_at, v.codigo_interno "
                "FROM moradores m JOIN viviendas v ON v.id = m.vivienda_id "
                "WHERE m.id = :mid"
            ),
            {"mid": morador_id},
        )
    ).mappings().first()
    if not row:
        raise MoradorError("Morador no encontrado")
    if row["anulada_at"] is not None:
        raise MoradorError(
            "No se puede editar un morador de una vivienda anulada. "
            "Reactivar la vivienda primero."
        )
    if not row["activo"]:
        raise MoradorError("El morador está inactivo")

    vivienda_id = row["vivienda_id"]

    # Validaciones por campo.
    cambios_validos: dict = {}
    for campo, valor in cambios.items():
        if campo not in CAMPOS_EDITABLES_MORADOR:
            continue
        if campo == "sexo":
            valor_norm = (valor or "").strip().upper()[:1]
            if valor_norm not in SEXO_VALIDOS:
                raise MoradorError(f"Sexo inválido: {valor!r}")
            valor = valor_norm or None
        elif campo == "fecha_nacimiento":
            valor = (valor or "").strip() or None
        elif campo == "telefono":
            valor = (valor or "").strip() or None
        elif campo == "nombre_completo":
            valor = (valor or "").strip()
            if not valor:
                raise MoradorError("El nombre completo no puede estar vacío")
        elif campo in ("es_jefe_familia", "es_responsable_pago", "acceso_portal"):
            valor = bool(valor)

        actual = row[campo]
        if str(actual) == str(valor):
            continue
        if valor in (None, "") and (actual is None or actual == ""):
            continue
        cambios_validos[campo] = valor

    if not cambios_validos:
        return []

    # Si se activa un flag único, desmarcar al resto antes del UPDATE.
    for flag in FLAGS_UNICOS:
        if cambios_validos.get(flag) is True:
            await session.execute(
                text(
                    f"UPDATE moradores SET {flag} = FALSE "
                    f"WHERE vivienda_id = :vid AND id <> :mid AND {flag} = TRUE"
                ),
                {"vid": vivienda_id, "mid": morador_id},
            )

    set_clauses = ", ".join(f"{c} = :{c}" for c in cambios_validos.keys())
    params = {**cambios_validos, "mid": morador_id}
    await session.execute(
        text(
            f"UPDATE moradores SET {set_clauses}, updated_at = NOW() "
            f"WHERE id = :mid"
        ),
        params,
    )

    for campo, valor_nuevo in cambios_validos.items():
        await _registrar_evento(
            session,
            vivienda_id,
            user_id,
            descripcion=f"Morador {row['dni']} — modificado: {campo}",
            metadata={
                "morador_id": morador_id,
                "dni": row["dni"],
                "campo": campo,
                "valor_anterior": (str(row[campo]) if row[campo] is not None else None),
                "valor_nuevo": (str(valor_nuevo) if valor_nuevo is not None else None),
            },
        )

    await session.commit()
    logger.info(
        "Morador %d (DNI %s) modificado por user %d: %s",
        morador_id, row["dni"], user_id, list(cambios_validos.keys()),
    )
    return list(cambios_validos.keys())
