"""Repository pattern for L2 capability data access.

This module implements the repository pattern for clean separation between
business logic and data access layer for L2 capabilities.
"""

import logging
from typing import Any, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jwg_app.domain.services.abstract_repositories.base_repository import (
    IBaseRepository,
)
from jwg_app.infrastructure.database.models import L2CapabilityModel

logger = logging.getLogger(__name__)


class L2CapabilityRepository(IBaseRepository[L2CapabilityModel]):
    """Repository for L2 capability data access operations.

    Encapsulates all database operations for the L2 capability table,
    following the repository pattern for clean architecture.
    """

    def __init__(self, session: AsyncSession):
        """Initialize repository with database session.

        Args:
            session: SQLAlchemy async session
        """
        self.session = session

    async def get_by_ids(self, l2_capability_ids: List[str]) -> List[L2CapabilityModel]:
        """Get active L2 capabilities by their IDs.

        Args:
            l2_capability_ids: List of L2 capability identifiers

        Returns:
            List of active L2 capability records (order not guaranteed; caller keys by id)
        """
        try:
            if not l2_capability_ids:
                return []
            stmt = select(L2CapabilityModel).where(
                L2CapabilityModel.l2_capability_id.in_(set(l2_capability_ids)),
                L2CapabilityModel.capability_active == "yes",
            )
            result = await self.session.execute(stmt)
            records = list(result.scalars().all())
            logger.info(
                f"Fetched {len(records)} L2 capability(ies) for "
                f"{len(set(l2_capability_ids))} id(s)"
            )
            return records
        except Exception as e:
            logger.error(f"Error fetching L2 capabilities by IDs: {e}")
            raise

    # ----------------------------------------------------------------------- #
    # IBaseRepository contract methods                                        #
    # ----------------------------------------------------------------------- #

    async def create(self, **kwargs) -> L2CapabilityModel:
        """Not implemented - capabilities are managed externally."""
        raise NotImplementedError("Capabilities are read-only via this API")

    async def get_by_field(
        self, field_name: str, field_value: Any
    ) -> List[L2CapabilityModel]:
        """Get L2 capability records by any field."""
        try:
            field = getattr(L2CapabilityModel, field_name)
            stmt = select(L2CapabilityModel).where(
                field == field_value,
                L2CapabilityModel.capability_active == "yes",
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Error fetching by {field_name}: {e}")
            raise

    async def get_by_filter(self, filter_expression: Any) -> List[L2CapabilityModel]:
        """Get L2 capability records by a filter expression."""
        try:
            stmt = select(L2CapabilityModel).where(
                filter_expression,
                L2CapabilityModel.capability_active == "yes",
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Error fetching by filter: {e}")
            raise

    async def get_all(self) -> List[L2CapabilityModel]:
        """Get all active L2 capability records."""
        try:
            stmt = select(L2CapabilityModel).where(
                L2CapabilityModel.capability_active == "yes"
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Error fetching all L2 capabilities: {e}")
            raise

    async def update(
        self, filter_expression: Any, **fields
    ) -> Optional[L2CapabilityModel]:
        """Not implemented - capabilities are managed externally."""
        raise NotImplementedError("Capabilities are read-only via this API")

    async def delete(self, field_name: str, field_value: Any) -> bool:
        """Not implemented - capabilities are managed externally."""
        raise NotImplementedError("Capabilities are read-only via this API")
