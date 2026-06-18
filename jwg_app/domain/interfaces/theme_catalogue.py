"""Abstraction for the governed-catalogue read the handler depends on (DIP).

Theme generation reads, for ALL approved Value Streams at once, each one's governed attributes
(value proposition, trigger), its candidate stages, and its full L3 list (each L3's
parent L2 inline) — sourced from the ``vs -> vss -> l3`` and ``l3 -> l2 -> l1`` tables. The
concrete Azure SQL client implements this; tests inject a fake.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from jwg_app.domain.models.theme_generation import AzureSQLData


class ThemeCatalogueReader(Protocol):
    async def fetch_theme_inputs(self, vs_ids: Sequence[str]) -> dict[str, AzureSQLData]:
        """One batched read for all approved Value Streams, keyed by ``vs_id``."""
        ...
