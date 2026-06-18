"""Repository pattern for the value stream <-> stage <-> capability mapping.

This module implements the repository pattern for clean separation between
business logic and data access layer for the value stream capability mapping table.
This mapping is the only link between a value stream and its stages and L3 capabilities.
"""

import logging
from typing import Any, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jwg_app.domain.services.abstract_repositories.base_repository import (
    IBaseRepository,
)
from jwg_app.infrastructure.database.models import ValueStreamCapabilityModel

logger = logging.getLogger(__name__)


class ValueStreamCapabilityRepository(IBaseRepository[ValueStreamCapabilityModel]):
    """Repository for the value stream capability mapping table.

    Encapsulates all database operations for the mapping table, following the
    repository pattern for clean architecture.
    """

    def __init__(self, session: AsyncSession):
        """Initialize repository with database session.

        Args:
            session: SQLAlchemy async session
        """
        self.session = session

    async def get_by_value_stream_ids(
        self, value_stream_ids: List[str]
    ) -> List[ValueStreamCapabilityModel]:
        """Get all mapping rows for the given value streams.

        Each row carries the value stream, one of its stages, and one L3 capability.

        Args:
            value_stream_ids: List of value stream identifiers

        Returns:
            List of mapping rows for those value streams
        """
        try:
            if not value_stream_ids:
                return []
            stmt = select(ValueStreamCapabilityModel).where(
                ValueStreamCapabilityModel.value_stream_id.in_(set(value_stream_ids))
            )
            result = await self.session.execute(stmt)
            records = list(result.scalars().all())
            logger.info(
                f"Fetched {len(records)} mapping row(s) for "
                f"{len(set(value_stream_ids))} value stream(s)"
            )
            return records
        except Exception as e:
            logger.error(f"Error fetching mapping rows by value stream IDs: {e}")
            raise

    # ----------------------------------------------------------------------- #
    # IBaseRepository contract methods                                        #
    # ----------------------------------------------------------------------- #

    async def create(self, **kwargs) -> ValueStreamCapabilityModel:
        """Not implemented - the mapping is managed externally."""
        raise NotImplementedError("The capability mapping is read-only via this API")

    async def get_by_field(
        self, field_name: str, field_value: Any
    ) -> List[ValueStreamCapabilityModel]:
        """Get mapping rows by any field."""
        try:
            field = getattr(ValueStreamCapabilityModel, field_name)
            stmt = select(ValueStreamCapabilityModel).where(field == field_value)
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Error fetching by {field_name}: {e}")
            raise

    async def get_by_filter(
        self, filter_expression: Any
    ) -> List[ValueStreamCapabilityModel]:
        """Get mapping rows by a filter expression."""
        try:
            stmt = select(ValueStreamCapabilityModel).where(filter_expression)
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Error fetching by filter: {e}")
            raise

    async def get_all(self) -> List[ValueStreamCapabilityModel]:
        """Get all mapping rows."""
        try:
            stmt = select(ValueStreamCapabilityModel)
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Error fetching all mapping rows: {e}")
            raise

    async def update(
        self, filter_expression: Any, **fields
    ) -> Optional[ValueStreamCapabilityModel]:
        """Not implemented - the mapping is managed externally."""
        raise NotImplementedError("The capability mapping is read-only via this API")

    async def delete(self, field_name: str, field_value: Any) -> bool:
        """Not implemented - the mapping is managed externally."""
        raise NotImplementedError("The capability mapping is read-only via this API")
