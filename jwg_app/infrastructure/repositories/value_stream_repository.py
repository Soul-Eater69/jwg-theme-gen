"""Repository pattern for ValueStream data access.

This module implements the repository pattern for clean separation between
business logic and data access layer for value streams.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from jwg_app.domain.services.abstract_repositories.base_repository import (
    IBaseRepository,
)
from jwg_app.infrastructure.database.models import ValueStreamModel

logger = logging.getLogger(__name__)


class ValueStreamRepository(IBaseRepository[ValueStreamModel]):
    """Repository for ValueStream data access operations.

    Encapsulates all database operations for the ValueStream table,
    following the repository pattern for clean architecture.
    """

    def __init__(self, session: AsyncSession):
        """Initialize repository with database session.

        Args:
            session: SQLAlchemy async session
        """
        self.session = session

    async def get_by_id(self, value_stream_id: str) -> Optional[ValueStreamModel]:
        """Get a single active value stream by ID.

        Args:
            value_stream_id: The value stream identifier (e.g., VSR00074585)

        Returns:
            ValueStreamModel if found and active, None otherwise
        """
        try:
            stmt = select(ValueStreamModel).where(
                ValueStreamModel.value_stream_id == value_stream_id,
                ValueStreamModel.value_stream_active == "yes",
            )
            result = await self.session.execute(stmt)
            record = result.scalars().first()

            if record:
                logger.info(f"Retrieved value stream: {value_stream_id}")
            else:
                logger.info(f"Value stream not found or inactive: {value_stream_id}")

            return record

        except Exception as e:
            logger.error(f"Error fetching value stream {value_stream_id}: {e}")
            raise

    async def get_by_ids(
        self, value_stream_ids: List[str]
    ) -> Tuple[List[ValueStreamModel], List[str]]:
        """Get multiple active value streams by IDs.

        Maintains request order in response and reports missing/inactive IDs.

        Args:
            value_stream_ids: List of value stream identifiers

        Returns:
            Tuple of (found items in request order, list of missing/inactive IDs)
        """
        try:
            # Deduplicate while preserving order
            seen = set()
            unique_ids = []
            for vs_id in value_stream_ids:
                if vs_id not in seen:
                    seen.add(vs_id)
                    unique_ids.append(vs_id)

            stmt = select(ValueStreamModel).where(
                ValueStreamModel.value_stream_id.in_(unique_ids),
                ValueStreamModel.value_stream_active == "yes",
            )
            result = await self.session.execute(stmt)
            records = result.scalars().all()

            # Build lookup map
            record_map: Dict[str, ValueStreamModel] = {
                r.value_stream_id: r for r in records
            }

            # Maintain request order
            found_items = []
            missing_ids = []
            for vs_id in unique_ids:
                if vs_id in record_map:
                    found_items.append(record_map[vs_id])
                else:
                    missing_ids.append(vs_id)

            logger.info(
                f"Bulk fetch: {len(found_items)} found, {len(missing_ids)} missing "
                f"out of {len(unique_ids)} unique IDs requested"
            )
            return found_items, missing_ids

        except Exception as e:
            logger.error(f"Error fetching value streams by IDs: {e}")
            raise

    async def search_paginated(
        self,
        query: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[ValueStreamModel], int]:
        """Search and paginate active value streams.

        Args:
            query: Optional search string (searches across ID, name, description)
            page: Page number (1-indexed)
            page_size: Items per page

        Returns:
            Tuple of (list of value streams for this page, total count)
        """
        try:
            # Base filter: active only
            base_filter = ValueStreamModel.value_stream_active == "yes"

            # Build search filter
            if query:
                search_pattern = f"%{query}%"
                search_filter = or_(
                    ValueStreamModel.value_stream_id.ilike(search_pattern),
                    ValueStreamModel.value_stream_name.ilike(search_pattern),
                    ValueStreamModel.value_stream_display_name.ilike(search_pattern),
                    ValueStreamModel.value_stream_description.ilike(search_pattern),
                )
                combined_filter = base_filter & search_filter
            else:
                combined_filter = base_filter

            # Count total items
            count_stmt = select(func.count()).select_from(
                select(ValueStreamModel).where(combined_filter).subquery()
            )
            count_result = await self.session.execute(count_stmt)
            total_items = count_result.scalar() or 0

            # Fetch paginated results ordered by value_stream_id ascending
            offset = (page - 1) * page_size
            data_stmt = (
                select(ValueStreamModel)
                .where(combined_filter)
                .order_by(ValueStreamModel.value_stream_id.asc())
                .offset(offset)
                .limit(page_size)
            )
            data_result = await self.session.execute(data_stmt)
            records = data_result.scalars().all()

            logger.info(
                f"Search paginated: query='{query}', page={page}, "
                f"page_size={page_size}, total={total_items}, returned={len(records)}"
            )
            return list(records), total_items

        except Exception as e:
            logger.error(f"Error searching value streams: {e}")
            raise

    # ----------------------------------------------------------------------- #
    # IBaseRepository contract methods                                        #
    # ----------------------------------------------------------------------- #

    async def create(self, **kwargs) -> ValueStreamModel:
        """Not implemented - value streams are managed externally."""
        raise NotImplementedError("Value streams are read-only via this API")

    async def get_by_field(
        self, field_name: str, field_value: Any
    ) -> List[ValueStreamModel]:
        """Get value stream records by any field."""
        try:
            field = getattr(ValueStreamModel, field_name)
            stmt = select(ValueStreamModel).where(
                field == field_value,
                ValueStreamModel.value_stream_active == "yes",
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Error fetching by {field_name}: {e}")
            raise

    async def get_by_filter(self, filter_expression: Any) -> List[ValueStreamModel]:
        """Get value stream records by a filter expression."""
        try:
            stmt = select(ValueStreamModel).where(
                filter_expression,
                ValueStreamModel.value_stream_active == "yes",
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Error fetching by filter: {e}")
            raise

    async def get_all(self) -> List[ValueStreamModel]:
        """Get all active value stream records."""
        try:
            stmt = select(ValueStreamModel).where(
                ValueStreamModel.value_stream_active == "yes"
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Error fetching all value streams: {e}")
            raise

    async def update(
        self, filter_expression: Any, **fields
    ) -> Optional[ValueStreamModel]:
        """Not implemented - value streams are managed externally."""
        raise NotImplementedError("Value streams are read-only via this API")

    async def delete(self, field_name: str, field_value: Any) -> bool:
        """Not implemented - value streams are managed externally."""
        raise NotImplementedError("Value streams are read-only via this API")
