"""
Administración de viviendas: anular (soft delete con motivo),
reactivar (revertir anulación) y modificar campos editables.

Toda mutación queda registrada en vivienda_eventos para auditoría.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ViviendaError(Exception):
    """Error de negocio al editar/anular/reactivar una vivienda."""


# Motivos válidos de anulación (deben coincidir con el CHECK en BD).
MOTIVOS_VALIDOS: dict[str, str] = {
    "error_empadronamiento": "Error de empadronamiento",
    "duplicado":             "Vivienda duplicada",
    "no_pertenece":          "No pertenece al distrito",
    "demolida":              "Vivienda demolida o ya no existe",
    "otro":                  "Otro motivo",
}

# Campos editables de una vivienda y su tipo Python.
CAMPOS_EDITABLES_VIVIENDA: dict[str, type] = {
    "comunidad_id":        int,
    "referente_id":        int,
    "referencia_fisica":   str,
    "fuente_validacion":   str,
    "estado_servicio":     str,
    "modo_calculo":        str,
    "observaciones":       str,
}

ESTADO_SERVICIO_VALIDOS = ["activo", "suspendido", "cortado"]
MODO_CALCULO_VALIDOS = ["estimado", "lectura_medidor", "mixto"]


async def _registrar_evento(
    session: AsyncSession,
    vivienda_id: int,
    tipo: str,
    user_id: int,
    descripcion: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    """Inserta un registro en vivienda_eventos. Reusa el patrón existente."""
    await session.execute(
        text(
            "INSERT INTO vivienda_eventos (vivienda_id, tipo, descripcion, metadata, user_id) "
            "VALUES (:v, :t, :d, CAST(:m AS JSONB), :u)"
        ),
        {
            "v": vivienda_id,
            "t": tipo,
            "d": descripcion,
            "m": json.dumps(metadata, ensure_ascii=False, default=str) if metadata is not None else None,
            "u": user_id,
        },
    )


async def tiene_pagos_activos(session: AsyncSession, vivienda_id: int) -> bool:
    """True si la vivienda tiene al menos un pago NO anulado."""
    row = (
        await session.execute(
            text(
                """
                SELECT EXISTS(
                    SELECT 1 FROM pagos p
                    JOIN cuotas c ON c.id = p.cuota_id
                    WHERE c.vivienda_id = :vid AND p.anulado = FALSE
                ) AS existe
                """
            ),
            {"vid": vivienda_id},
        )
    ).scalar()
    return bool(row)


async def anular_vivienda(
    session: AsyncSession,
    vivienda_id: int,
    motivo: str,
    observacion: Optional[str],
    user_id: int,
) -> None:
    """
    Anula una vivienda (soft delete).

    Reglas:
    - motivo debe estar en MOTIVOS_VALIDOS
    - si motivo == 'otro', observacion es obligatoria (>=10 chars)
    - no se puede anular si tiene pagos NO anulados
    - moradores asociados se marcan inactivos
    - inventario vigente se cierra con vigente_hasta = NOW()
    - se registra evento tipo='anulacion'

    El caller NO debe llamar commit: este método hace commit por sí mismo.
    """
    if motivo not in MOTIVOS_VALIDOS:
        raise ViviendaError(f"Motivo inválido: {motivo}")
    obs = (observacion or "").strip()
    if motivo == "otro" and len(obs) < 10:
        raise ViviendaError(
            "Si el motivo es 'Otro', la observación debe tener al menos 10 caracteres"
        )

    row = (
        await session.execute(
            text("SELECT codigo_interno, anulada_at FROM viviendas WHERE id = :vid"),
            {"vid": vivienda_id},
        )
    ).mappings().first()
    if not row:
        raise ViviendaError("Vivienda no encontrada")
    if row["anulada_at"] is not None:
        raise ViviendaError("La vivienda ya está anulada")

    if await tiene_pagos_activos(session, vivienda_id):
        raise ViviendaError(
            "No se puede anular: la vivienda tiene pagos registrados. "
            "Primero deben anularse los pagos correspondientes."
        )

    await session.execute(
        text(
            """
            UPDATE viviendas
               SET anulada_at = NOW(),
                   anulada_por_user_id = :uid,
                   motivo_anulacion = :motivo,
                   observacion_anulacion = :obs,
                   estado_servicio = 'anulado'
             WHERE id = :vid
            """
        ),
        {"uid": user_id, "motivo": motivo, "obs": obs or None, "vid": vivienda_id},
    )

    await session.execute(
        text(
            "UPDATE moradores SET activo = FALSE "
            "WHERE vivienda_id = :vid AND activo = TRUE"
        ),
        {"vid": vivienda_id},
    )

    await session.execute(
        text(
            "UPDATE vivienda_inventario SET vigente_hasta = NOW() "
            "WHERE vivienda_id = :vid AND vigente_hasta IS NULL"
        ),
        {"vid": vivienda_id},
    )

    await _registrar_evento(
        session,
        vivienda_id,
        "anulacion",
        user_id,
        descripcion=f"Vivienda anulada — {MOTIVOS_VALIDOS[motivo]}",
        metadata={"motivo": motivo, "observacion": obs or None},
    )

    await session.commit()
    logger.info("Vivienda %s anulada por user %d", row["codigo_interno"], user_id)


async def reactivar_vivienda(
    session: AsyncSession,
    vivienda_id: int,
    motivo_reactivacion: str,
    user_id: int,
) -> None:
    """
    Reactiva una vivienda anulada.

    Reglas:
    - vivienda debe estar anulada
    - motivo_reactivacion obligatorio (>=10 chars)
    - moradores e inventario NO se reactivan automáticamente
      (deben hacerse manualmente si corresponde)
    """
    motivo = (motivo_reactivacion or "").strip()
    if len(motivo) < 10:
        raise ViviendaError(
            "El motivo de reactivación debe tener al menos 10 caracteres"
        )

    row = (
        await session.execute(
            text(
                "SELECT codigo_interno, anulada_at, motivo_anulacion "
                "FROM viviendas WHERE id = :vid"
            ),
            {"vid": vivienda_id},
        )
    ).mappings().first()
    if not row:
        raise ViviendaError("Vivienda no encontrada")
    if row["anulada_at"] is None:
        raise ViviendaError("La vivienda no está anulada")

    await session.execute(
        text(
            """
            UPDATE viviendas
               SET anulada_at = NULL,
                   anulada_por_user_id = NULL,
                   motivo_anulacion = NULL,
                   observacion_anulacion = NULL,
                   estado_servicio = 'activo'
             WHERE id = :vid
            """
        ),
        {"vid": vivienda_id},
    )

    await _registrar_evento(
        session,
        vivienda_id,
        "reactivacion",
        user_id,
        descripcion="Vivienda reactivada",
        metadata={
            "motivo_anulacion_previo": row["motivo_anulacion"],
            "motivo_reactivacion": motivo,
        },
    )

    await session.commit()
    logger.info("Vivienda %s reactivada por user %d", row["codigo_interno"], user_id)


async def modificar_vivienda(
    session: AsyncSession,
    vivienda_id: int,
    cambios: dict,
    user_id: int,
) -> list[str]:
    """
    Modifica campos editables. Cada cambio real (valor distinto al actual)
    se audita por separado en vivienda_eventos.

    Retorna la lista de campos efectivamente modificados.
    """
    if not cambios:
        raise ViviendaError("No hay cambios para aplicar")

    row = (
        await session.execute(
            text("SELECT * FROM viviendas WHERE id = :vid"),
            {"vid": vivienda_id},
        )
    ).mappings().first()
    if not row:
        raise ViviendaError("Vivienda no encontrada")
    if row["anulada_at"] is not None:
        raise ViviendaError(
            "No se puede editar una vivienda anulada. Reactivarla primero."
        )

    cambios_validos: dict = {}
    for campo, valor in cambios.items():
        if campo not in CAMPOS_EDITABLES_VIVIENDA:
            continue
        if campo == "estado_servicio" and valor not in ESTADO_SERVICIO_VALIDOS:
            raise ViviendaError(f"Estado de servicio inválido: {valor}")
        if campo == "modo_calculo" and valor not in MODO_CALCULO_VALIDOS:
            raise ViviendaError(f"Modo de cálculo inválido: {valor}")
        actual = row[campo]
        # Normalizar: '' viene del form, en BD puede ser NULL
        if valor == "" and actual is None:
            continue
        if str(actual) == str(valor):
            continue
        cambios_validos[campo] = valor if valor != "" else None

    if not cambios_validos:
        return []

    set_clauses = ", ".join(f"{c} = :{c}" for c in cambios_validos.keys())
    params = {**cambios_validos, "vid": vivienda_id}
    await session.execute(
        text(f"UPDATE viviendas SET {set_clauses} WHERE id = :vid"),
        params,
    )

    for campo, valor_nuevo in cambios_validos.items():
        await _registrar_evento(
            session,
            vivienda_id,
            "modificacion",
            user_id,
            descripcion=f"Modificado: {campo}",
            metadata={
                "campo": campo,
                "valor_anterior": (str(row[campo]) if row[campo] is not None else None),
                "valor_nuevo": (str(valor_nuevo) if valor_nuevo is not None else None),
            },
        )

    await session.commit()
    logger.info(
        "Vivienda %d modificada por user %d: %s",
        vivienda_id, user_id, list(cambios_validos.keys()),
    )
    return list(cambios_validos.keys())
