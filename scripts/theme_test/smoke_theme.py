"""Manual smoke test for theme generation — FOR TESTING ONLY.

Wires the ThemeGenerationHandler with a fake catalogue reader and (by default) a fake platform
client, so the full generate-theme pipeline runs end to end with no DB and no LLM. Pass --real-llm to
hit the real IDP gateway (set the LLM_/IDP_ env vars first; see platform_client.build_platform_client).

Run from the repo root:
    python scripts/theme_test/smoke_theme.py
    python scripts/theme_test/smoke_theme.py --real-llm
"""

from __future__ import annotations

import os
import sys

# Put this folder (worklet_data_api stub, platform_client, idp_auth) and the repo root (jwg_app) on
# the path BEFORE importing the handler, so `from worklet_data_api import Worklet` resolves to the stub.
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
for _p in (HERE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import argparse  # noqa: E402
import asyncio  # noqa: E402
from typing import Any, Dict, List, Optional, Sequence, Tuple  # noqa: E402

from worklet_data_api import Worklet  # noqa: E402  (stub)

from jwg_app.domain.models.base import Property  # noqa: E402
from jwg_app.domain.models.theme_generation import (  # noqa: E402
    L3Capability,
    ValueStage,
    ValueStreamAttributes,
    ValueStreamCatalogue,
)
from jwg_app.domain.services.theme import worklet_mapper as mapper  # noqa: E402
from jwg_app.domain.services.theme_generation_handler import (  # noqa: E402
    ThemeGenerationHandler,
)

CONFIG_PATH = os.path.join(ROOT, "configs", "user_config.yaml")
TICKET_ID = "IDMT-19761"
VS_ID = "VSR00074583"
VS_NAME = "Procurement Management"


# --- fakes ---------------------------------------------------------------------------------

class FakeCatalogueReader:
    """Returns a canned ValueStreamCatalogue per VS (no DB)."""

    async def fetch_theme_inputs(self, vs_ids: Sequence[str]) -> Dict[str, ValueStreamCatalogue]:
        out: Dict[str, ValueStreamCatalogue] = {}
        for vs_id in vs_ids:
            out[vs_id] = ValueStreamCatalogue(
                value_stream=ValueStreamAttributes(
                    value_proposition="Faster, compliant procurement of physical assets.",
                    trigger="A business unit raises a need for a new physical asset.",
                ),
                stage_list=[
                    ValueStage(
                        stage_id="VSS00074676",
                        stage_name="Physical Asset Order Management",
                        stage_description="Place and manage orders for approved physical assets.",
                        entrance_criteria="Approved asset request exists.",
                        exit_criteria="Order placed with the vendor.",
                    ),
                    ValueStage(
                        stage_id="VSS00074677",
                        stage_name="Contract Negotiation Support",
                        stage_description="Support negotiation of vendor contracts.",
                        entrance_criteria="Shortlisted vendors identified.",
                        exit_criteria="Contract terms agreed.",
                    ),
                ],
                l3_capabilities=[
                    L3Capability(
                        id="CAP00000588",
                        name="Physical Asset Order Management",
                        description="Manage the lifecycle of a physical asset order.",
                        stage_id="VSS00074676",
                        level_two_id="CAP00000089",
                        level_two_name="Physical Asset Acquisition",
                    ),
                    L3Capability(
                        id="CAP00000629",
                        name="Contract Negotiation Support",
                        description="Support contract negotiation activities.",
                        stage_id="VSS00074677",
                        level_two_id="CAP00000086",
                        level_two_name="Procurement Management",
                    ),
                ],
            )
        return out


class FakePlatformClient:
    """Returns canned structured output per schema, so the pipeline runs without an LLM."""

    async def agenerate(
        self,
        message: List[Dict[str, str]],
        model_params: Optional[Dict[str, Any]] = None,
        output_function: Optional[type] = None,
        **kwargs: Any,
    ) -> Tuple[Optional[Any], Optional[str], int]:
        name = output_function.__name__ if output_function else ""
        if name == "TextOut":
            return {"text": "[fake] Generated narrative text for testing."}, None, 200
        if name == "FramingsOut":
            return {"framings": []}, None, 200
        if name == "BatchedStageSelection":
            return {"value_streams": []}, None, 200  # empty -> resolver falls back to all stages
        if name == "BatchedCapabilitySelection":
            return {"stages": []}, None, 200
        return {}, None, 200


# --- worklet builders ----------------------------------------------------------------------

def _prop(name: str, value: Any) -> Property:
    return Property(property_name=name, property_value=value)


def build_er_worklet() -> Worklet:
    return Worklet(
        id=TICKET_ID,
        source_id=TICKET_ID,
        properties=[
            _prop("title", "New physical asset procurement initiative"),
            _prop(
                "rawText",
                "The business needs a faster way to procure approved physical assets, including "
                "order management and vendor contract negotiation for the new fiscal year.",
            ),
            _prop("Docs Summary", {}),
        ],
    )


def build_vs_worklet() -> Worklet:
    return Worklet(
        source_id=VS_ID,
        properties=[
            _prop("title", VS_NAME),
            _prop("valueStreamDescription", "Manage end-to-end procurement of physical assets."),
        ],
    )


# --- run -----------------------------------------------------------------------------------

def _print_themes(themes: List[Worklet]) -> None:
    print(f"\n# generated {len(themes)} theme worklet(s)\n" + "=" * 80)
    for theme in themes:
        title = mapper.get_property(theme, mapper.ThemeProps.TITLE, "")
        description = mapper.get_property(theme, mapper.ThemeProps.DESCRIPTION, "")
        needs = mapper.get_property(theme, mapper.ThemeProps.BUSINESS_NEEDS, "")
        stages = mapper.get_property(theme, mapper.ThemeProps.SELECTED_STAGES, []) or []
        l3 = mapper.get_property(theme, mapper.ThemeProps.L3, []) or []
        l2 = mapper.get_property(theme, mapper.ThemeProps.L2, []) or []
        print(f"TITLE: {title}")
        print(f"DESCRIPTION:\n{description}\n")
        print(f"BUSINESS NEEDS:\n{needs}\n")
        print(f"SELECTED STAGES: {len(stages)} | L3: {len(l3)} | L2: {len(l2)}")
        print("=" * 80)


def _build_real_service(session):
    from jwg_app.domain.services.theme_service import ThemeService
    from jwg_app.infrastructure.repositories import (
        L2CapabilityRepository,
        L3CapabilityRepository,
        ValueStreamCapabilityRepository,
        ValueStreamRepository,
        ValueStreamStageRepository,
    )

    return ThemeService(
        value_stream_repository=ValueStreamRepository(session),
        stage_repository=ValueStreamStageRepository(session),
        capability_repository=ValueStreamCapabilityRepository(session),
        l3_repository=L3CapabilityRepository(session),
        l2_repository=L2CapabilityRepository(session),
    )


async def main(args: argparse.Namespace) -> None:
    if args.real_llm:
        from platform_client import build_platform_client

        platform = build_platform_client()
        print("# using REAL platform client (IDP gateway)")
    else:
        platform = FakePlatformClient()
        print("# using FAKE platform client (no LLM)")

    er, vs = build_er_worklet(), build_vs_worklet()
    try:
        if args.real_db:
            from db_session import build_async_session_factory

            print("# using REAL catalogue (Azure SQL via ThemeService)")
            async with build_async_session_factory()() as session:
                handler = ThemeGenerationHandler(_build_real_service(session), platform, CONFIG_PATH)
                themes = await handler.run(er, [vs])
        else:
            print("# using FAKE catalogue (no DB)")
            handler = ThemeGenerationHandler(FakeCatalogueReader(), platform, CONFIG_PATH)
            themes = await handler.run(er, [vs])
        _print_themes(themes)
    finally:
        if hasattr(platform, "aclose"):
            await platform.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--real-llm", action="store_true", help="hit the real IDP gateway (needs env)")
    parser.add_argument("--real-db", action="store_true", help="use real ThemeService over Azure SQL (needs env + aioodbc)")
    main_args = parser.parse_args()
    asyncio.run(main(main_args))
