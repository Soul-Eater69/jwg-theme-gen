"""Async DB session for the catalogue tests — FOR TESTING ONLY.

Thin wrapper over the prod DatabaseManager (jwg_app.infrastructure.database.connection), which builds
the async Azure SQL engine from the app Settings (DB_* in .env) via build_connection_url(). Requires
an async ODBC driver: `pip install aioodbc`.

Run directly to test connectivity in isolation (SELECT 1):
    python scripts/theme_test/db_session.py
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
for _p in (HERE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from contextlib import asynccontextmanager  # noqa: E402
from typing import AsyncIterator  # noqa: E402

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from jwg_app.infrastructure.database.connection import DatabaseManager  # noqa: E402


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Yield one async session from the (singleton) DatabaseManager, initializing it if needed."""
    manager = DatabaseManager()
    manager.initialize()  # idempotent; builds the engine from settings on first call
    async with manager.get_session() as session:
        yield session


async def _check() -> None:
    """Open one async session and run SELECT 1 to confirm connectivity."""
    async with session_scope() as session:
        result = await session.execute(text("SELECT 1"))
        print("DB session OK, SELECT 1 ->", result.scalar())


if __name__ == "__main__":
    import asyncio

    asyncio.run(_check())
