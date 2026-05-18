import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

from app.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dependencia FastAPI: sesión sobre el schema public."""
    async with SessionLocal() as session:
        yield session


@asynccontextmanager
async def tenant_session(schema_name: str) -> AsyncIterator[AsyncSession]:
    """
    Context manager que abre una sesión y fija el search_path al schema del tenant.
    Uso:
        async with tenant_session("muni_160101") as session:
            ...
    """
    async with SessionLocal() as session:
        await session.execute(text(f'SET search_path TO "{schema_name}", public'))
        try:
            yield session
        finally:
            await session.execute(text("SET search_path TO public"))


async def get_tenant_session(schema_name: str) -> AsyncIterator[AsyncSession]:
    """Versión generador para usar como Depends() en rutas."""
    async with tenant_session(schema_name) as session:
        yield session
