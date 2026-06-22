"""Dependency injection for the theme service."""

import logging

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from jwg_app.domain.services.theme_service import ThemeService
from jwg_app.infrastructure.database.connection import get_db_session
from jwg_app.infrastructure.repositories.value_stream_catalogue_repository import (
    ValueStreamCatalogueRepository,
)

logger = logging.getLogger(__name__)


async def get_theme_service(
    session: AsyncSession = Depends(get_db_session),
) -> ThemeService:
    """Get ThemeService wired to the catalogue read repository on the injected session.

    Args:
        session: SQLAlchemy async session from DI.

    Returns:
        ThemeService instance.
    """
    return ThemeService(catalogue_repository=ValueStreamCatalogueRepository(session=session))
