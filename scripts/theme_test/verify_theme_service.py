"""Verify the real ThemeService against Azure SQL — FOR TESTING ONLY.

Runs the production catalogue stack (ThemeService + the five repositories) against the live database
for one or more value stream ids, prints the assembled catalogue, and asserts the chain held
(attributes present, stages found, each L3 carries its L2 name). Use this to confirm the SQL layer
works before wiring the real service into the generation flow.

Setup: `pip install aioodbc`, then set the SQL_* env vars (see db_session.build_async_session_factory)
with the same values you used in verify_catalogue_schema.py.

Run from the repo root:
    python scripts/theme_test/verify_theme_service.py VSR00074583
    python scripts/theme_test/verify_theme_service.py VSR00074583 VSR00074584
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
for _p in (HERE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import argparse  # noqa: E402
import asyncio  # noqa: E402
from typing import List  # noqa: E402

from db_session import build_async_session_factory  # noqa: E402

from jwg_app.domain.services.theme_service import ThemeService  # noqa: E402
from jwg_app.infrastructure.repositories import (  # noqa: E402
    L2CapabilityRepository,
    L3CapabilityRepository,
    ValueStreamCapabilityRepository,
    ValueStreamRepository,
    ValueStreamStageRepository,
)


def build_service(session) -> ThemeService:
    return ThemeService(
        value_stream_repository=ValueStreamRepository(session),
        stage_repository=ValueStreamStageRepository(session),
        capability_repository=ValueStreamCapabilityRepository(session),
        l3_repository=L3CapabilityRepository(session),
        l2_repository=L2CapabilityRepository(session),
    )


async def main(vs_ids: List[str]) -> None:
    factory = build_async_session_factory()
    async with factory() as session:
        catalogue = await build_service(session).fetch_theme_inputs(vs_ids)

    failures = 0
    for vs_id in vs_ids:
        cat = catalogue.get(vs_id)
        print("\n" + "=" * 80)
        print(f"VALUE STREAM: {vs_id}")
        print("-" * 80)
        if cat is None:
            print("  FAIL: not present in catalogue result")
            failures += 1
            continue

        print(f"value proposition: {cat.value_stream.value_proposition!r}")
        print(f"trigger:           {cat.value_stream.trigger!r}")

        print(f"\nstages ({len(cat.stage_list)}):")
        for stage in cat.stage_list:
            print(f"  [{stage.stage_id}] {stage.stage_name}")
            print(f"      entrance: {stage.entrance_criteria!r}")
            print(f"      exit:     {stage.exit_criteria!r}")

        print(f"\nL3 capabilities ({len(cat.l3_capabilities)}):")
        for l3 in cat.l3_capabilities:
            print(
                f"  [{l3.id}] {l3.name}  (stage {l3.stage_id})  "
                f"-> L2 [{l3.level_two_id}] {l3.level_two_name}"
            )

        # Assertions: the chain held.
        if not cat.stage_list:
            print("  FAIL: no stages resolved for this value stream")
            failures += 1
        if not cat.l3_capabilities:
            print("  FAIL: no L3 capabilities resolved")
            failures += 1
        missing_l2 = [l3.id for l3 in cat.l3_capabilities if not l3.level_two_name]
        if missing_l2:
            print(f"  FAIL: {len(missing_l2)} L3(s) missing L2 name (L3->L2 join gap): {missing_l2[:5]}")
            failures += 1

    print("\n" + "=" * 80)
    print("RESULT:", "PASS" if failures == 0 else f"FAIL ({failures} issue(s))")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("vs_ids", nargs="+", help="approved value stream ids (e.g. VSR00074583)")
    args = parser.parse_args()
    asyncio.run(main(args.vs_ids))
