"""Service layer that assembles the value-stream catalogue for theme generation.

Coordinates the value stream, stage, mapping, and L3/L2 repositories to build, for each approved
value stream, its catalogue read: its attributes, its candidate stages, and its L3 capabilities
(each carrying its parent L2). A stage and an L3 are tied to a value stream through the mapping
table; the mapping's capability_id is an L3 id, and L2 is reached via L3.parent_capability_id.

This is the concrete ThemeCatalogueReader the theme generation handler depends on.
"""

import logging
from typing import Dict, List, Sequence

from jwg_app.domain.models.theme_generation import (
    L3Capability,
    ValueStage,
    ValueStreamAttributes,
    ValueStreamCatalogue,
)
from jwg_app.infrastructure.database.models import (
    ValueStreamCapabilityModel,
    ValueStreamStageModel,
)
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


class ThemeCatalogueService:
    """Service layer that assembles the theme-generation catalogue for approved value streams."""

    def __init__(
        self,
        value_stream_repository: ValueStreamRepository,
        stage_repository: ValueStreamStageRepository,
        capability_repository: ValueStreamCapabilityRepository,
        l3_repository: L3CapabilityRepository,
        l2_repository: L2CapabilityRepository,
    ):
        """Initialize the service with the catalogue repositories.

        Args:
            value_stream_repository: Value stream attributes.
            stage_repository: Value stream stages.
            capability_repository: Value stream <-> stage <-> capability mapping.
            l3_repository: L3 capabilities.
            l2_repository: L2 capabilities (for each L3's parent name).
        """
        self.value_stream_repository = value_stream_repository
        self.stage_repository = stage_repository
        self.capability_repository = capability_repository
        self.l3_repository = l3_repository
        self.l2_repository = l2_repository

    async def fetch_theme_inputs(
        self, vs_ids: Sequence[str]
    ) -> Dict[str, ValueStreamCatalogue]:
        """Read the catalogue for every approved value stream in one batched pass.

        Args:
            vs_ids: The approved value-stream ids to read.

        Returns:
            The catalogue read for each value stream, keyed by value-stream id.
        """
        ids = list(dict.fromkeys(vs_ids))  # dedupe, preserve order
        if not ids:
            return {}

        # Value stream attributes.
        found, missing = await self.value_stream_repository.get_by_ids(ids)
        if missing:
            logger.info(f"Catalogue: {len(missing)} value stream(s) not found/inactive: {missing}")
        attributes_by_vs = {
            r.value_stream_id: ValueStreamAttributes(
                value_proposition=r.value_stream_value_proposition or "",
                trigger=r.value_stream_trigger or "",
            )
            for r in found
        }

        # Mapping rows link each value stream to its stages and L3 capabilities.
        mappings = await self.capability_repository.get_by_value_stream_ids(ids)

        # Stages referenced by the mappings.
        stage_ids = [m.value_stream_stage_id for m in mappings if m.value_stream_stage_id]
        stages = await self.stage_repository.get_by_ids(stage_ids)
        stage_by_id = {s.value_stream_stage_id: s for s in stages}

        # L3 capabilities referenced by the mappings (capability_id is an L3 id).
        l3_ids = [m.capability_id for m in mappings if m.capability_id]
        l3_records = await self.l3_repository.get_by_ids(l3_ids)
        l3_by_id = {c.l3_capability_id: c for c in l3_records}

        # L2 names for each L3's parent.
        l2_ids = [c.parent_capability_id for c in l3_records if c.parent_capability_id]
        l2_records = await self.l2_repository.get_by_ids(l2_ids)
        l2_name_by_id = {c.l2_capability_id: (c.capability_name or "") for c in l2_records}

        catalogue: Dict[str, ValueStreamCatalogue] = {}
        for vs_id in ids:
            vs_mappings = [m for m in mappings if m.value_stream_id == vs_id]
            catalogue[vs_id] = ValueStreamCatalogue(
                value_stream=attributes_by_vs.get(vs_id, ValueStreamAttributes()),
                stage_list=self._stages_for(vs_mappings, stage_by_id),
                l3_capabilities=self._l3_for(vs_mappings, l3_by_id, l2_name_by_id),
            )
        return catalogue

    def _stages_for(
        self,
        mappings: List[ValueStreamCapabilityModel],
        stage_by_id: Dict[str, ValueStreamStageModel],
    ) -> List[ValueStage]:
        """The distinct candidate stages for one value stream, in mapping order."""
        stages: List[ValueStage] = []
        seen = set()
        for mapping in mappings:
            stage_id = mapping.value_stream_stage_id
            if not stage_id or stage_id in seen:
                continue
            stage = stage_by_id.get(stage_id)
            if stage is None:
                continue
            seen.add(stage_id)
            stages.append(
                ValueStage(
                    stage_id=stage.value_stream_stage_id,
                    stage_name=stage.value_stream_stage_name or "",
                    stage_description=stage.value_stream_stage_description or "",
                    entrance_criteria=stage.value_stream_stage_entrance_criteria or "",
                    exit_criteria=stage.value_stream_stage_exit_criteria or "",
                )
            )
        return stages

    def _l3_for(
        self,
        mappings: List[ValueStreamCapabilityModel],
        l3_by_id: Dict[str, object],
        l2_name_by_id: Dict[str, str],
    ) -> List[L3Capability]:
        """The L3 capabilities for one value stream, one per (stage, capability) mapping."""
        capabilities: List[L3Capability] = []
        seen = set()
        for mapping in mappings:
            stage_id = mapping.value_stream_stage_id
            capability_id = mapping.capability_id
            if not stage_id or not capability_id:
                continue
            key = (stage_id, capability_id)
            if key in seen:
                continue
            l3 = l3_by_id.get(capability_id)
            if l3 is None:
                continue
            seen.add(key)
            capabilities.append(
                L3Capability(
                    id=l3.l3_capability_id,
                    name=l3.capability_name or "",
                    description=l3.capability_description or "",
                    stage_id=stage_id,
                    level_two_id=l3.parent_capability_id or "",
                    level_two_name=l2_name_by_id.get(l3.parent_capability_id, ""),
                )
            )
        return capabilities
