"""Repository pattern for L3 (leaf) capability data access.

This module implements the repository pattern for clean separation between
business logic and data access layer for L3 capabilities.
"""

import logging
from typing import Any, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jwg_app.domain.services.abstract_repositories.base_repository import (
    IBaseRepository,
)
from jwg_app.infrastructure.database.models import L3CapabilityModel

logger = logging.getLogger(__name__)


class L3CapabilityRepository(IBaseRepository[L3CapabilityModel]):
    """Repository for L3 capability data access operations.

    Encapsulates all database operations for the L3 capability table,
    following the repository pattern for clean architecture.
    """

    def __init__(self, session: AsyncSession):
        """Initialize repository with database session.

        Args:
            session: SQLAlchemy async session
        """
        self.session = session

    async def get_by_ids(self, l3_capability_ids: List[str]) -> List[L3CapabilityModel]:
        """Get active L3 capabilities by their IDs.

        Args:
            l3_capability_ids: List of L3 capability identifiers

        Returns:
            List of active L3 capability records (order not guaranteed; caller keys by id)
        """
        try:
            if not l3_capability_ids:
                return []
            stmt = select(L3CapabilityModel).where(
                L3CapabilityModel.l3_capability_id.in_(set(l3_capability_ids)),
                L3CapabilityModel.capability_active == "yes",
            )
            result = await self.session.execute(stmt)
            records = list(result.scalars().all())
            logger.info(
                f"Fetched {len(records)} L3 capability(ies) for "
                f"{len(set(l3_capability_ids))} id(s)"
            )
            return records
        except Exception as e:
            logger.error(f"Error fetching L3 capabilities by IDs: {e}")
            raise

    # ----------------------------------------------------------------------- #
    # IBaseRepository contract methods                                        #
    # ----------------------------------------------------------------------- #

    async def create(self, **kwargs) -> L3CapabilityModel:
        """Not implemented - capabilities are managed externally."""
        raise NotImplementedError("Capabilities are read-only via this API")

    async def get_by_field(
        self, field_name: str, field_value: Any
    ) -> List[L3CapabilityModel]:
        """Get L3 capability records by any field."""
        try:
            field = getattr(L3CapabilityModel, field_name)
            stmt = select(L3CapabilityModel).where(
                field == field_value,
                L3CapabilityModel.capability_active == "yes",
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Error fetching by {field_name}: {e}")
            raise

    async def get_by_filter(self, filter_expression: Any) -> List[L3CapabilityModel]:
        """Get L3 capability records by a filter expression."""
        try:
            stmt = select(L3CapabilityModel).where(
                filter_expression,
                L3CapabilityModel.capability_active == "yes",
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Error fetching by filter: {e}")
            raise

    async def get_all(self) -> List[L3CapabilityModel]:
        """Get all active L3 capability records."""
        try:
            stmt = select(L3CapabilityModel).where(
                L3CapabilityModel.capability_active == "yes"
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Error fetching all L3 capabilities: {e}")
            raise

    async def update(
        self, filter_expression: Any, **fields
    ) -> Optional[L3CapabilityModel]:
        """Not implemented - capabilities are managed externally."""
        raise NotImplementedError("Capabilities are read-only via this API")

    async def delete(self, field_name: str, field_value: Any) -> bool:
        """Not implemented - capabilities are managed externally."""
        raise NotImplementedError("Capabilities are read-only via this API")
