"""Async DB session for the catalogue tests — FOR TESTING ONLY.

Self-contained: reads ONLY the DB_* values from .env (ignoring the rest of the app config) and builds
the async Azure SQL engine. This avoids constructing the full prod Settings, which requires many
unrelated fields (Cosmos, platform, Jira, ...) you may not have locally. The DB_* names match the prod
Settings, so it reads the same .env values. Requires an async ODBC driver: `pip install aioodbc`.

Run directly to test connectivity in isolation (SELECT 1):
    python scripts/theme_test/db_session.py
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class _DbSettings(BaseSettings):
    """DB-only settings — reads the DB_* fields from .env and ignores everything else."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=True)

    DB_SERVER: str = ""
    DATABASE: str = ""
    DB_USERNAME: str = ""
    DB_PASSWORD: str = ""
    DB_DRIVER: str = "ODBC Driver 17 for SQL Server"
    DB_AUTHENTICATION: str = "ActiveDirectoryPassword"
    DB_ENCRYPT: str = "yes"
    DB_TRUST_SERVER_CERTIFICATE: str = "no"


def _database_url() -> str:
    s = _DbSettings()
    odbc = (
        f"DRIVER={{{s.DB_DRIVER}}};SERVER={s.DB_SERVER};DATABASE={s.DATABASE};"
        f"UID={s.DB_USERNAME};PWD={s.DB_PASSWORD};Encrypt={s.DB_ENCRYPT};"
        f"TrustServerCertificate={s.DB_TRUST_SERVER_CERTIFICATE};Connection Timeout=30;"
    )
    if s.DB_AUTHENTICATION:
        odbc += f"Authentication={s.DB_AUTHENTICATION};"
    return f"mssql+aioodbc:///?odbc_connect={quote_plus(odbc)}"


_engine = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def _factory() -> async_sessionmaker[AsyncSession]:
    """Build the async engine + session factory on first use."""
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_async_engine(_database_url(), pool_pre_ping=True)
        _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Yield one async session for a test."""
    async with _factory()() as session:
        yield session


async def dispose() -> None:
    """Dispose the engine at the end of a script (avoids 'unclosed connection' warnings)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


async def _check() -> None:
    """Open one async session and run SELECT 1 to confirm connectivity."""
    s = _DbSettings()
    print(
        "DB config read from .env: "
        f"DRIVER={s.DB_DRIVER!r} SERVER={s.DB_SERVER!r} DATABASE={s.DATABASE!r} "
        f"UID={s.DB_USERNAME!r} AUTH={s.DB_AUTHENTICATION!r} "
        f"ENCRYPT={s.DB_ENCRYPT!r} TRUST={s.DB_TRUST_SERVER_CERTIFICATE!r} "
        f"(password set: {bool(s.DB_PASSWORD)})"
    )
    try:
        async with session_scope() as session:
            result = await session.execute(text("SELECT 1"))
            print("DB session OK, SELECT 1 ->", result.scalar())
    finally:
        await dispose()


if __name__ == "__main__":
    import asyncio

    asyncio.run(_check())
