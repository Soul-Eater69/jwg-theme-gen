"""Dependency injection for the theme service and its repositories."""

import logging

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from jwg_app.domain.services.theme_service import ThemeService
from jwg_app.infrastructure.database.connection import get_db_session
from jwg_app.infrastructure.repositories.l2_capability_repository import (
    L2CapabilityRepository,
)
from jwg_app.infrastructure.repositories.l3_capability_repository import (
    L3CapabilityRepository,
)
from jwg_app.infrastructure.repositories.value_stream_capability_repository import (
    ValueStreamCapabilityRepository,
)
from jwg_app.infrastructure.repositories.value_stream_repository import (
    ValueStreamRepository,
)
from jwg_app.infrastructure.repositories.value_stream_stage_repository import (
    ValueStreamStageRepository,
)

logger = logging.getLogger(__name__)


async def get_theme_service(
    session: AsyncSession = Depends(get_db_session),
) -> ThemeService:
    """Get ThemeService with its repositories wired to the injected database session.

    Args:
        session: SQLAlchemy async session from DI

    Returns:
        ThemeService instance
    """
    return ThemeService(
        value_stream_repository=ValueStreamRepository(session=session),
        stage_repository=ValueStreamStageRepository(session=session),
        capability_repository=ValueStreamCapabilityRepository(session=session),
        l3_repository=L3CapabilityRepository(session=session),
        l2_repository=L2CapabilityRepository(session=session),
    )
