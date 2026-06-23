"""Service layer that assembles the value-stream catalogue for theme generation.

Maps the joined catalogue rows (read by ValueStreamCatalogueRepository in one query) into, for each
approved value stream, its catalogue: attributes, candidate stages, and L3 capabilities (each
carrying its parent L2 name). The repository owns the SQL/join; this service owns the grouping and
dedup. This is the concrete ThemeCatalogueReader the theme generation handler depends on.
"""

import logging
from typing import Dict, Sequence

from jwg_app.domain.models.theme_generation import (
    L3Capability,
    ValueStage,
    ValueStreamAttributes,
    ValueStreamCatalogue,
)
from jwg_app.infrastructure.repositories.value_stream_catalogue_repository import (
    ValueStreamCatalogueRepository,
)

logger = logging.getLogger(__name__)


class ThemeService:
    """Assembles the theme-generation catalogue for approved value streams from the joined rows."""

    def __init__(self, catalogue_repository: ValueStreamCatalogueRepository):
        """Initialize with the catalogue read repository.

        Args:
            catalogue_repository: Runs the single catalogue join and returns the rows.
        """
        self.catalogue_repository = catalogue_repository

    async def fetch_theme_inputs(
        self, vs_ids: Sequence[str]
    ) -> Dict[str, ValueStreamCatalogue]:
        """Read and assemble the catalogue for every approved value stream.

        Args:
            vs_ids: The approved value-stream ids to read.

        Returns:
            The catalogue read for each value stream, keyed by value-stream id. Every requested id
            gets an entry; a missing/inactive value stream yields empty attributes and lists.
        """
        ids = list(dict.fromkeys(vs_ids))  # dedupe, preserve order
        if not ids:
            return {}

        rows = await self.catalogue_repository.get_catalogue_rows(ids)

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

            # One L3 per (stage, capability), tied to its active stage. (L3 under an inactive stage
            # is dropped here - it can never be a candidate, since selected stages are active ones.)
            if r.l3_id and r.stage_id:
                key = (r.stage_id, r.l3_id)
                if key not in l3_seen[r.vs_id]:
                    l3_seen[r.vs_id].add(key)
                    cat.l3_capabilities.append(
                        L3Capability(
                            id=r.l3_id,
                            name=r.l3_name or "",
                            description=r.l3_description or "",
                            stage_id=r.stage_id,
                            level_two_id=r.level_two_id or "",
                            level_two_name=r.level_two_name or "",
                            level_two_description=r.level_two_description or "",
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
