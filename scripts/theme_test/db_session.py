"""Async SQLAlchemy session for the catalogue tests — FOR TESTING ONLY.

Reuses the real connection (jwg_app.infrastructure.database.connection), which builds the async
Azure SQL engine from the app Settings (DB_* in .env). Requires an async ODBC driver:
`pip install aioodbc`.

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

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # noqa: E402

from jwg_app.infrastructure.database.connection import async_session_factory  # noqa: E402


def build_async_session_factory() -> async_sessionmaker[AsyncSession]:
    """The shared async session factory from the real connection module."""
    return async_session_factory


async def _check() -> None:
    """Open one async session and run SELECT 1 to confirm connectivity."""
    async with async_session_factory() as session:
        result = await session.execute(text("SELECT 1"))
        print("DB session OK, SELECT 1 ->", result.scalar())


if __name__ == "__main__":
    import asyncio

    asyncio.run(_check())
