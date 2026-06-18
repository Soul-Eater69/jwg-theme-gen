"""Repository pattern for value stream stage data access.

This module implements the repository pattern for clean separation between
business logic and data access layer for value stream stages.
"""

import logging
from typing import Any, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jwg_app.domain.services.abstract_repositories.base_repository import (
    IBaseRepository,
)
from jwg_app.infrastructure.database.models import ValueStreamStageModel

logger = logging.getLogger(__name__)


class ValueStreamStageRepository(IBaseRepository[ValueStreamStageModel]):
    """Repository for value stream stage data access operations.

    Encapsulates all database operations for the value stream stage table,
    following the repository pattern for clean architecture.
    """

    def __init__(self, session: AsyncSession):
        """Initialize repository with database session.

        Args:
            session: SQLAlchemy async session
        """
        self.session = session

    async def get_by_ids(self, stage_ids: List[str]) -> List[ValueStreamStageModel]:
        """Get active stages by their IDs.

        Args:
            stage_ids: List of value stream stage identifiers

        Returns:
            List of active stage records (order not guaranteed; caller keys by id)
        """
        try:
            if not stage_ids:
                return []
            stmt = select(ValueStreamStageModel).where(
                ValueStreamStageModel.value_stream_stage_id.in_(set(stage_ids)),
                ValueStreamStageModel.value_stream_stage_active == "yes",
            )
            result = await self.session.execute(stmt)
            records = list(result.scalars().all())
            logger.info(f"Fetched {len(records)} stage(s) for {len(set(stage_ids))} id(s)")
            return records
        except Exception as e:
            logger.error(f"Error fetching stages by IDs: {e}")
            raise

    # ----------------------------------------------------------------------- #
    # IBaseRepository contract methods                                        #
    # ----------------------------------------------------------------------- #

    async def create(self, **kwargs) -> ValueStreamStageModel:
        """Not implemented - stages are managed externally."""
        raise NotImplementedError("Stages are read-only via this API")

    async def get_by_field(
        self, field_name: str, field_value: Any
    ) -> List[ValueStreamStageModel]:
        """Get stage records by any field."""
        try:
            field = getattr(ValueStreamStageModel, field_name)
            stmt = select(ValueStreamStageModel).where(
                field == field_value,
                ValueStreamStageModel.value_stream_stage_active == "yes",
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Error fetching by {field_name}: {e}")
            raise

    async def get_by_filter(self, filter_expression: Any) -> List[ValueStreamStageModel]:
        """Get stage records by a filter expression."""
        try:
            stmt = select(ValueStreamStageModel).where(
                filter_expression,
                ValueStreamStageModel.value_stream_stage_active == "yes",
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Error fetching by filter: {e}")
            raise

    async def get_all(self) -> List[ValueStreamStageModel]:
        """Get all active stage records."""
        try:
            stmt = select(ValueStreamStageModel).where(
                ValueStreamStageModel.value_stream_stage_active == "yes"
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Error fetching all stages: {e}")
            raise

    async def update(
        self, filter_expression: Any, **fields
    ) -> Optional[ValueStreamStageModel]:
        """Not implemented - stages are managed externally."""
        raise NotImplementedError("Stages are read-only via this API")

    async def delete(self, field_name: str, field_value: Any) -> bool:
        """Not implemented - stages are managed externally."""
        raise NotImplementedError("Stages are read-only via this API")
