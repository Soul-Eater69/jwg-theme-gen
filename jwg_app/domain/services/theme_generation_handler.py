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

from pydantic import BaseModel
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

logger = logging.getLogger(__name__)


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
        # the theme_generation usecase: { prompt: {key: {system_role, static_prompt}}, model_params }
        self._usecase = config["theme_generation"]

    async def run(self, er_worklet: Worklet, vs_worklets: list[Worklet]) -> list[Worklet]:
        """
        Generate one unsaved THEME worklet per approved value stream.

        Args:
            er_worklet: The engagement-request worklet that grounds generation.
            vs_worklets: The approved value-stream worklets, one Theme each.

        Returns:
            One unsaved THEME worklet per approved value stream, for the caller to persist.

        Raises:
            CustomException: 404 if the ER or VS worklets are missing; 400 if no stages resolve
                for any value stream; 503 if Azure SQL or the LLM is unavailable.
        """
        if er_worklet is None or not vs_worklets:
            raise CustomException(
                status_code=404, detail="ER worklet or VS worklet not found"
            )

        er = mapper.to_er_context(er_worklet)
        vs_ids = [mapper.value_stream_id(w) for w in vs_worklets]
        try:
            catalogue = await self._azure_sql.fetch_theme_inputs(vs_ids)
        except CustomException:
            raise
        except Exception as exc:
            raise CustomException(
                status_code=503, detail="Azure SQL service unavailable"
            ) from exc
        vs_by_id = {
            vs_id: mapper.to_vs_context(worklet, catalogue.get(vs_id, ValueStreamCatalogue()))
            for worklet, vs_id in zip(vs_worklets, vs_ids)
        }
        vs_list = list(vs_by_id.values())
        logger.info(
            "theme generation started: ticket=%s, %d approved value stream(s)",
            er.idmt_ticket_title, len(vs_list),
        )

        # Step 1 — ticket-level batched calls, in parallel.
        body, framings, stages_by_vs = await asyncio.gather(
            self._description_body(er),
            self._description_framings(er, vs_list),
            self._stage_selection(er, vs_list, catalogue),
        )

        if not any(stages_by_vs.get(vs.vs_id) for vs in vs_list):
            raise CustomException(
                status_code=400, detail="No valid stages resolved for this Value Stream"
            )

        # Step 2 — after stages: capabilities (one merged call) and business needs (per VS).
        l3_by_stage, needs_by_vs = await asyncio.gather(
            self._capability_selection(er, vs_list, stages_by_vs, catalogue),
            self._business_needs(er, vs_list, stages_by_vs),
        )

        # Step 3 — assemble per VS.
        themes: list[Worklet] = []
        for worklet, vs_id in zip(vs_worklets, vs_ids):
            vs = vs_by_id[vs_id]
            stages = stages_by_vs.get(vs_id, [])
            l3 = [cap for stage in stages for cap in l3_by_stage.get(stage.stage_id, [])]
            themes.append(
                mapper.to_theme_worklet(
                    worklet,
                    title=f"{er.idmt_ticket_title} -- {vs.vs_name}",
                    description=self._theme_description(framings.get(vs_id, ""), body),
                    business_needs=needs_by_vs.get(vs_id, ""),
                    selected_stages=stages,
                    l3=l3,
                    l2=resolver.derive_l2(l3),
                )
            )
        logger.info("theme generation finished: %d theme(s) produced", len(themes))
        return themes

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
            return {}
        picks = await self._call(
            "capability_selection", BatchedCapabilitySelection,
            ticket_context=prompts.ticket_context(er),
            value_streams=prompts.capability_value_streams(groups),
        )
        return resolver.resolve_l3(picks, candidates_by_stage)

    async def _business_needs(
        self, er: ERContext, vs_list: list[VSContext], stages_by_vs: dict[str, list[SelectedStage]]
    ) -> dict[str, str]:
        """
        Generate the Business Needs text for each value stream that has selected stages.

        Args:
            er: The engagement-request context.
            vs_list: The approved value streams.
            stages_by_vs: The selected stages for each value stream.

        Returns:
            The Business Needs text for each value stream, keyed by value-stream id.
        """
        async def for_vs(vs: VSContext) -> tuple[str, str]:
            stages = stages_by_vs.get(vs.vs_id, [])
            if not stages:
                return vs.vs_id, ""
            result = await self._call(
                "business_needs", TextOut,
                ticket_context=prompts.ticket_context(er),
                value_stream_id=vs.vs_id,
                value_stream_name=vs.vs_name,
                value_stream_description=vs.vs_description,
                value_proposition=vs.value_proposition,
                selected_stages=prompts.selected_stages(stages),
            )
            return vs.vs_id, result.text

        return dict(await asyncio.gather(*(for_vs(vs) for vs in vs_list)))

    async def _call(self, key: str, schema: type[BaseModel], **values: Any) -> BaseModel:
        """
        Run one structured LLM call for the given prompt key.

        Builds the system and user messages from the usecase prompt config, sends them through the
        chat-completions API constrained to ``schema``, and validates the structured result.

        Args:
            key: The prompt key in the theme-generation usecase config.
            schema: The pydantic model the response must validate against.
            **values: The template variables that fill the prompt's static text.

        Returns:
            The validated ``schema`` instance.

        Raises:
            CustomException: 503 if the LLM gateway returns an error, a non-200 status, or no data.
        """
        prompt = self._usecase["prompt"][key]
        messages = [
            {"role": "system", "content": prompt["system_role"]},
            {"role": "user", "content": prompt["static_prompt"].format(**values)},
        ]
        logger.debug("calling LLM for %s", key)
        data, error, status_code = await self._platform.agenerate(
            message=messages,
            model_params=self._usecase.get("model_params"),
            output_function=schema,
        )
        if error or status_code != 200 or data is None:
            reason = error or "no data returned"
            logger.error("LLM call %s failed (status=%s): %s", key, status_code, reason)
            raise CustomException(
                status_code=503, detail=f"LLM service unavailable: {reason}"
            )
        if isinstance(data, str):  # structured output returned as a JSON string
            data = json.loads(data)
        return schema.model_validate(data)

