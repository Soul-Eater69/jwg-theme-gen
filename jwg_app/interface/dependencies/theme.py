"""Dependency injection for the theme service."""

import logging

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from jwg_app.domain.services.theme_service import ThemeService
from jwg_app.infrastructure.database.connection import get_db_session

logger = logging.getLogger(__name__)


async def get_theme_service(
    session: AsyncSession = Depends(get_db_session),
) -> ThemeService:
    """Get ThemeService wired to the injected database session.

    Args:
        session: SQLAlchemy async session from DI.

    Returns:
        ThemeService instance.
    """
    return ThemeService(session=session)
