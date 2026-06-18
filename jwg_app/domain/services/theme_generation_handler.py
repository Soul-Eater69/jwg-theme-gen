"""ThemeGenerationHandler (LLD §8.3).

Given the ER worklet and the approved Value Stream worklets, generate one THEME worklet per VS.
The heavy calls are batched across ALL approved Value Streams (the reason ``run`` takes the VS
list): stage selection, description body + framing, and capabilities each run once for every VS;
only business needs is per VS. Generation reads the ER's RAW ticket text.

Phases:
  A — ticket-level, in parallel: description body, description framing (all VS), stage selection (all VS).
  B — after stages, in parallel: capabilities (one merged call, all VS) ∥ business needs (per VS).
  C — deterministic, per VS: derive L2, assemble the THEME worklet (description = framing + body).

Design: SRP — orchestration here; prompt rendering + output resolution in ``theme_generation_helper``;
worklet↔domain translation in ``worklet_mapper``; schemas in ``models.theme_generation``. DIP/ISP —
the ``PlatformClient`` and ``ThemeCatalogueReader`` Protocols are injected; the handler never persists.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Union

from pydantic import BaseModel

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
from jwg_app.domain.models.worklet import Worklet
from jwg_app.domain.services import theme_generation_helper as helper
from jwg_app.domain.services import worklet_mapper as mapper
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

        # Phase A — ticket-level batched calls, in parallel.
        body, framings, stages_by_vs = await asyncio.gather(
            self._description_body(er),
            self._description_framings(er, vs_list),
            self._stage_selection(er, vs_list, catalogue),
        )

        # Phase B — after stages: capabilities (one merged call) ∥ business needs (per VS).
        l3_by_stage, needs_by_vs = await asyncio.gather(
            self._capabilities(er, vs_list, stages_by_vs, catalogue),
            self._business_needs(er, vs_list, stages_by_vs),
        )

        # Phase C — assemble per VS.
        themes: list[Worklet] = []
        for worklet, vs_id in zip(vs_worklets, vs_ids):
            vs = vs_by_id[vs_id]
            stages = stages_by_vs.get(vs_id, [])
            l3 = [cap for stage in stages for cap in l3_by_stage.get(stage.stage_id, [])]
            themes.append(
                mapper.to_theme_worklet(
                    worklet,
                    title=helper.theme_title(er, vs),
                    description=helper.assemble_description(framings.get(vs_id, ""), body),
                    business_needs=needs_by_vs.get(vs_id, ""),
                    selected_stages=stages,
                    l3=l3,
                    l2=helper.derive_l2(l3),
                )
            )
        return themes

    # ---- Phase A: description body (1 call, VS-agnostic) ------------------------------

    async def _description_body(self, er: ERContext) -> str:
        """Generate the shared description body reused by every Theme for the ER."""
        out = await self._call(
            "description_body", TextOut, ticket_context=helper.ticket_context(er)
        )
        return out.text

    # ---- Phase A: description framing (1 call, all VS) -------------------------------

    async def _description_framings(self, er: ERContext, vs_list: list[VSContext]) -> dict[str, str]:
        """Generate the per-VS opening paragraph for each Theme description."""
        if not vs_list:
            return {}
        out = await self._call(
            "description_framing", FramingsOut,
            ticket_context=helper.ticket_context(er),
            value_streams=helper.framing_value_streams(vs_list),
        )
        return helper.resolve_framings(out, [vs.vs_id for vs in vs_list])

    # ---- Phase A: stage selection (1 call, all VS) ----------------------------------

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
            ticket_context=helper.ticket_context(er),
            value_streams=helper.stage_value_streams(pairs),
        )
        return helper.resolve_stages_for_all(out, {vs.vs_id: stages for vs, stages in pairs})

    # ---- Phase B: capabilities (1 merged call, all VS) ------------------------------

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
            ticket_context=helper.ticket_context(er),
            value_streams=helper.capability_value_streams(groups),
        )
        return helper.resolve_l3_merged(out, candidates_by_stage)

    # ---- Phase B: business needs (per VS, parallel) ---------------------------------

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
                ticket_context=helper.ticket_context(er),
                value_stream_id=vs.vs_id,
                value_stream_name=vs.vs_name,
                value_stream_description=vs.vs_description,
                value_proposition=vs.value_proposition,
                selected_stages=helper.render_selected_stages(stages),
            )
            return vs.vs_id, out.text

        return dict(await asyncio.gather(*(for_vs(vs) for vs in vs_list)))

    # ---- LLM call --------------------------------------------------------------------

    async def _call(self, key: str, schema: type[BaseModel], **values: Any) -> BaseModel:
        """Build the prompt for ``key`` from the usecase config (system_role + filled static_prompt),
        send it with the usecase model params, and validate the result against ``schema``."""
        prompt = self._usecase["prompt"][key]
        messages = [
            {"role": "system", "content": prompt["system_role"]},
            {"role": "user", "content": prompt["static_prompt"].format(**values)},
        ]
        data, error, status_code = await self._platform.agenerate(
            message=messages,
            output_function=schema,
            model_params=self._usecase.get("model_params"),
        )
        if error or status_code != 200 or data is None:
            # TODO: align with the prod handler pattern (return a result object vs raise).
            raise RuntimeError(f"platform agenerate failed ({status_code}): {error or 'no data'}")
        if isinstance(data, str):  # text fell through; parse it
            data = json.loads(data)
        return schema.model_validate(data)

