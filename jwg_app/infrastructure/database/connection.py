"""Async database engine and session factory.

NOTE: mirror this with the production infrastructure/database/connection.py. It builds the async
SQLAlchemy engine and yields one session per request for dependency injection. The connection URL
should come from the same configuration source the rest of the app uses.
"""

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DATABASE_URL = os.environ.get("DATABASE_URL", "")

_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Build the session factory on first use (avoids creating the engine at import time)."""
    global _session_factory
    if _session_factory is None:
        engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
        _session_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
    return _session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session, closing it when the request completes."""
    async with _get_session_factory()() as session:
        yield session
