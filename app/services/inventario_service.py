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
        if not row:
            logger.warning(
                "Catálogo público no tiene código='%s' (schema_name=%s)", codigo, schema_name
            )
            return None
        return row.nombre
    if origen == "propio":
        row = (
            await session.execute(
                text(f'SELECT nombre FROM "{schema_name}".artefacto_propio WHERE codigo = :c'),
                {"c": codigo},
            )
        ).first()
        if not row:
            logger.warning(
                "artefacto_propio no tiene código='%s' (schema=%s)", codigo, schema_name
            )
            return None
        return row.nombre
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


async def sincronizar_inventario(
    session: AsyncSession,
    schema_name: str,
    vivienda_id: int,
    cantidades_objetivo: list[dict],
    user_id: int,
    motivo: str = "inventario_modificacion",
) -> dict:
    """
    Sincroniza el inventario vigente de una vivienda con un set de cantidades objetivo.

    `cantidades_objetivo` es una lista de dicts con shape
        {"origen": "catalogo"|"propio", "codigo": str, "cantidad": int}

    Reglas (effective dating):
      - cantidad_actual == cantidad_objetivo  → no-op
      - existe & cantidad_objetivo == 0       → cerrar fila vigente (baja)
      - existe & cantidad_objetivo != actual  → cerrar fila vigente + insertar nueva
      - no existe & cantidad_objetivo > 0     → insertar nueva fila

    Registra UN solo evento `inventario_modificacion` con un resumen consolidado
    de los cambios en metadata.

    El caller NO debe hacer commit: esta función no commitea; lo deja al caller
    para que pueda hacer commit atómico junto con otras operaciones.

    Retorna un dict con resumen: {altas, bajas, sin_cambio, cambios_cantidad}.
    """
    actuales = await inventario_actual_de_vivienda(session, vivienda_id)
    # Indexar por (origen, codigo) para mirar O(1)
    actuales_idx: dict[tuple[str, str], dict] = {
        (r["artefacto_origen"], r["artefacto_codigo"]): r for r in actuales
    }

    altas: list[dict] = []
    bajas: list[dict] = []
    cambios: list[dict] = []
    sin_cambio: list[dict] = []

    objetivos_idx: dict[tuple[str, str], int] = {}
    for it in cantidades_objetivo:
        origen = it.get("origen")
        codigo = it.get("codigo")
        cantidad = int(it.get("cantidad") or 0)
        if origen not in ("catalogo", "propio"):
            raise InventarioError(f"origen invalido: {origen!r}")
        if not codigo:
            raise InventarioError("Falta el codigo de artefacto")
        if cantidad < 0:
            raise InventarioError(f"Cantidad negativa para {origen}/{codigo}")
        objetivos_idx[(origen, codigo)] = cantidad

    # 1) Artefactos que estan en objetivos: comparar con actuales.
    for (origen, codigo), cantidad_obj in objetivos_idx.items():
        actual = actuales_idx.get((origen, codigo))
        if actual is None:
            if cantidad_obj > 0:
                await agregar_artefacto(
                    session, schema_name, vivienda_id,
                    origen, codigo, cantidad_obj, user_id, motivo=motivo,
                )
                altas.append({"origen": origen, "codigo": codigo, "cantidad": cantidad_obj})
            # cantidad_obj == 0 y no existia: no-op (ni siquiera registrar)
        else:
            cantidad_actual = int(actual["cantidad"])
            inv_id = int(actual["id"])
            if cantidad_obj == cantidad_actual:
                sin_cambio.append({"origen": origen, "codigo": codigo, "cantidad": cantidad_actual})
            elif cantidad_obj == 0:
                await dar_de_baja_artefacto(session, inv_id, user_id, motivo=motivo)
                bajas.append({"origen": origen, "codigo": codigo, "cantidad_previa": cantidad_actual})
            else:
                await cambiar_cantidad(
                    session, schema_name, inv_id, cantidad_obj, user_id, motivo=motivo,
                )
                cambios.append({
                    "origen": origen, "codigo": codigo,
                    "cantidad_previa": cantidad_actual, "cantidad_nueva": cantidad_obj,
                })

    # 2) Artefactos vigentes que NO aparecen en objetivos: baja implicita? NO.
    #    Solo se da de baja si el form lo manda con cantidad=0 (explicito).
    #    Esto evita que un form parcialmente cargado borre todo lo demas.

    resumen = {
        "altas": altas,
        "bajas": bajas,
        "cambios_cantidad": cambios,
        "sin_cambio": sin_cambio,
    }

    # Si ningun cambio real, no registrar evento.
    if altas or bajas or cambios:
        await _registrar_evento(
            session, vivienda_id, "inventario_modificacion", user_id,
            descripcion=(
                f"Inventario: {len(altas)} alta(s), {len(bajas)} baja(s), "
                f"{len(cambios)} cambio(s) de cantidad"
            ),
            metadata=resumen,
        )

    logger.info(
        "Inventario vivienda %d sincronizado por user %d: %d altas, %d bajas, %d cambios",
        vivienda_id, user_id, len(altas), len(bajas), len(cambios),
    )
    return resumen
