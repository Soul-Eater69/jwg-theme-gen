"""
Abstraction for the catalogue read the handler depends on.

Theme generation reads, for all approved value streams at once, each value stream's attributes
(value proposition, trigger), its candidate stages, and its full L3 list (with each L3's parent L2
inline), sourced from the ``vs -> vss -> l3`` and ``l3 -> l2 -> l1`` tables. The concrete Azure SQL
client implements this protocol; tests inject a fake.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from jwg_app.domain.models.theme_generation import ValueStreamCatalogue


class ThemeCatalogueReader(Protocol):
    async def fetch_theme_inputs(self, vs_ids: Sequence[str]) -> dict[str, ValueStreamCatalogue]:
        """
        Read the catalogue for every approved value stream in one batched call.

        Args:
            vs_ids: The approved value-stream ids to read.

        Returns:
            The catalogue record for each value stream, keyed by value-stream id.
        """
        ...
