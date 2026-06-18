"""Async SQLAlchemy session for the catalogue — FOR TESTING ONLY.

Builds an async engine against Azure SQL with the same connection shape the verify script uses
(Azure AD auth via ODBC), so the real ThemeService + repositories can be exercised against the live
database. Requires an async ODBC driver: `pip install aioodbc`. Config comes from env vars; fill them
with the same values you used in verify_catalogue_schema.py.
"""

from __future__ import annotations

import os
from urllib.parse import quote_plus

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def build_async_session_factory() -> async_sessionmaker[AsyncSession]:
    """Build an async session factory from env vars.

    Required: SQL_SERVER, SQL_DATABASE, SQL_USERNAME, SQL_PASSWORD.
    Optional: SQL_PORT (1433), ODBC_DRIVER (ODBC Driver 17 for SQL Server),
    SQL_AUTHENTICATION (ActiveDirectoryPassword; set "" for plain SQL login).
    """
    driver = os.environ.get("ODBC_DRIVER", "ODBC Driver 17 for SQL Server")
    server = os.environ.get("SQL_SERVER", "")
    database = os.environ.get("SQL_DATABASE", "")
    username = os.environ.get("SQL_USERNAME", "")
    password = os.environ.get("SQL_PASSWORD", "")
    port = os.environ.get("SQL_PORT", "1433")
    authentication = os.environ.get("SQL_AUTHENTICATION", "ActiveDirectoryPassword")

    odbc = (
        f"DRIVER={{{driver}}};SERVER={server},{port};DATABASE={database};"
        f"UID={username};PWD={password};Encrypt=yes;TrustServerCertificate=no;"
        f"Connection Timeout=30;"
    )
    if authentication:
        odbc += f"Authentication={authentication};"

    url = f"mssql+aioodbc:///?odbc_connect={quote_plus(odbc)}"
    engine = create_async_engine(url, pool_pre_ping=True)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _check() -> None:
    """Open one async session and run SELECT 1 to confirm connectivity."""
    factory = build_async_session_factory()
    async with factory() as session:
        result = await session.execute(text("SELECT 1"))
        print("DB session OK, SELECT 1 ->", result.scalar())


if __name__ == "__main__":
    import asyncio

    asyncio.run(_check())
