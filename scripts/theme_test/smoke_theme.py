"""Manual smoke test for theme generation — FOR TESTING ONLY.

Wires the ThemeGenerationHandler with a fake catalogue reader and (by default) a fake platform
client, so the full generate-theme pipeline runs end to end with no DB and no LLM. Pass --real-llm to
use the prod PlatformRestClient, configured from the app's existing settings in .env
(CORE_PLATFORM_ENDPOINT / VERIFY_SSL / APP_ID) plus PLATFORM_AUTH_TOKEN (the bearer from
`python -m scripts.print_token` in the teg repo).

The ticket raw text fed to generation comes from scripts/theme_test/raw_text.txt (edit it to test a
real ticket); --raw-text-file points elsewhere. --coverage scores the generated themes against the
raw text via CoverageAnalysisService.

Run from the repo root:
    python scripts/theme_test/smoke_theme.py
    python scripts/theme_test/smoke_theme.py --real-llm
    python scripts/theme_test/smoke_theme.py --real-db --real-llm
    python scripts/theme_test/smoke_theme.py --real-db --real-llm --coverage
"""

from __future__ import annotations

import os
import sys

# Put this folder (worklet_data_api stub) and the repo root (jwg_app) on the path BEFORE importing
# the handler, so `from worklet_data_api import Worklet` resolves to the stub.
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
for _p in (HERE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import argparse  # noqa: E402
import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any, Dict, List, Optional, Sequence, Tuple  # noqa: E402

from worklet_data_api import Worklet  # noqa: E402  (stub)

from jwg_app.domain.models.base import Property  # noqa: E402
from jwg_app.domain.models.theme_generation import (  # noqa: E402
    L3Capability,
    ValueStage,
    ValueStreamAttributes,
    ValueStreamCatalogue,
)
from jwg_app.domain.services.theme import output_resolver as resolver  # noqa: E402
from jwg_app.domain.services.theme import worklet_mapper as mapper  # noqa: E402
from jwg_app.domain.services.theme_generation_handler import (  # noqa: E402
    ThemeGenerationHandler,
)

CONFIG_PATH = os.path.join(ROOT, "configs", "user_config.yaml")
TICKET_ID = "IDMT-19761"
RAW_TEXT_FILE = os.path.join(HERE, "raw_text.txt")  # the ticket raw text fed to generation
DEFAULT_RAW_TEXT = (
    "The business needs a faster way to procure approved physical assets (order management and "
    "vendor contract negotiation) and to streamline claims adjudication and pricing for members "
    "and providers in the new fiscal year."
)

# Multiple approved value streams -> exercises the batched stage/capability calls, the per-VS
# parallel business-needs, and the resolver's cross-VS reassignment. Use real VSR ids for --real-db.
VALUE_STREAMS = [
    ("VSR00074583", "Procurement Management", "Manage end-to-end procurement of physical assets."),
    ("VSR00074584", "Claims Adjudication", "Adjudicate and price member and provider claims."),
]


# --- fakes ---------------------------------------------------------------------------------

class FakeCatalogueReader:
    """Returns a canned ValueStreamCatalogue per VS (no DB)."""

    async def fetch_theme_inputs(self, vs_ids: Sequence[str]) -> Dict[str, ValueStreamCatalogue]:
        out: Dict[str, ValueStreamCatalogue] = {}
        for vs_id in vs_ids:
            name = next((n for v, n, _ in VALUE_STREAMS if v == vs_id), vs_id)
            description = next((d for v, _, d in VALUE_STREAMS if v == vs_id), "")
            out[vs_id] = ValueStreamCatalogue(
                value_stream=ValueStreamAttributes(
                    name=name,
                    description=description,
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


class _DebugPlatform:
    """Wraps any platform client and prints each agenerate request + raw (data, error, status)."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def agenerate(
        self,
        message: List[Dict[str, str]],
        model_params: Optional[Dict[str, Any]] = None,
        output_function: Optional[type] = None,
        **kwargs: Any,
    ) -> Tuple[Optional[Any], Optional[str], int]:
        schema = output_function.__name__ if output_function else "?"
        user = message[-1]["content"] if message else ""
        print(f"\n>>> agenerate [{schema}] | model_params={model_params}")
        print(f">>> user message ({len(user)} chars), first 400:\n{user[:400]}")
        data, error, status = await self._inner.agenerate(
            message=message, model_params=model_params, output_function=output_function, **kwargs
        )
        print(f"<<< status={status} error={error!r}")
        print(f"<<< data (first 600): {str(data)[:600]!r}")
        return data, error, status

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


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


def _load_raw_text(path: str) -> str:
    """Read the ticket raw text from a file; fall back to the built-in sample if absent/empty."""
    p = Path(path)
    if p.is_file():
        text = p.read_text(encoding="utf-8").strip()
        if text:
            print(f"# raw text from {path} ({len(text)} chars)")
            return text
    print(f"# raw text file not found/empty ({path}); using built-in sample")
    return DEFAULT_RAW_TEXT


def build_er_worklet(raw_text: str) -> Worklet:
    return Worklet(
        id=TICKET_ID,
        source_id=TICKET_ID,
        properties=[
            _prop("title", "New physical asset procurement initiative"),
            _prop("rawText", raw_text),
        ],
    )


def build_vs_worklets() -> List[Worklet]:
    # The worklet supplies only the id; name/description come from the catalogue.
    return [Worklet(source_id=vs_id, properties=[]) for vs_id, _, _ in VALUE_STREAMS]


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


def _register_bundled_nltk_data() -> None:
    """Point NLTK at the repo's bundled nltk_data so the evaluator finds stopwords/punkt."""
    bundled = os.path.join(ROOT, "nltk_data")
    if os.path.isdir(bundled):
        try:
            import nltk

            if bundled not in nltk.data.path:
                nltk.data.path.insert(0, bundled)
        except ImportError:
            pass


def _run_coverage(raw_text: str, themes: List[Worklet]) -> None:
    """Run coverage analysis on the generated theme worklets against the raw ticket text."""
    from jwg_app.domain.services.coverage_analysis import CoverageAnalysisService

    _register_bundled_nltk_data()
    service = CoverageAnalysisService()
    dataset = service.build_dataset(raw_text=raw_text, themes=themes)
    print("\n" + "=" * 80)
    print(f"# coverage analysis: {len(dataset['generated_text'])} theme(s) scored vs raw text "
          f"({len(raw_text)} chars)")
    try:
        result = service.analyze(raw_text=raw_text, themes=themes)
    except RuntimeError as exc:
        # The n-gram evaluator (text_evaluation) is a prod dependency; print the dataset instead.
        print(f"# evaluator unavailable: {exc}")
        print("# dataset that WOULD be scored:")
        print(json.dumps(dataset, indent=2, default=str)[:1500])
        return

    # The serialized worklet "analysis" property - exactly what the API would return on the ER.
    analysis = service.analysis_property(result)
    for metric in analysis["propertyValue"]:
        name = metric.get("metric_name")
        value = metric.get("metric_value", {})
        print(f"\n--- {name} ---  score={value.get('score')}", end="")
        if "scores" in value:
            print(f"  per-theme={value.get('scores')}", end="")
        print()
    print("\n# full analysis property:")
    print(json.dumps(analysis, indent=2))


def _build_real_platform():
    """Build the prod PlatformRestClient from the app's existing platform settings (read from .env).

    Reads CORE_PLATFORM_ENDPOINT / VERIFY_SSL / APP_ID (same names as the prod Settings) plus
    PLATFORM_AUTH_TOKEN (the bearer from scripts.print_token). A minimal reader is used so the full
    Settings validation (Cosmos/Jira/...) is not required just to test.
    """
    from pydantic_settings import BaseSettings, SettingsConfigDict

    from jwg_app.infrastructure.external.platform_rest_client import PlatformRestClient

    class _PlatformSettings(BaseSettings):
        model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=True)

        CORE_PLATFORM_ENDPOINT: str = ""
        VERIFY_SSL: bool = False
        APP_ID: str = "APP00236755"  # same default as the prod Settings
        PLATFORM_AUTH_TOKEN: str = ""  # bearer from `python -m scripts.print_token` (teg)

    cfg = _PlatformSettings()
    # agenerate/generate append "api/v1/..." with no separator, so base_url must end with "/".
    base_url = (cfg.CORE_PLATFORM_ENDPOINT.rstrip("/") + "/") if cfg.CORE_PLATFORM_ENDPOINT else ""
    return PlatformRestClient(
        base_url=base_url,
        auth_token=cfg.PLATFORM_AUTH_TOKEN,
        verify_ssl=cfg.VERIFY_SSL,
        app_id=cfg.APP_ID,
    )


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
    if args.debug:
        logging.basicConfig(
            level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
        )

    if args.real_llm:
        platform = _build_real_platform()
        print("# using REAL platform client (PlatformRestClient, config from .env)")
    else:
        platform = FakePlatformClient()
        print("# using FAKE platform client (no LLM)")

    if args.debug:
        platform = _DebugPlatform(platform)

    raw_text = _load_raw_text(args.raw_text_file)
    er_worklet, vs_worklets = build_er_worklet(raw_text), build_vs_worklets()
    vs_ids = [mapper.value_stream_id(w) for w in vs_worklets]
    print(f"# {len(vs_worklets)} value stream(s): {vs_ids} | only={args.only}")

    try:
        catalogue = await _fetch_catalogue(args, vs_ids)
        handler = ThemeGenerationHandler(_StaticCatalogue(catalogue), platform, CONFIG_PATH)
        if args.only == "all":
            themes = await handler.run(er_worklet, vs_worklets)
            _print_themes(themes)
            if args.coverage:
                _run_coverage(raw_text, themes)
        else:
            await _run_only(handler, args.only, er_worklet, vs_worklets, catalogue)
    finally:
        if hasattr(platform, "aclose"):
            await platform.aclose()
        if args.real_db:
            try:
                from db_session import dispose

                await dispose()
            except ImportError:
                pass  # older db_session without dispose(); engine closes on process exit


class _StaticCatalogue:
    """Returns an already-fetched catalogue dict, so each generator can run without re-hitting the DB."""

    def __init__(self, data):
        self._data = data

    async def fetch_theme_inputs(self, vs_ids):
        return {i: self._data.get(i, ValueStreamCatalogue()) for i in vs_ids}


async def _fetch_catalogue(args, vs_ids):
    if args.real_db:
        from db_session import session_scope

        print("# fetching catalogue from Azure SQL (ThemeService)")
        async with session_scope() as session:
            return await _build_real_service(session).fetch_theme_inputs(vs_ids)
    print("# using FAKE catalogue (no DB)")
    return await FakeCatalogueReader().fetch_theme_inputs(vs_ids)


async def _run_only(handler, only, er_worklet, vs_worklets, catalogue):
    """Run one generator (batched, as in the real pipeline) and print its output per value stream."""
    er = mapper.to_er_context(er_worklet)
    vs_ids = [mapper.value_stream_id(w) for w in vs_worklets]
    vs_list = [mapper.to_vs_context(w, catalogue.get(vid, ValueStreamCatalogue())) for w, vid in zip(vs_worklets, vs_ids)]

    # Compute the requested generator once (same calls the pipeline makes), then display per VS.
    stages_by_vs, body, framings, needs_by_vs, l3_by_stage = {}, "", {}, {}, {}
    if only in ("stages", "needs", "caps"):
        stages_by_vs = await handler._stage_selection(er, vs_list, catalogue)
    if only == "description":
        body = await handler._description_body(er)
        framings = await handler._description_framings(er, vs_list)
    if only == "needs":
        async def needs_for_vs(vs):
            return vs.vs_id, await handler._business_needs_for_vs(
                er, vs, stages_by_vs.get(vs.vs_id, [])
            )

        needs_by_vs = dict(await asyncio.gather(*(needs_for_vs(vs) for vs in vs_list)))
    if only == "caps":
        l3_by_stage = await handler._capability_selection(er, vs_list, stages_by_vs, catalogue)

    for vs in vs_list:
        print("\n" + "=" * 80)
        print(f"{vs.vs_name} ({vs.vs_id}) -- {only.upper()}")
        print("-" * 80)
        if only == "stages":
            for s in stages_by_vs.get(vs.vs_id, []):
                print(f"  [{s.stage_id}] {s.stage_name}" + (f" - {s.reason}" if s.reason else ""))
        elif only == "description":
            print(handler._theme_description(framings.get(vs.vs_id, ""), body))
        elif only == "needs":
            print(needs_by_vs.get(vs.vs_id, "") or "(none)")
        elif only == "caps":
            l3 = [c for s in stages_by_vs.get(vs.vs_id, []) for c in l3_by_stage.get(s.stage_id, [])]
            print("L3:")
            for c in l3:
                print(f"  [{c.id}] {c.name}  (stage {c.stage_id}) -> L2 [{c.level_two_id}] {c.level_two_name}")
            print("L2 (derived):")
            for c in resolver.derive_l2(l3):
                print(f"  [{c.id}] {c.name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--real-llm", action="store_true", help="use prod PlatformRestClient (needs PLATFORM_* env)")
    parser.add_argument("--real-db", action="store_true", help="use real ThemeService over Azure SQL (needs env + aioodbc)")
    parser.add_argument("--debug", action="store_true", help="DEBUG logging + print each agenerate request/response")
    parser.add_argument(
        "--only",
        choices=["all", "stages", "description", "needs", "caps"],
        default="all",
        help="generate just one part in isolation (to show a reviewer each output)",
    )
    parser.add_argument("--raw-text-file", default=RAW_TEXT_FILE,
                        help="file holding the ticket raw text fed to generation (default raw_text.txt)")
    parser.add_argument("--coverage", action="store_true",
                        help="run coverage analysis on the generated themes (only with --only all)")
    main_args = parser.parse_args()
    asyncio.run(main(main_args))
