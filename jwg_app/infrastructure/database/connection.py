"""Async database engine and session factory.

Builds the async SQLAlchemy engine for Azure SQL from the app Settings (jwg_app.core.config) and
yields one session per request for dependency injection. The ODBC connection string uses the same
DB_* settings (driver, Azure AD authentication, encrypt) the rest of the app reads from .env.
"""

from collections.abc import AsyncGenerator
from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from jwg_app.core.config import settings


def _odbc_connection_string() -> str:
    """Build the ODBC connection string from the DB_* settings."""
    odbc = (
        f"DRIVER={{{settings.DB_DRIVER}}};SERVER={settings.DB_SERVER};"
        f"DATABASE={settings.DATABASE};UID={settings.DB_USERNAME};PWD={settings.DB_PASSWORD};"
        f"Encrypt={settings.DB_ENCRYPT};"
        f"TrustServerCertificate={settings.DB_TRUST_SERVER_CERTIFICATE};"
        f"Connection Timeout=30;"
    )
    if settings.DB_AUTHENTICATION:
        odbc += f"Authentication={settings.DB_AUTHENTICATION};"
    return odbc


def _database_url() -> str:
    return f"mssql+aioodbc:///?odbc_connect={quote_plus(_odbc_connection_string())}"


engine = create_async_engine(_database_url(), pool_pre_ping=True)
async_session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session, closing it when the request completes."""
    async with async_session_factory() as session:
        yield session
