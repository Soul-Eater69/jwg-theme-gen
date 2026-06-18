"""Theme generation handler.

Given the ER worklet and the approved Value Stream worklets, generates one THEME worklet per
Value Stream. The heavy calls are batched across all approved Value Streams (which is why ``run``
takes the VS list): stage selection, description body + framing, and capabilities each run once
for every VS; only business needs runs per VS. Generation reads the ER's raw ticket text.

Order of work:
  1. Ticket-level, in parallel: description body, description framing (all VS), stage selection (all VS).
  2. After stages, in parallel: capabilities (one merged call, all VS) and business needs (per VS).
  3. Per VS: derive L2 capabilities, then assemble the THEME worklet (description = framing + body).

Orchestration lives here; the theme helpers live in the ``theme`` subpackage: prompt strings come
from ``theme.prompt_builder``, the LLM output is turned into final values by ``theme.output_resolver``,
and worklet/domain translation is in ``theme.worklet_mapper``. Output schemas are in
``models.theme_generation``.
The platform client and catalogue reader are injected; the handler never persists.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Union

from pydantic import BaseModel
from worklet_data_api import Worklet

from jwg_app.domain.exceptions.custom_exception import CustomException
from jwg_app.domain.interfaces.platform_client import PlatformClient
from jwg_app.domain.interfaces.theme_catalogue import ThemeCatalogueReader
from jwg_app.domain.models.theme_generation import (
    AzureSQLData,
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


class ThemeGenerationHandler:
    def __init__(
        self,
        azure_sql_client: ThemeCatalogueReader,
        platform_client: PlatformClient,
        user_config: Union[str, dict],
    ) -> None:
        self._azure_sql = azure_sql_client
        self._platform = platform_client
        config = load_config(user_config) if isinstance(user_config, str) else user_config
        # the theme_generation usecase: { prompt: {key: {system_role, static_prompt}}, model_params }
        self._usecase = config["theme_generation"]

    # ---- public ----------------------------------------------------------------------

    async def run(self, er_worklet: Worklet, vs_worklets: list[Worklet]) -> list[Worklet]:
        """One unsaved THEME worklet per approved Value Stream; the caller persists them."""
        er = mapper.to_er_context(er_worklet)
        vs_ids = [mapper.value_stream_id(w) for w in vs_worklets]
        catalogue = await self._azure_sql.fetch_theme_inputs(vs_ids)
        vs_by_id = {
            vs_id: mapper.to_vs_context(worklet, catalogue.get(vs_id, AzureSQLData()))
            for worklet, vs_id in zip(vs_worklets, vs_ids)
        }
        vs_list = list(vs_by_id.values())

        # Step 1 — ticket-level batched calls, in parallel.
        body, framings, stages_by_vs = await asyncio.gather(
            self._description_body(er),
            self._description_framings(er, vs_list),
            self._stage_selection(er, vs_list, catalogue),
        )

        # Step 2 — after stages: capabilities (one merged call) and business needs (per VS).
        l3_by_stage, needs_by_vs = await asyncio.gather(
            self._capabilities(er, vs_list, stages_by_vs, catalogue),
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
                    title=resolver.theme_title(er, vs),
                    description=resolver.assemble_description(framings.get(vs_id, ""), body),
                    business_needs=needs_by_vs.get(vs_id, ""),
                    selected_stages=stages,
                    l3=l3,
                    l2=resolver.derive_l2(l3),
                )
            )
        return themes

    # ---- Step 1: description body (1 call, VS-agnostic) ------------------------------

    async def _description_body(self, er: ERContext) -> str:
        """Generate the shared description body reused by every Theme for the ER."""
        out = await self._call(
            "description_body", TextOut, ticket_context=prompts.ticket_context(er)
        )
        return out.text

    # ---- Step 1: description framing (1 call, all VS) -------------------------------

    async def _description_framings(self, er: ERContext, vs_list: list[VSContext]) -> dict[str, str]:
        """Generate the per-VS opening paragraph for each Theme description."""
        if not vs_list:
            return {}
        out = await self._call(
            "description_framing", FramingsOut,
            ticket_context=prompts.ticket_context(er),
            value_streams=prompts.framing_value_streams(vs_list),
        )
        return resolver.resolve_framings(out, [vs.vs_id for vs in vs_list])

    # ---- Step 1: stage selection (1 call, all VS) ----------------------------------

    async def _stage_selection(
        self, er: ERContext, vs_list: list[VSContext], catalogue: dict[str, AzureSQLData]
    ) -> dict[str, list[SelectedStage]]:
        """Select governed lifecycle stages for every approved Value Stream in one LLM call."""
        pairs = [
            (vs, catalogue[vs.vs_id].stage_list)
            for vs in vs_list
            if catalogue.get(vs.vs_id) and catalogue[vs.vs_id].stage_list
        ]
        if not pairs:
            return {}
        out = await self._call(
            "stage_selection", BatchedStageSelection,
            ticket_context=prompts.ticket_context(er),
            value_streams=prompts.stage_value_streams(pairs),
        )
        return resolver.resolve_stages(out, {vs.vs_id: stages for vs, stages in pairs})

    # ---- Step 2: capabilities (1 merged call, all VS) ------------------------------

    async def _capabilities(
        self,
        er: ERContext,
        vs_list: list[VSContext],
        stages_by_vs: dict[str, list[SelectedStage]],
        catalogue: dict[str, AzureSQLData],
    ) -> dict[str, list[L3Capability]]:
        """Select governed L3 capabilities for all selected stages in one merged LLM call."""
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
        out = await self._call(
            "capability_selection", BatchedCapabilitySelection,
            ticket_context=prompts.ticket_context(er),
            value_streams=prompts.capability_value_streams(groups),
        )
        return resolver.resolve_l3(out, candidates_by_stage)

    # ---- Step 2: business needs (per VS, parallel) ---------------------------------

    async def _business_needs(
        self, er: ERContext, vs_list: list[VSContext], stages_by_vs: dict[str, list[SelectedStage]]
    ) -> dict[str, str]:
        """Generate Business Needs independently for each VS that has selected stages."""
        async def for_vs(vs: VSContext) -> tuple[str, str]:
            stages = stages_by_vs.get(vs.vs_id, [])
            if not stages:
                return vs.vs_id, ""
            out = await self._call(
                "business_needs", TextOut,
                ticket_context=prompts.ticket_context(er),
                value_stream_id=vs.vs_id,
                value_stream_name=vs.vs_name,
                value_stream_description=vs.vs_description,
                value_proposition=vs.value_proposition,
                selected_stages=prompts.selected_stages(stages),
            )
            return vs.vs_id, out.text

        return dict(await asyncio.gather(*(for_vs(vs) for vs in vs_list)))

    # ---- LLM call --------------------------------------------------------------------

    async def _call(self, key: str, schema: type[BaseModel], **values: Any) -> BaseModel:
        """Build the messages for ``key`` (system_role + filled static_prompt), send them via the
        chat-completions API constrained to ``schema``, and validate the structured result."""
        prompt = self._usecase["prompt"][key]
        messages = [
            {"role": "system", "content": prompt["system_role"]},
            {"role": "user", "content": prompt["static_prompt"].format(**values)},
        ]
        data, error, status_code = await self._platform.agenerate(
            message=messages,
            model_params=self._usecase.get("model_params"),
            output_function=schema,
        )
        if error or status_code != 200 or data is None:
            raise CustomException(
                status_code=status_code, detail=error or "platform agenerate returned no data"
            )
        if isinstance(data, str):  # structured output returned as a JSON string
            data = json.loads(data)
        return schema.model_validate(data)

