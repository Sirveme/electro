"""
Ejecutor de migraciones SQL versionadas (estilo SigcoWeb, sin Alembic).

- Lee la versión actual de public.schema_versions.
- Lista archivos v{NNN}_*.sql en la carpeta correspondiente.
- Aplica los pendientes en orden, dentro de una transacción cada uno.
- Para tenant: reemplaza {{SCHEMA}} por el schema real antes de ejecutar.

NOTA: usa conexión SYNCRÓNICA (psycopg2). Es CLI, procesos cortos, más simple.
"""
import logging
import os
import re
from pathlib import Path
from typing import Iterable

import psycopg2
from psycopg2.extensions import connection as PgConnection

logger = logging.getLogger(__name__)

MIGRATIONS_ROOT = Path(__file__).resolve().parents[2] / "migrations"
PUBLIC_DIR = MIGRATIONS_ROOT / "public"
TENANT_DIR = MIGRATIONS_ROOT / "tenant"

VERSION_FILE_RE = re.compile(r"^v(\d{3})_.+\.sql$", re.IGNORECASE)


def _ensure_schema_versions_table(conn: PgConnection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public.schema_versions (
                schema_name VARCHAR(40) PRIMARY KEY,
                version INT NOT NULL DEFAULT 0,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
    conn.commit()


def _current_version(conn: PgConnection, schema_name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT version FROM public.schema_versions WHERE schema_name = %s",
            (schema_name,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0


def _set_version(conn: PgConnection, schema_name: str, version: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.schema_versions (schema_name, version, applied_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (schema_name) DO UPDATE
            SET version = EXCLUDED.version, applied_at = NOW()
            """,
            (schema_name, version),
        )


def _list_migration_files(directory: Path) -> list[tuple[int, Path]]:
    if not directory.exists():
        return []
    out: list[tuple[int, Path]] = []
    for entry in directory.iterdir():
        if not entry.is_file():
            continue
        m = VERSION_FILE_RE.match(entry.name)
        if not m:
            continue
        out.append((int(m.group(1)), entry))
    out.sort(key=lambda x: x[0])
    return out


def _split_statements(sql: str) -> Iterable[str]:
    """
    Divide SQL en sentencias separadas por ';' fuera de bloques $$...$$.
    Ignora líneas que arrancan con '--' y líneas vacías.
    """
    buf: list[str] = []
    in_dollar = False
    for line in sql.splitlines():
        stripped = line.strip()
        if not in_dollar:
            if not stripped or stripped.startswith("--"):
                continue
        if "$$" in line:
            count = line.count("$$")
            if count % 2 == 1:
                in_dollar = not in_dollar
        buf.append(line)

    joined = "\n".join(buf)

    statements: list[str] = []
    current: list[str] = []
    in_dollar = False
    i = 0
    while i < len(joined):
        ch = joined[i]
        if joined[i:i+2] == "$$":
            in_dollar = not in_dollar
            current.append("$$")
            i += 2
            continue
        if ch == ";" and not in_dollar:
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def _apply_file(conn: PgConnection, path: Path, schema_replacement: str | None) -> None:
    sql = path.read_text(encoding="utf-8")
    if schema_replacement:
        sql = sql.replace("{{SCHEMA}}", schema_replacement)
    statements = list(_split_statements(sql))
    logger.info("Aplicando %s (%d statements)...", path.name, len(statements))
    with conn.cursor() as cur:
        for stmt in statements:
            cur.execute(stmt)


def _apply_pending(
    conn: PgConnection,
    directory: Path,
    schema_name: str,
    schema_replacement: str | None,
) -> list[str]:
    _ensure_schema_versions_table(conn)
    current = _current_version(conn, schema_name)
    aplicadas: list[str] = []

    for version, path in _list_migration_files(directory):
        if version <= current:
            continue
        try:
            _apply_file(conn, path, schema_replacement)
            _set_version(conn, schema_name, version)
            conn.commit()
            aplicadas.append(path.name)
            logger.info("OK %s aplicada a %s", path.name, schema_name)
        except Exception:
            conn.rollback()
            logger.exception("FALLO aplicando %s a %s", path.name, schema_name)
            raise
    return aplicadas


def aplicar_migraciones_public(db_url_sync: str) -> list[str]:
    """Aplica las migraciones pendientes al schema public."""
    conn = psycopg2.connect(db_url_sync)
    try:
        return _apply_pending(conn, PUBLIC_DIR, schema_name="public", schema_replacement=None)
    finally:
        conn.close()


def aplicar_migraciones_tenant(db_url_sync: str, schema_name: str) -> list[str]:
    """Aplica las migraciones pendientes al schema del tenant (reemplaza {{SCHEMA}})."""
    if not schema_name.startswith("muni_"):
        raise ValueError(f"schema_name '{schema_name}' no parece tenant (esperaba muni_*)")
    conn = psycopg2.connect(db_url_sync)
    try:
        return _apply_pending(conn, TENANT_DIR, schema_name=schema_name, schema_replacement=schema_name)
    finally:
        conn.close()
