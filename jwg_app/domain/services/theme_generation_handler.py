"""
Theme generation handler.

Given the engagement-request worklet and the approved value-stream worklets, generates one THEME
worklet per value stream. The work runs in three steps:

    1. Ticket-level, in parallel: description body, description framing (all value streams), and
       stage selection (all value streams).
    2. After stages, in parallel: capability selection (one merged call) and business needs
       (per value stream).
    3. Per value stream: derive the L2 capabilities, then assemble the THEME worklet (description is
       the value stream's framing over the shared body).

Orchestration lives here; the theme helpers live in the ``theme`` subpackage: prompt strings come
from ``theme.prompt_builder``, the LLM output is turned into final values by
``theme.output_resolver``, and worklet-to-domain translation is in ``theme.worklet_mapper``. The
output schemas are in ``models.theme_generation``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pydantic import BaseModel, ValidationError
from worklet_data_api import Worklet

from jwg_app.domain.exceptions.custom_exception import CustomException
from jwg_app.domain.interfaces.platform_client import PlatformClient
from jwg_app.domain.interfaces.theme_catalogue import ThemeCatalogueReader
from jwg_app.domain.models.theme_generation import (
    ValueStreamCatalogue,
    BatchedCapabilitySelection,
    BatchedStageSelection,
    ERContext,
    FramingsOut,
    L3Capability,
    SelectedStage,
    TextOut,
    VSContext,
)
from jwg_app.domain.services.theme import output_resolver as resolver
from jwg_app.domain.services.theme import prompt_builder as prompts
from jwg_app.domain.services.theme import worklet_mapper as mapper
from jwg_app.domain.services.utils import load_config
from jwg_app.infrastructure.external.strict_schema import strict_response_format

logger = logging.getLogger(__name__)


def _error_detail(exc: BaseException) -> str:
    """The error text stored in a failure worklet's ``generationError`` (CustomException detail or str)."""
    return exc.detail if isinstance(exc, CustomException) else str(exc)


class ThemeGenerationHandler:
    """
    Generates Jira THEME worklets from an engagement request and its approved value streams.

    The heavy LLM calls are batched across all approved value streams: stage selection, description
    body and framing, and capability selection each run once for every value stream, while business
    needs runs per value stream. Generation reads the engagement request's raw ticket text.

    The platform client and catalogue reader are injected, so the handler orchestrates only: it
    never talks to Azure directly and never persists the worklets it returns.
    """

    def __init__(
        self,
        azure_sql_client: ThemeCatalogueReader,
        platform_client: PlatformClient,
        user_config_path: str,
    ) -> None:
        """
        Store the injected clients and load the theme-generation usecase config.

        Args:
            azure_sql_client: Reads the catalogue for the approved value streams.
            platform_client: Sends the structured LLM calls.
            user_config_path: Path to user_config.yaml; loaded once here.
        """
        self._azure_sql = azure_sql_client
        self._platform = platform_client
        config = load_config(user_config_path)
        self._usecase = config["theme_generation"]

    async def run(self, er_worklet: Worklet, vs_worklets: list[Worklet]) -> list[Worklet]:
        """
        Generate one THEME worklet per approved value stream.

        Args:
            er_worklet: The engagement-request worklet that grounds generation.
            vs_worklets: The approved value-stream worklets, one per value stream. Each worklet's
                ``valueStreamId`` property is the value-stream id used to read the catalogue, and its
                ``id`` becomes the generated theme worklet's ``parent_worklet_id``.

        Returns:
            One THEME worklet per value stream. Each is either a generated theme worklet or a
            failure worklet carrying ``generationError`` (built by ``mapper.to_failed_theme_worklet``).
            A shared/batched call failure (description body/framing, stage or capability selection)
            fails every value stream's worklet, since no theme can be built without that data. A
            per-value-stream failure (business needs unavailable, or no stages resolved) fails only
            that value stream's worklet; the rest are returned as normal theme worklets.

        Raises:
            CustomException: Only for failures that leave nothing to return - 404 if the ER or VS
                worklets are missing; 503 if Azure SQL is unavailable. LLM-call failures do not raise:
                they surface as failure worklets in the returned list.
        """
        if er_worklet is None or not vs_worklets:
            logger.error("theme generation aborted (404): ER worklet or VS worklet not found")
            raise CustomException(
                status_code=404, detail="ER worklet or VS worklet not found"
            )

        er = mapper.to_er_context(er_worklet)
        vs_ids = [mapper.value_stream_id(w) for w in vs_worklets]  # each VS worklet's valueStreamId property
        try:
            catalogue = await self._azure_sql.fetch_theme_inputs(vs_ids)
        except CustomException:
            raise
        except Exception as exc:
            logger.error("theme generation aborted (503): Azure SQL unavailable: %s", exc)
            raise CustomException(
                status_code=503, detail="Azure SQL service unavailable"
            ) from exc
        vs_by_id = {
            vs_id: mapper.to_vs_context(vs_id, catalogue.get(vs_id, ValueStreamCatalogue()))
            for vs_id in vs_ids
        }
        vs_list = list(vs_by_id.values())
        logger.info(
            "theme generation started: ticket=%s, %d approved value stream(s)",
            er.idmt_ticket_title, len(vs_list),
        )

        # --- Shared phase: batched, all-VS calls (description body/framings, stage + capability
        # selection). These produce data for every theme, so if any fails there is nothing to build
        # ANY theme from -> every value stream comes back as a failure worklet (we do not raise).
        # Step 1 — ticket-level batched calls, in parallel. return_exceptions=True lets all three
        # finish (no orphaned "never retrieved" tasks).
        results = await asyncio.gather(
            self._description_body(er),
            self._description_framings(er, vs_list),
            self._stage_selection(er, vs_list, catalogue),
            return_exceptions=True,
        )
        shared_failure = next((r for r in results if isinstance(r, BaseException)), None)
        if shared_failure is None:
            body, framings, stages_by_vs = results
            try:
                # Step 2 — capabilities (one merged call across all value streams).
                l3_by_stage = await self._capability_selection(er, vs_list, stages_by_vs, catalogue)
            except CustomException as exc:
                shared_failure = exc
        if shared_failure is not None:
            detail = _error_detail(shared_failure)
            logger.error("theme generation failed for all value streams: %s", detail)
            return [mapper.to_failed_theme_worklet(w, detail) for w in vs_worklets]

        # --- Per-VS phase: each value stream's own flow (business needs + assembly). A failure here
        # (business needs unavailable, or no stages resolved) only affects that value stream: its
        # worklet comes back as a failure worklet, the rest are returned as normal theme worklets.
        results = await asyncio.gather(
            *(
                self._build_theme(vs_wlet, vs_by_id[vs_id], er, stages_by_vs, l3_by_stage, body, framings)
                for vs_wlet, vs_id in zip(vs_worklets, vs_ids)
            ),
            return_exceptions=True,
        )
        themes: list[Worklet] = []
        for vs_wlet, vs_id, result in zip(vs_worklets, vs_ids, results):
            if isinstance(result, BaseException):
                detail = _error_detail(result)
                logger.error("theme generation failed for value stream %s: %s", vs_id, detail)
                themes.append(mapper.to_failed_theme_worklet(vs_wlet, detail))
            else:
                themes.append(result)

        succeeded = sum(1 for r in results if not isinstance(r, BaseException))
        logger.info(
            "theme generation finished: %d/%d theme(s) produced", succeeded, len(themes)
        )
        return themes

    async def _build_theme(
        self,
        vs_worklet: Worklet,
        vs: VSContext,
        er: ERContext,
        stages_by_vs: dict[str, list[SelectedStage]],
        l3_by_stage: dict[str, list[L3Capability]],
        body: str,
        framings: dict[str, str],
    ) -> Worklet:
        """Run one value stream's flow (business needs + assembly) and generate its THEME worklet.

        Raises ``CustomException`` on failure (no stages resolved, or business needs unavailable);
        the caller turns that into a failure worklet for this value stream and continues with the rest.
        """
        stages = stages_by_vs.get(vs.vs_id, [])
        if not stages:
            raise CustomException(
                status_code=400, detail="No valid stages resolved for this Value Stream"
            )
        business_needs = await self._business_needs_for_vs(er, vs, stages)
        l3 = [cap for stage in stages for cap in l3_by_stage.get(stage.stage_id, [])]
        l2 = resolver.derive_l2(l3)
        logger.info(
            "theme assembled for %s: %d stage(s) %s, %d L3, %d L2",
            vs.vs_id, len(stages), [s.stage_id for s in stages], len(l3), len(l2),
        )
        return mapper.to_theme_worklet(
            vs_worklet,
            summary=f"{er.idmt_ticket_title} - {vs.vs_name}",
            description=self._theme_description(framings.get(vs.vs_id, ""), body),
            business_needs=business_needs,
            selected_stages=stages,
            l3=l3,
            l2=l2,
        )

    async def _description_body(self, er: ERContext) -> str:
        """
        Generate the shared description body reused by every Theme for this ticket.

        Args:
            er: The engagement-request context.

        Returns:
            The shared description body text.
        """
        result = await self._call(
            "description_body", TextOut, ticket_context=prompts.ticket_context(er)
        )
        return result.text

    async def _description_framings(self, er: ERContext, vs_list: list[VSContext]) -> dict[str, str]:
        """
        Generate the per-value-stream opening paragraph for each Theme description.

        Args:
            er: The engagement-request context.
            vs_list: The approved value streams.

        Returns:
            The framing paragraph for each value stream, keyed by value-stream id.
        """
        if not vs_list:
            return {}
        picks = await self._call(
            "description_framing", FramingsOut,
            ticket_context=prompts.ticket_context(er),
            value_streams=prompts.framing_value_streams(vs_list),
        )
        # A value stream the model skips simply has no framing; its description still has the body.
        return {f.value_stream_id: f.text for f in picks.framings}

    @staticmethod
    def _theme_description(framing: str, body: str) -> str:
        """
        Assemble a Theme description from the value stream's framing paragraph and the shared body.

        Either part is omitted when empty.

        Args:
            framing: The value stream's opening paragraph.
            body: The shared description body.

        Returns:
            The assembled Theme description.
        """
        parts = []
        if framing.strip():
            parts.append("Theme Description:\n" + framing.strip())
        if body.strip():
            parts.append(body.strip())
        return "\n\n".join(parts)

    async def _stage_selection(
        self, er: ERContext, vs_list: list[VSContext], catalogue: dict[str, ValueStreamCatalogue]
    ) -> dict[str, list[SelectedStage]]:
        """
        Select the catalogue lifecycle stages for every approved value stream in one LLM call.

        Args:
            er: The engagement-request context.
            vs_list: The approved value streams.
            catalogue: The catalogue read, keyed by value-stream id.

        Returns:
            The selected stages for each value stream, keyed by value-stream id.
        """
        pairs = [
            (vs, catalogue[vs.vs_id].stage_list)
            for vs in vs_list
            if catalogue.get(vs.vs_id) and catalogue[vs.vs_id].stage_list
        ]
        if not pairs:
            return {}
        picks = await self._call(
            "stage_selection", BatchedStageSelection,
            ticket_context=prompts.ticket_context(er),
            value_streams=prompts.stage_value_streams(pairs),
        )
        return resolver.resolve_stages(picks, {vs.vs_id: stages for vs, stages in pairs})

    async def _capability_selection(
        self,
        er: ERContext,
        vs_list: list[VSContext],
        stages_by_vs: dict[str, list[SelectedStage]],
        catalogue: dict[str, ValueStreamCatalogue],
    ) -> dict[str, list[L3Capability]]:
        """
        Select the catalogue L3 capabilities for every selected stage in one merged LLM call.

        Args:
            er: The engagement-request context.
            vs_list: The approved value streams.
            stages_by_vs: The selected stages for each value stream.
            catalogue: The catalogue read, keyed by value-stream id.

        Returns:
            The selected L3 capabilities for each stage, keyed by stage id.
        """
        groups: list[tuple[VSContext, list[tuple[SelectedStage, list[L3Capability]]]]] = []
        candidates_by_stage: dict[str, list[L3Capability]] = {}
        for vs in vs_list:
            sql = catalogue.get(vs.vs_id)
            if sql is None:
                continue
            stage_caps = []
            for stage in stages_by_vs.get(vs.vs_id, []):
                candidates = [c for c in sql.l3_capabilities if c.stage_id == stage.stage_id]
                if candidates:
                    stage_caps.append((stage, candidates))
                    candidates_by_stage[stage.stage_id] = candidates
            if stage_caps:
                groups.append((vs, stage_caps))
        if not groups:
            logger.info("capability selection: no selected stage has L3 candidates; skipping")
            return {}
        picks = await self._call(
            "capability_selection", BatchedCapabilitySelection,
            ticket_context=prompts.ticket_context(er),
            value_streams=prompts.capability_value_streams(groups),
        )
        resolved = resolver.resolve_l3(picks, candidates_by_stage)
        logger.info(
            "capability selection: %d stage(s) with candidates, %d L3 selected",
            len(candidates_by_stage), sum(len(v) for v in resolved.values()),
        )
        return resolved

    async def _business_needs_for_vs(
        self, er: ERContext, vs: VSContext, stages: list[SelectedStage]
    ) -> str:
        """
        Generate the Business Needs text for one value stream's selected stages.

        Args:
            er: The engagement-request context.
            vs: The value stream.
            stages: That value stream's selected stages.

        Returns:
            The Business Needs text (empty if the value stream has no selected stages).

        Raises:
            CustomException: 503 if the LLM is unavailable.
        """
        if not stages:
            return ""
        result = await self._call(
            "business_needs", TextOut,
            ticket_context=prompts.ticket_context(er),
            value_stream_id=vs.vs_id,
            value_stream_name=vs.vs_name,
            value_stream_description=vs.vs_description,
            value_proposition=vs.value_proposition,
            selected_stages=prompts.selected_stages(stages),
        )
        return result.text

    async def _call(self, key: str, schema: type[BaseModel], **values: Any) -> BaseModel:
        """
        Run one structured LLM call for the given prompt key.

        Builds the system and user messages from the usecase prompt config, sends them through the
        chat-completions API constrained (strict) to ``schema``, and validates the structured result.
        A single attempt is made - there is no retry; strict structured output is the only guard.

        Args:
            key: The prompt key in the theme-generation usecase config.
            schema: The pydantic model the response must validate against.
            **values: The template variables that fill the prompt's static text.

        Returns:
            The validated ``schema`` instance.

        Raises:
            CustomException: 503 if the LLM gateway fails, returns a non-200 status or no data, or
                the output fails schema validation.
        """
        prompt = self._usecase["prompt"][key]
        messages = [
            {"role": "system", "content": prompt["system_role"]},
            {"role": "user", "content": prompt["static_prompt"].format(**values)},
        ]
        # Force strict (constrained) structured output: pass a strict response_format in model_params.
        # agenerate merges model_params into the request last, so this overrides its default
        # (non-strict) response_format - no platform-client change needed. Strict decoding makes the
        # model match the schema exactly (no renamed/missing fields, no objects where a value is due).
        model_params = {
            **(self._usecase.get("model_params") or {}),
            "response_format": strict_response_format(schema),
        }
        data, error, status_code = await self._platform.agenerate(
            message=messages,
            model_params=model_params,
            output_function=schema,
        )
        if error or status_code != 200 or data is None:
            reason = error or "no data returned"
            logger.error("LLM call %s failed (status=%s): %s", key, status_code, reason)
            raise CustomException(status_code=503, detail=f"LLM service unavailable: {reason}")
        try:
            payload = json.loads(data) if isinstance(data, str) else data
            return schema.model_validate(payload)
        except (ValidationError, json.JSONDecodeError) as exc:
            logger.error("LLM call %s output failed schema validation: %s", key, exc)
            raise CustomException(
                status_code=503, detail="LLM output failed schema validation"
            ) from exc

