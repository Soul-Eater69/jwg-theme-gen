"""Read repository for the value-stream catalogue used by theme generation.

Reads the catalogue for the approved value streams in a SINGLE projected join across the value
stream, the stage<->capability mapping, the stage table, and the L3/L2 capability tables - only the
columns theme generation uses, and only active rows. Returns the joined rows; ThemeService maps them
into the domain catalogue. This is a cross-table read (a query repository), not single-table CRUD.
"""

import logging
from typing import List, Sequence

from sqlalchemy import Row, Select, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from jwg_app.infrastructure.database.models import (
    L2CapabilityModel,
    L3CapabilityModel,
    ValueStreamCapabilityModel,
    ValueStreamModel,
    ValueStreamStageModel,
)

logger = logging.getLogger(__name__)

_ACTIVE = "yes"


class ValueStreamCatalogueRepository:
    """Reads the theme-generation catalogue for approved value streams in one joined query."""

    def __init__(self, session: AsyncSession):
        """Initialize with the database session the join runs on.

        Args:
            session: SQLAlchemy async session.
        """
        self.session = session

    async def get_catalogue_rows(self, value_stream_ids: Sequence[str]) -> List[Row]:
        """Read the joined catalogue rows for the given value streams.

        Args:
            value_stream_ids: The approved value-stream ids to read.

        Returns:
            One row per value-stream x active stage x active capability; each row exposes the labelled
            columns the catalogue assembly reads (vs_*, stage_*, l3_*, level_two_*). A value stream
            with no/inactive mappings still returns one row (stage/L3 columns null).
        """
        ids = list(dict.fromkeys(value_stream_ids))
        if not ids:
            return []
        try:
            result = await self.session.execute(self._query(ids))
            return result.all()
        except Exception:
            logger.exception("Error reading value-stream catalogue")
            raise

    @staticmethod
    def _query(ids: List[str]) -> Select:
        """One projected join: value stream -> mapping -> stage + L3 (+ parent L2), active rows only.

        Outer joins from the value stream out, so an approved value stream with no (or only inactive)
        mappings still returns - its stage/L3 columns come back null. Only the columns theme
        generation uses are selected.
        """
        return (
            select(
                ValueStreamModel.value_stream_id.label("vs_id"),
                ValueStreamModel.value_stream_name.label("vs_name"),
                ValueStreamModel.value_stream_description.label("vs_description"),
                ValueStreamModel.value_stream_value_proposition.label("vs_value_proposition"),
                ValueStreamModel.value_stream_trigger.label("vs_trigger"),
                ValueStreamStageModel.value_stream_stage_id.label("stage_id"),
                ValueStreamStageModel.value_stream_stage_name.label("stage_name"),
                ValueStreamStageModel.value_stream_stage_description.label("stage_description"),
                ValueStreamStageModel.value_stream_stage_entrance_criteria.label("stage_entrance"),
                ValueStreamStageModel.value_stream_stage_exit_criteria.label("stage_exit"),
                L3CapabilityModel.l3_capability_id.label("l3_id"),
                L3CapabilityModel.capability_name.label("l3_name"),
                L3CapabilityModel.capability_description.label("l3_description"),
                L3CapabilityModel.parent_capability_id.label("level_two_id"),
                L2CapabilityModel.capability_name.label("level_two_name"),
            )
            .select_from(ValueStreamModel)
            .outerjoin(
                ValueStreamCapabilityModel,
                ValueStreamCapabilityModel.value_stream_id == ValueStreamModel.value_stream_id,
            )
            .outerjoin(
                ValueStreamStageModel,
                and_(
                    ValueStreamStageModel.value_stream_stage_id
                    == ValueStreamCapabilityModel.value_stream_stage_id,
                    ValueStreamStageModel.value_stream_stage_active == _ACTIVE,
                ),
            )
            .outerjoin(
                L3CapabilityModel,
                and_(
                    L3CapabilityModel.l3_capability_id == ValueStreamCapabilityModel.capability_id,
                    L3CapabilityModel.capability_active == _ACTIVE,
                ),
            )
            .outerjoin(
                L2CapabilityModel,
                and_(
                    L2CapabilityModel.l2_capability_id == L3CapabilityModel.parent_capability_id,
                    L2CapabilityModel.capability_active == _ACTIVE,
                ),
            )
            .where(
                ValueStreamModel.value_stream_id.in_(ids),
                ValueStreamModel.value_stream_active == _ACTIVE,
            )
        )
