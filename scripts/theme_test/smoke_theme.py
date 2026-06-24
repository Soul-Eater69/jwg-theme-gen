"""Manual smoke test for theme generation — FOR TESTING ONLY.

Runs the full ThemeGenerationHandler pipeline end to end against the real Azure SQL catalogue
(ThemeService) and the real prod PlatformRestClient (LLM) — there are no fakes. The value streams are
supplied as ids only (VALUE_STREAMS); every attribute (name, description, stages, capabilities) comes
from SQL.

Platform config is read from .env (CORE_PLATFORM_ENDPOINT / VERIFY_SSL / APP_ID) plus
PLATFORM_AUTH_TOKEN (the bearer from `python -m scripts.print_token` in the teg repo). DB config is
read from DB_* in .env (see db_session). Needs aioodbc + an ODBC driver for the DB.

The ticket raw text fed to generation comes from scripts/theme_test/raw_text.txt (edit it to test a
real ticket); --raw-text-file points elsewhere. --coverage scores the generated themes against the
raw text via CoverageAnalysisService.

Run from the repo root:
    python scripts/theme_test/smoke_theme.py
    python scripts/theme_test/smoke_theme.py --only stages
    python scripts/theme_test/smoke_theme.py --coverage
    python scripts/theme_test/smoke_theme.py --debug
"""

from __future__ import annotations

import os
import sys

# Put this folder (worklet_data_api stub) and the repo root (jwg_app) on the path BEFORE importing
# the handler, so `from worklet_data_api import Worklet` resolves to the stub.
HERE = os.path.dirname(os.path.abspath(__file__))


def _find_repo_root(start: str) -> str:
    """Walk up from ``start`` to the dir that holds ``configs/user_config.yaml`` (the repo root).

    Location-independent: works whether this script sits one or several folders under the repo root.
    Falls back to two-levels-up if nothing is found.
    """
    d = start
    for _ in range(8):
        if os.path.isfile(os.path.join(d, "configs", "user_config.yaml")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.abspath(os.path.join(start, "..", ".."))


ROOT = _find_repo_root(HERE)
for _p in (HERE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import argparse  # noqa: E402
import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any, Dict, List, Optional, Tuple  # noqa: E402

from worklet_data_api import Worklet  # noqa: E402  (stub)

from jwg_app.domain.models.theme_generation import ValueStreamCatalogue  # noqa: E402
from jwg_app.domain.services.theme import output_resolver as resolver  # noqa: E402
from jwg_app.domain.services.theme import worklet_mapper as mapper  # noqa: E402
from jwg_app.domain.services.theme_generation_handler import (  # noqa: E402
    ThemeGenerationHandler,
)

CONFIG_PATH = os.path.join(ROOT, "configs", "user_config.yaml")
TICKET_ID = "IDMT-19761"
RAW_TEXT_FILE = os.path.join(HERE, "raw_text.txt")  # the ticket raw text fed to generation

# Approved value streams, by id only -> every attribute comes from SQL. Multiple ids exercise the
# batched stage/capability calls, the per-VS parallel business-needs, and the resolver's cross-VS
# reassignment.
VALUE_STREAMS = ["VSR00074583", "VSR00074584"]


# --- platform debug wrapper ----------------------------------------------------------------

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
        print(f"\n>>> agenerate [{schema}] | model_params={ {k: v for k, v in (model_params or {}).items() if k != 'response_format'} }")
        print(f">>> user message ({len(user)} chars), first 400:\n{user[:400]}")
        data, error, status = await self._inner.agenerate(
            message=message, model_params=model_params, output_function=output_function, **kwargs
        )
        print(f"<<< status={status} error={error!r}")
        # the EXACT, full LLM output for this call (pretty-printed when it is JSON-ish)
        try:
            print(f"<<< data (full):\n{json.dumps(data, indent=2, default=str)}")
        except (TypeError, ValueError):
            print(f"<<< data (full): {data!r}")
        return data, error, status

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _FaultPlatform:
    """Wraps a platform to inject a 503 on selected calls, to exercise the failure-worklet paths.

    Modes:
        shared = fail a shared/batched call (stage selection) -> every value stream fails.
        needs  = fail business needs for ``target_vs`` only      -> just that value stream fails.
    """

    def __init__(self, inner: Any, mode: str, target_vs: str = "") -> None:
        self._inner = inner
        self._mode = mode
        self._target_vs = target_vs

    async def agenerate(
        self,
        message: List[Dict[str, str]],
        model_params: Optional[Dict[str, Any]] = None,
        output_function: Optional[type] = None,
        **kwargs: Any,
    ) -> Tuple[Optional[Any], Optional[str], int]:
        schema = output_function.__name__ if output_function else ""
        user = message[-1]["content"] if message else ""
        if self._mode == "shared" and schema == "BatchedStageSelection":
            return None, "injected shared failure (stage selection)", 503
        # business needs is a TextOut whose prompt carries the VS id (the body TextOut does not).
        if self._mode == "needs" and schema == "TextOut" and self._target_vs and self._target_vs in user:
            return None, f"injected business-needs failure ({self._target_vs})", 503
        return await self._inner.agenerate(
            message=message, model_params=model_params, output_function=output_function, **kwargs
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


# --- worklet builders ----------------------------------------------------------------------

def _prop(name: str, value: Any) -> Dict[str, Any]:
    # The real Worklet validates each property into a PropertyObject; a {propertyName, propertyValue}
    # dict is accepted, and the mapper reads either shape.
    return {"propertyName": name, "propertyValue": value}


def _load_raw_text(path: str) -> str:
    """Read the ticket raw text from a file; this is the only ticket input generation reads."""
    p = Path(path)
    text = p.read_text(encoding="utf-8").strip() if p.is_file() else ""
    if not text:
        raise SystemExit(f"# raw text file not found or empty: {path} (put the ticket text there)")
    print(f"# raw text from {path} ({len(text)} chars)")
    return text


def build_er_worklet(raw_text: str) -> Worklet:
    return Worklet(
        id=TICKET_ID,
        source_id=TICKET_ID,
        worklet_type="ENGAGEMENT_REQUEST",
        properties=[
            _prop("title", "New physical asset procurement initiative"),
            _prop("rawText", raw_text),
        ],
    )


def build_vs_worklets() -> List[Worklet]:
    # VALUE_STREAM worklets: each has its own worklet id (becomes the theme's parentWorkletId), a
    # valueStreamId property (the catalogue lookup key), and a businessValueStream label that is
    # carried over onto the theme worklet.
    return [
        Worklet(
            id=f"vswlet-{vs_id}",
            source_id=f"{TICKET_ID}-{vs_id}",
            worklet_type="VALUE_STREAM",
            properties=[
                _prop("valueStreamId", vs_id),
                _prop("businessValueStream", f"Value Stream {{{vs_id}}}"),
            ],
        )
        for vs_id in VALUE_STREAMS
    ]


# --- run -----------------------------------------------------------------------------------

def _print_themes(themes: List[Worklet]) -> None:
    print(f"\n# generated {len(themes)} theme worklet(s)\n" + "=" * 80)
    for theme in themes:
        print(f"THEME worklet: type={theme.worklet_type} parentWorkletId={theme.parent_worklet_id}")
        error = mapper.get_property(theme, mapper.ThemeProps.GENERATION_ERROR, None)
        if error is not None:
            bvs = mapper.get_property(theme, mapper.ThemeProps.BUSINESS_VALUE_STREAM, "")
            print(f"FAILED ({bvs}) - generationError: {error}")
            print("=" * 80)
            continue
        summary = mapper.get_property(theme, mapper.ThemeProps.SUMMARY, "")
        description = mapper.get_property(theme, mapper.ThemeProps.DESCRIPTION, "")
        needs = mapper.get_property(theme, mapper.ThemeProps.BUSINESS_NEEDS, "")
        tags = mapper.get_property(theme, mapper.ThemeProps.SELECTED_STAGES, {}) or {}
        l3 = mapper.get_property(theme, mapper.ThemeProps.L3, {}) or {}
        l2 = mapper.get_property(theme, mapper.ThemeProps.L2, {}) or {}
        print(f"SUMMARY: {summary}")
        print(f"DESCRIPTION:\n{description}\n")
        print(f"BUSINESS NEEDS:\n{needs}\n")
        print(f"SELECTED STAGES: {len(tags)} | L3: {len(l3)} | L2: {len(l2)}")
        print("=" * 80)


def _worklet_to_dict(theme: Worklet) -> Dict[str, Any]:
    """The generated theme worklet as a plain dict: top-level fields + the properties list."""
    props = []
    for p in theme.properties:
        if isinstance(p, dict):
            props.append({"propertyName": p.get("propertyName"), "propertyValue": p.get("propertyValue")})
        else:
            props.append({"propertyName": p.property_name, "propertyValue": p.property_value})
    return {
        "id": getattr(theme, "id", None),
        "sourceId": getattr(theme, "source_id", None),
        "parentWorkletId": getattr(theme, "parent_worklet_id", None),
        "workletType": str(getattr(theme, "worklet_type", None)),
        "properties": props,
    }


def _print_worklets_json(themes: List[Worklet]) -> None:
    """Worklet mode: the exact generated THEME worklet(s) as JSON (long text shortened)."""
    print("\n" + "=" * 80)
    print(f"# worklet mode: {len(themes)} generated THEME worklet(s)")
    for theme in themes:
        print(json.dumps(_shorten_strings(_worklet_to_dict(theme)), indent=2))


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


def _shorten_strings(obj: Any, limit: int = 160) -> Any:
    """Copy a JSON-ish structure, shortening long strings (the highlight HTML) so the schema shows
    without flooding the terminal. Scores and structure are kept in full."""
    if isinstance(obj, str):
        return obj if len(obj) <= limit else f"{obj[:limit]}… (+{len(obj) - limit} chars)"
    if isinstance(obj, dict):
        return {k: _shorten_strings(v, limit) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_shorten_strings(v, limit) for v in obj]
    return obj


def _run_coverage(er_worklet: Worklet, raw_text: str, themes: List[Worklet]) -> None:
    """Run coverage analysis on the generated theme worklets (the same flow the service does)."""
    from jwg_app.domain.services.coverage_analysis import CoverageAnalysisService

    _register_bundled_nltk_data()
    service = CoverageAnalysisService()
    dataset = service.build_dataset(raw_text=raw_text, themes=themes)
    print("\n" + "=" * 80)
    print(f"# coverage analysis: {len(dataset['generated_text'])} theme(s) scored vs raw text "
          f"({len(raw_text)} chars)")
    try:
        # coverage just returns the metrics; the service upserts them onto the ER (mimicked here).
        analysis_value = service.analyze(er_worklet=er_worklet, themes=themes)
    except RuntimeError as exc:
        # The n-gram evaluator (text_evaluation) is a prod dependency; print the dataset instead.
        print(f"# evaluator unavailable: {exc}")
        print("# dataset that WOULD be scored (long text shortened):")
        print(json.dumps(_shorten_strings(dataset), indent=2, default=str))
        return

    er_worklet.upsert_property(name=service.ANALYSIS_PROPERTY, value=analysis_value)
    # The serialized "analysis" property - exactly what the API would return on the ER.
    analysis = {"propertyName": service.ANALYSIS_PROPERTY, "propertyValue": analysis_value}
    for metric in analysis["propertyValue"]:
        name = metric.get("metric_name")
        value = metric.get("metric_value", {})
        print(f"\n--- {name} ---  score={value.get('score')}", end="")
        if "scores" in value:
            print(f"  per-theme={value.get('scores')}", end="")
        print()
    # Full property - every metric and the whole schema - with only the highlight HTML shortened.
    print("\n# full analysis property (highlight text shortened to show schema):")
    print(json.dumps(_shorten_strings(analysis), indent=2))


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
    from jwg_app.infrastructure.repositories import ValueStreamCatalogueRepository

    return ThemeService(catalogue_repository=ValueStreamCatalogueRepository(session))


async def main(args: argparse.Namespace) -> None:
    if args.debug:
        logging.basicConfig(
            level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
        )

    from db_session import dispose, session_scope

    raw_text = _load_raw_text(args.raw_text_file)
    er_worklet, vs_worklets = build_er_worklet(raw_text), build_vs_worklets()
    vs_ids = [mapper.value_stream_id(w) for w in vs_worklets]

    platform = _build_real_platform()
    if args.fail != "none":
        target_vs = vs_ids[0] if vs_ids else ""
        platform = _FaultPlatform(platform, args.fail, target_vs)
        print(f"# fault injection: --fail {args.fail}"
              + (f" (target VS {target_vs})" if args.fail == "needs" else ""))
    if args.debug:
        platform = _DebugPlatform(platform)
    print("# platform: real PlatformRestClient (config from .env)")
    print(f"# {len(vs_worklets)} value stream(s): {vs_ids} | only={args.only}")

    try:
        async with session_scope() as session:
            service = _build_real_service(session)
            handler = ThemeGenerationHandler(service, platform, args.config_path)
            if args.only == "all":
                themes = await handler.run(er_worklet, vs_worklets)
                _print_themes(themes)                       # current human-readable print mode
                if args.worklet:
                    _print_worklets_json(themes)            # worklet mode: full worklet JSON
                if args.coverage:
                    _run_coverage(er_worklet, raw_text, themes)
            else:
                catalogue = await service.fetch_theme_inputs(vs_ids)
                await _run_only(handler, args.only, er_worklet, vs_worklets, catalogue)
    finally:
        if hasattr(platform, "aclose"):
            await platform.aclose()
        await dispose()


async def _run_only(handler, only, er_worklet, vs_worklets, catalogue):
    """Run one generator (batched, as in the real pipeline) and print its output per value stream."""
    er = mapper.to_er_context(er_worklet)
    vs_ids = [mapper.value_stream_id(w) for w in vs_worklets]
    vs_list = [mapper.to_vs_context(vid, catalogue.get(vid, ValueStreamCatalogue())) for vid in vs_ids]

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
                print(f"  [{s.stage_id}] {s.stage_name}")
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
    parser.add_argument("--worklet", action="store_true",
                        help="worklet mode: print each generated THEME worklet as JSON (only with --only all)")
    parser.add_argument(
        "--fail",
        choices=["none", "shared", "needs"],
        default="none",
        help="inject a 503 to test failure worklets: 'shared' fails a batched call (every VS fails); "
             "'needs' fails business needs for the first VS (only that VS fails)",
    )
    parser.add_argument("--config-path", default=CONFIG_PATH,
                        help=f"path to user_config.yaml (default: auto-found at {CONFIG_PATH})")
    main_args = parser.parse_args()
    if not os.path.isfile(main_args.config_path):
        raise SystemExit(f"# config not found: {main_args.config_path} (pass --config-path)")
    asyncio.run(main(main_args))
