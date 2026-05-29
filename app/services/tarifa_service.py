"""
Servicio de tarifas: catálogo unificado para el tenant.

La vista unificada combina:
- public.artefacto_catalogo (lista maestra del SaaS)
- {{schema}}.artefacto_config (overrides por tenant: tarifa local + habilitado)
- {{schema}}.artefacto_propio (artefactos agregados por el municipio)

Operaciones soportadas:
- listar_unificado(): lista todo lo que el tenant puede ofrecer
- listar_habilitados(): solo los que aparecerán en el wizard
- editar_tarifa_catalogo(): UPSERT en artefacto_config
- toggle_catalogo(): UPSERT en artefacto_config cambiando habilitado
- crear_propio(), editar_propio(), toggle_propio(): CRUD de artefacto_propio
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class TarifaError(Exception):
    pass


async def listar_unificado(session: AsyncSession) -> list[dict]:
    """
    Retorna lista combinada de catálogo público (con override del tenant) + propios.
    Cada item:
        {origen, codigo, nombre, categoria, icono, tarifa, habilitado, orden}
    Ordenamiento: habilitado DESC, categoría, orden, nombre.
    """
    rows = (
        await session.execute(
            text(
                """
                SELECT
                    'catalogo' AS origen,
                    ac.codigo,
                    ac.nombre,
                    ac.categoria,
                    ac.icono,
                    COALESCE(cfg.tarifa_mensual, ac.tarifa_sugerida) AS tarifa,
                    CASE
                        WHEN cfg.habilitado IS NULL THEN ac.activo_default
                        ELSE cfg.habilitado
                    END AS habilitado,
                    COALESCE(cfg.es_frecuente, FALSE) AS es_frecuente,
                    ac.orden
                FROM public.artefacto_catalogo ac
                LEFT JOIN artefacto_config cfg ON cfg.catalogo_id = ac.id
                UNION ALL
                SELECT
                    'propio' AS origen,
                    codigo,
                    nombre,
                    categoria,
                    NULL AS icono,
                    tarifa_mensual AS tarifa,
                    habilitado,
                    COALESCE(es_frecuente, FALSE) AS es_frecuente,
                    orden
                FROM artefacto_propio
                ORDER BY habilitado DESC, categoria, orden, nombre
                """
            )
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def listar_habilitados(session: AsyncSession) -> list[dict]:
    """Solo los habilitados (vista que ve el empadronador en paso 4)."""
    todos = await listar_unificado(session)
    return [t for t in todos if t.get("habilitado")]


async def _catalogo_id_por_codigo(session: AsyncSession, codigo: str) -> Optional[int]:
    row = (
        await session.execute(
            text("SELECT id FROM public.artefacto_catalogo WHERE codigo = :c"),
            {"c": codigo},
        )
    ).first()
    return row.id if row else None


async def editar_tarifa_catalogo(
    session: AsyncSession, codigo: str, tarifa_nueva: Decimal
) -> dict:
    """UPSERT en artefacto_config con la nueva tarifa. Mantiene habilitado existente."""
    if tarifa_nueva is None or tarifa_nueva < 0:
        raise TarifaError("La tarifa debe ser >= 0")

    catalogo_id = await _catalogo_id_por_codigo(session, codigo)
    if not catalogo_id:
        raise TarifaError(f"Artefacto de catálogo no encontrado: {codigo}")

    await session.execute(
        text(
            """
            INSERT INTO artefacto_config (catalogo_id, tarifa_mensual, habilitado)
            VALUES (:cid, :t, TRUE)
            ON CONFLICT (catalogo_id) DO UPDATE
                SET tarifa_mensual = EXCLUDED.tarifa_mensual
            """
        ),
        {"cid": catalogo_id, "t": tarifa_nueva},
    )
    return {"codigo": codigo, "origen": "catalogo", "tarifa": float(tarifa_nueva)}


async def toggle_catalogo(session: AsyncSession, codigo: str) -> bool:
    """Toggle del flag habilitado para un artefacto del catálogo público. Retorna el nuevo valor."""
    catalogo_id = await _catalogo_id_por_codigo(session, codigo)
    if not catalogo_id:
        raise TarifaError(f"Artefacto de catálogo no encontrado: {codigo}")

    row = (
        await session.execute(
            text(
                """
                SELECT
                    CASE
                        WHEN cfg.habilitado IS NULL THEN ac.activo_default
                        ELSE cfg.habilitado
                    END AS habilitado,
                    COALESCE(cfg.tarifa_mensual, ac.tarifa_sugerida) AS tarifa
                FROM public.artefacto_catalogo ac
                LEFT JOIN artefacto_config cfg ON cfg.catalogo_id = ac.id
                WHERE ac.codigo = :c
                """
            ),
            {"c": codigo},
        )
    ).first()
    actual = bool(row.habilitado) if row else True
    nuevo = not actual
    tarifa_actual = row.tarifa if row else Decimal("0")

    await session.execute(
        text(
            """
            INSERT INTO artefacto_config (catalogo_id, tarifa_mensual, habilitado)
            VALUES (:cid, :t, :h)
            ON CONFLICT (catalogo_id) DO UPDATE
                SET habilitado = EXCLUDED.habilitado
            """
        ),
        {"cid": catalogo_id, "t": tarifa_actual, "h": nuevo},
    )
    return nuevo


async def toggle_frecuente_catalogo(session: AsyncSession, codigo: str) -> bool:
    """Toggle del flag es_frecuente de un artefacto de catálogo. Retorna nuevo valor.

    UPSERT en artefacto_config preservando tarifa/habilitado actuales.
    """
    catalogo_id = await _catalogo_id_por_codigo(session, codigo)
    if not catalogo_id:
        raise TarifaError(f"Artefacto de catálogo no encontrado: {codigo}")

    row = (
        await session.execute(
            text(
                """
                SELECT
                    CASE
                        WHEN cfg.habilitado IS NULL THEN ac.activo_default
                        ELSE cfg.habilitado
                    END AS habilitado,
                    COALESCE(cfg.tarifa_mensual, ac.tarifa_sugerida) AS tarifa,
                    COALESCE(cfg.es_frecuente, FALSE) AS es_frecuente
                FROM public.artefacto_catalogo ac
                LEFT JOIN artefacto_config cfg ON cfg.catalogo_id = ac.id
                WHERE ac.codigo = :c
                """
            ),
            {"c": codigo},
        )
    ).first()
    nuevo = not (bool(row.es_frecuente) if row else False)
    habilitado_actual = bool(row.habilitado) if row else True
    tarifa_actual = row.tarifa if row else Decimal("0")

    await session.execute(
        text(
            """
            INSERT INTO artefacto_config (catalogo_id, tarifa_mensual, habilitado, es_frecuente)
            VALUES (:cid, :t, :h, :f)
            ON CONFLICT (catalogo_id) DO UPDATE
                SET es_frecuente = EXCLUDED.es_frecuente
            """
        ),
        {"cid": catalogo_id, "t": tarifa_actual, "h": habilitado_actual, "f": nuevo},
    )
    return nuevo


async def toggle_frecuente_propio(session: AsyncSession, codigo: str) -> bool:
    """Toggle del flag es_frecuente de un artefacto propio. Retorna nuevo valor."""
    row = (
        await session.execute(
            text("SELECT COALESCE(es_frecuente, FALSE) AS es_frecuente FROM artefacto_propio WHERE codigo = :c"),
            {"c": codigo},
        )
    ).first()
    if not row:
        raise TarifaError(f"Artefacto propio '{codigo}' no encontrado")
    nuevo = not bool(row.es_frecuente)
    await session.execute(
        text("UPDATE artefacto_propio SET es_frecuente = :f WHERE codigo = :c"),
        {"f": nuevo, "c": codigo},
    )
    return nuevo


async def crear_propio(
    session: AsyncSession,
    codigo: str,
    nombre: str,
    categoria: str,
    tarifa: Decimal,
    habilitado: bool = True,
    orden: int = 100,
) -> int:
    codigo = (codigo or "").strip().upper()
    nombre = (nombre or "").strip()
    if not codigo or not nombre or not categoria:
        raise TarifaError("Código, nombre y categoría son obligatorios")
    if tarifa is None or tarifa < 0:
        raise TarifaError("La tarifa debe ser >= 0")

    dup = (
        await session.execute(
            text("SELECT id FROM artefacto_propio WHERE codigo = :c"),
            {"c": codigo},
        )
    ).first()
    if dup:
        raise TarifaError(f"Ya existe un artefacto propio con código '{codigo}'")

    row = (
        await session.execute(
            text(
                """
                INSERT INTO artefacto_propio (codigo, nombre, categoria, tarifa_mensual, habilitado, orden)
                VALUES (:c, :n, :cat, :t, :h, :o)
                RETURNING id
                """
            ),
            {"c": codigo, "n": nombre, "cat": categoria, "t": tarifa, "h": habilitado, "o": orden},
        )
    ).first()
    return row.id


async def editar_propio_tarifa(
    session: AsyncSession, codigo: str, tarifa_nueva: Decimal
) -> dict:
    if tarifa_nueva is None or tarifa_nueva < 0:
        raise TarifaError("La tarifa debe ser >= 0")
    res = await session.execute(
        text("UPDATE artefacto_propio SET tarifa_mensual = :t WHERE codigo = :c"),
        {"t": tarifa_nueva, "c": codigo},
    )
    if res.rowcount == 0:
        raise TarifaError(f"Artefacto propio '{codigo}' no encontrado")
    return {"codigo": codigo, "origen": "propio", "tarifa": float(tarifa_nueva)}


async def toggle_propio(session: AsyncSession, codigo: str) -> bool:
    row = (
        await session.execute(
            text("SELECT habilitado FROM artefacto_propio WHERE codigo = :c"),
            {"c": codigo},
        )
    ).first()
    if not row:
        raise TarifaError(f"Artefacto propio '{codigo}' no encontrado")
    nuevo = not bool(row.habilitado)
    await session.execute(
        text("UPDATE artefacto_propio SET habilitado = :h WHERE codigo = :c"),
        {"h": nuevo, "c": codigo},
    )
    return nuevo


async def obtener_branding(session: AsyncSession) -> dict:
    """Lee logo_url, nombre_municipalidad y nombre_corto de config_municipio.

    Retorna dict siempre (con strings vacios si falta una clave). Usado por
    auth.py al login para cachear branding en la sesion y por
    configuracion.py para mostrar/guardar el form de marca.
    """
    rows = (
        await session.execute(
            text(
                "SELECT clave, valor FROM config_municipio "
                "WHERE clave IN ('logo_url', 'nombre_municipalidad', 'nombre_corto')"
            )
        )
    ).all()
    out = {"logo_url": "", "nombre_municipalidad": "", "nombre_corto": ""}
    for r in rows:
        if r.clave in out:
            out[r.clave] = r.valor or ""
    return out


async def guardar_branding(
    session: AsyncSession,
    logo_url: Optional[str] = None,
    nombre_municipalidad: Optional[str] = None,
    nombre_corto: Optional[str] = None,
) -> None:
    """UPSERT de las claves de branding. Solo actualiza las que vengan no-None."""
    items: list[tuple[str, str]] = []
    if logo_url is not None:
        items.append(("logo_url", logo_url))
    if nombre_municipalidad is not None:
        items.append(("nombre_municipalidad", nombre_municipalidad))
    if nombre_corto is not None:
        items.append(("nombre_corto", nombre_corto))
    for clave, valor in items:
        await session.execute(
            text(
                """
                INSERT INTO config_municipio (clave, valor, tipo, descripcion)
                VALUES (:k, :v, 'string', NULL)
                ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor
                """
            ),
            {"k": clave, "v": valor},
        )


async def obtener_config_calculo(session: AsyncSession) -> dict:
    """
    Lee de config_municipio las claves usadas en el cálculo de recibo:
    cargo_fijo_mensual, adicional_por_morador.
    Retorna floats.
    """
    rows = (
        await session.execute(
            text(
                "SELECT clave, valor FROM config_municipio "
                "WHERE clave IN ('cargo_fijo_mensual', 'adicional_por_morador')"
            )
        )
    ).all()
    out = {"cargo_fijo_mensual": 0.0, "adicional_por_morador": 0.0}
    for r in rows:
        try:
            out[r.clave] = float(r.valor) if r.valor not in (None, "") else 0.0
        except (TypeError, ValueError):
            out[r.clave] = 0.0
    return out


async def guardar_config_calculo(
    session: AsyncSession, cargo_fijo: Decimal, adicional_morador: Decimal
) -> None:
    if cargo_fijo is None or cargo_fijo < 0:
        raise TarifaError("Cargo fijo debe ser >= 0")
    if adicional_morador is None or adicional_morador < 0:
        raise TarifaError("Adicional por morador debe ser >= 0")

    for clave, valor in (
        ("cargo_fijo_mensual", cargo_fijo),
        ("adicional_por_morador", adicional_morador),
    ):
        await session.execute(
            text(
                """
                INSERT INTO config_municipio (clave, valor, tipo, descripcion)
                VALUES (:k, :v, 'decimal', NULL)
                ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor
                """
            ),
            {"k": clave, "v": str(valor)},
        )
