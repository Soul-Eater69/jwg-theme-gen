"""Service layer that assembles the value-stream catalogue for theme generation.

Reads, for each approved value stream, its catalogue - attributes, candidate stages, and L3
capabilities (each carrying its parent L2 name) - in a SINGLE projected join across the value
stream, the stage<->capability mapping, the stage table, and the L3/L2 capability tables. Only the
columns theme generation uses are selected, and only active rows. This is the concrete
ThemeCatalogueReader the theme generation handler depends on.

A stage and an L3 are tied to a value stream only through the mapping table; the mapping's
capability_id is an L3 id, and L2 is reached via L3.parent_capability_id.
"""

import logging
from typing import Dict, List, Sequence

from sqlalchemy import Select, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from jwg_app.domain.models.theme_generation import (
    L3Capability,
    ValueStage,
    ValueStreamAttributes,
    ValueStreamCatalogue,
)
from jwg_app.infrastructure.database.models import (
    L2CapabilityModel,
    L3CapabilityModel,
    ValueStreamCapabilityModel,
    ValueStreamModel,
    ValueStreamStageModel,
)

logger = logging.getLogger(__name__)

_ACTIVE = "yes"


class ThemeService:
    """Assembles the theme-generation catalogue for approved value streams in one joined read."""

    def __init__(self, session: AsyncSession):
        """Initialize with the database session the catalogue join runs on.

        Args:
            session: SQLAlchemy async session.
        """
        self.session = session

    async def fetch_theme_inputs(
        self, vs_ids: Sequence[str]
    ) -> Dict[str, ValueStreamCatalogue]:
        """Read the catalogue for every approved value stream in one joined, projected query.

        Args:
            vs_ids: The approved value-stream ids to read.

        Returns:
            The catalogue read for each value stream, keyed by value-stream id. Every requested id
            gets an entry; a missing/inactive value stream yields empty attributes and lists.
        """
        ids = list(dict.fromkeys(vs_ids))  # dedupe, preserve order
        if not ids:
            return {}

        rows = (await self.session.execute(self._catalogue_query(ids))).all()

        catalogue: Dict[str, ValueStreamCatalogue] = {}
        stage_seen: Dict[str, set] = {}
        l3_seen: Dict[str, set] = {}
        for r in rows:
            cat = catalogue.get(r.vs_id)
            if cat is None:
                cat = ValueStreamCatalogue(
                    value_stream=ValueStreamAttributes(
                        name=r.vs_name or "",
                        description=r.vs_description or "",
                        value_proposition=r.vs_value_proposition or "",
                        trigger=r.vs_trigger or "",
                    )
                )
                catalogue[r.vs_id] = cat
                stage_seen[r.vs_id] = set()
                l3_seen[r.vs_id] = set()

            # Distinct candidate stages: only stages that matched an active stage row.
            if r.stage_id and r.stage_id not in stage_seen[r.vs_id]:
                stage_seen[r.vs_id].add(r.stage_id)
                cat.stage_list.append(
                    ValueStage(
                        stage_id=r.stage_id,
                        stage_name=r.stage_name or "",
                        stage_description=r.stage_description or "",
                        entrance_criteria=r.stage_entrance or "",
                        exit_criteria=r.stage_exit or "",
                    )
                )

            # One L3 per (mapping stage, capability), tied to the mapping's stage id.
            if r.l3_id and r.map_stage_id:
                key = (r.map_stage_id, r.l3_id)
                if key not in l3_seen[r.vs_id]:
                    l3_seen[r.vs_id].add(key)
                    cat.l3_capabilities.append(
                        L3Capability(
                            id=r.l3_id,
                            name=r.l3_name or "",
                            description=r.l3_description or "",
                            stage_id=r.map_stage_id,
                            level_two_id=r.level_two_id or "",
                            level_two_name=r.level_two_name or "",
                        )
                    )

        # Every requested id gets an entry, even if missing/inactive (empty attributes + lists).
        present = {r.vs_id for r in rows}
        for vs_id in ids:
            catalogue.setdefault(vs_id, ValueStreamCatalogue())
        missing = [i for i in ids if i not in present]
        if missing:
            logger.info(f"Catalogue: {len(missing)} value stream(s) not found/inactive: {missing}")
        return catalogue

    @staticmethod
    def _catalogue_query(ids: List[str]) -> Select:
        """One projected join: value stream -> mapping -> stage + L3 (+ parent L2), active rows only.

        Outer joins from the value stream out, so an approved value stream with no (or only inactive)
        mappings still returns - its stage/L3 columns come back null and become empty lists. Only the
        columns theme generation uses are selected.
        """
        return (
            select(
                ValueStreamModel.value_stream_id.label("vs_id"),
                ValueStreamModel.value_stream_name.label("vs_name"),
                ValueStreamModel.value_stream_description.label("vs_description"),
                ValueStreamModel.value_stream_value_proposition.label("vs_value_proposition"),
                ValueStreamModel.value_stream_trigger.label("vs_trigger"),
                ValueStreamCapabilityModel.value_stream_stage_id.label("map_stage_id"),
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
