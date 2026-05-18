"""
Lógica de inventario con effective dating.

Regla central:
- vigente_hasta IS NULL  => vigente HOY.
- "Dar de baja" = setear vigente_hasta = (HOY - 1 día). No se borra el registro.
- "Cambiar cantidad" = dar de baja el actual y crear uno nuevo desde HOY.
- Toda mutación escribe también en vivienda_eventos.
"""
import logging
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class InventarioError(Exception):
    pass


async def _resolver_nombre_artefacto(
    session: AsyncSession,
    schema_name: str,
    origen: str,
    codigo: str,
) -> Optional[str]:
    if origen == "catalogo":
        row = (
            await session.execute(
                text("SELECT nombre FROM public.artefacto_catalogo WHERE codigo = :c"),
                {"c": codigo},
            )
        ).first()
        return row.nombre if row else None
    if origen == "propio":
        row = (
            await session.execute(
                text(f'SELECT nombre FROM "{schema_name}".artefacto_propio WHERE codigo = :c'),
                {"c": codigo},
            )
        ).first()
        return row.nombre if row else None
    raise InventarioError(f"artefacto_origen inválido: {origen}")


async def inventario_actual_de_vivienda(
    session: AsyncSession, vivienda_id: int
) -> list[dict]:
    rows = (
        await session.execute(
            text(
                "SELECT id, artefacto_origen, artefacto_codigo, artefacto_nombre_snapshot, "
                "cantidad, vigente_desde, motivo_alta, registrado_por_user_id, created_at "
                "FROM vivienda_inventario "
                "WHERE vivienda_id = :v AND vigente_hasta IS NULL "
                "ORDER BY artefacto_nombre_snapshot"
            ),
            {"v": vivienda_id},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def inventario_a_fecha(
    session: AsyncSession, vivienda_id: int, fecha: date
) -> list[dict]:
    """Inventario que estaba vigente en la `fecha` (inclusive)."""
    rows = (
        await session.execute(
            text(
                "SELECT id, artefacto_origen, artefacto_codigo, artefacto_nombre_snapshot, cantidad "
                "FROM vivienda_inventario "
                "WHERE vivienda_id = :v AND vigente_desde <= :f "
                "  AND (vigente_hasta IS NULL OR vigente_hasta >= :f)"
            ),
            {"v": vivienda_id, "f": fecha},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def _registrar_evento(
    session: AsyncSession,
    vivienda_id: int,
    tipo: str,
    user_id: int,
    descripcion: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    import json as _json
    await session.execute(
        text(
            "INSERT INTO vivienda_eventos (vivienda_id, tipo, descripcion, metadata, user_id) "
            "VALUES (:v, :t, :d, CAST(:m AS JSONB), :u)"
        ),
        {
            "v": vivienda_id, "t": tipo, "d": descripcion,
            "m": _json.dumps(metadata) if metadata is not None else None,
            "u": user_id,
        },
    )


async def agregar_artefacto(
    session: AsyncSession,
    schema_name: str,
    vivienda_id: int,
    artefacto_origen: str,
    artefacto_codigo: str,
    cantidad: int,
    user_id: int,
    motivo: str = "empadronamiento_inicial",
    fecha_alta: Optional[date] = None,
) -> int:
    if cantidad <= 0:
        raise InventarioError("Cantidad debe ser > 0")
    if artefacto_origen not in ("catalogo", "propio"):
        raise InventarioError(f"artefacto_origen inválido: {artefacto_origen}")

    nombre = await _resolver_nombre_artefacto(session, schema_name, artefacto_origen, artefacto_codigo)
    if not nombre:
        raise InventarioError(f"Artefacto no encontrado: {artefacto_origen}/{artefacto_codigo}")

    desde = fecha_alta or date.today()
    row = (
        await session.execute(
            text(
                "INSERT INTO vivienda_inventario "
                "(vivienda_id, artefacto_origen, artefacto_codigo, artefacto_nombre_snapshot, "
                " cantidad, vigente_desde, motivo_alta, registrado_por_user_id) "
                "VALUES (:v, :o, :c, :n, :q, :d, :m, :u) RETURNING id"
            ),
            {
                "v": vivienda_id, "o": artefacto_origen, "c": artefacto_codigo,
                "n": nombre, "q": cantidad, "d": desde, "m": motivo, "u": user_id,
            },
        )
    ).first()
    new_id = row.id
    await _registrar_evento(
        session, vivienda_id, "alta_artefacto", user_id,
        descripcion=f"+{cantidad} {nombre}",
        metadata={"inventario_id": new_id, "codigo": artefacto_codigo, "cantidad": cantidad, "motivo": motivo},
    )
    return new_id


async def dar_de_baja_artefacto(
    session: AsyncSession,
    inventario_id: int,
    user_id: int,
    motivo: str,
) -> None:
    row = (
        await session.execute(
            text(
                "SELECT id, vivienda_id, artefacto_nombre_snapshot, cantidad, vigente_hasta "
                "FROM vivienda_inventario WHERE id = :id"
            ),
            {"id": inventario_id},
        )
    ).first()
    if not row:
        raise InventarioError(f"Inventario id {inventario_id} no existe")
    if row.vigente_hasta is not None:
        raise InventarioError("Este registro ya está dado de baja")

    hasta = date.today() - timedelta(days=1)
    await session.execute(
        text(
            "UPDATE vivienda_inventario "
            "SET vigente_hasta = :h, motivo_baja = :m, dado_de_baja_por_user_id = :u "
            "WHERE id = :id"
        ),
        {"h": hasta, "m": motivo, "u": user_id, "id": inventario_id},
    )
    await _registrar_evento(
        session, row.vivienda_id, "baja_artefacto", user_id,
        descripcion=f"Baja: {row.cantidad} {row.artefacto_nombre_snapshot}",
        metadata={"inventario_id": inventario_id, "motivo": motivo},
    )


async def cambiar_cantidad(
    session: AsyncSession,
    schema_name: str,
    inventario_id: int,
    nueva_cantidad: int,
    user_id: int,
    motivo: str = "correccion",
) -> int:
    if nueva_cantidad <= 0:
        raise InventarioError("La nueva cantidad debe ser > 0. Para bajar todo, usa dar_de_baja_artefacto.")
    row = (
        await session.execute(
            text(
                "SELECT vivienda_id, artefacto_origen, artefacto_codigo "
                "FROM vivienda_inventario WHERE id = :id"
            ),
            {"id": inventario_id},
        )
    ).first()
    if not row:
        raise InventarioError(f"Inventario id {inventario_id} no existe")

    await dar_de_baja_artefacto(session, inventario_id, user_id, motivo=motivo)
    return await agregar_artefacto(
        session, schema_name, row.vivienda_id,
        row.artefacto_origen, row.artefacto_codigo,
        nueva_cantidad, user_id, motivo=motivo,
    )
