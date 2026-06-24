"""PARTIAL REFERENCE — theme-generation methods of GeneratorService only.

This file is NOT the full prod GeneratorService (which also handles VS recommendation, feedback,
similar-entities, etc.). It reconstructs the two methods that drive theme generation, with the
changes needed for the current multi-VS ``ThemeGenerationHandler``. Merge ``_generate_theme_package``
(and the GENERATE case of ``handle_value_stream_action``) into the prod file; the ``self.*`` helpers
(get_worklet_by_id, validate_worklet, upsert_worklet, worklet_api_vs, session, platform_client,
logger) are the existing prod methods/attributes.

What changed vs the previous _generate_theme_package:
  1. Inject ThemeService as azure_sql_client (the handler reads VS attributes/stages/capabilities
     from Azure SQL; the constructor now requires it). ThemeService is injected into GeneratorService
     via DI - see get_generator_service note below - matching the get_value_stream_service pattern.
  2. Multi-VS, ONE call: run(er, vs_worklets) is called once with all approved VS so it can batch
     the shared LLM calls; it returns one THEME worklet per VS (a generated theme or a failure
     worklet carrying generationError). It does not raise on LLM failure.
  3. Partial success: persist every returned THEME worklet, split into generated vs failed (by the
     generationError property), and return (generated_themes, failed_value_streams). The GENERATE
     case maps that to 200 (all ok), 207 (some failed), or 500 (all failed). The handler builds each
     theme's businessValueStream from the VS worklet's title + valueStreamId.
  4. Add all vs_ids to the ER selected_VS_ids audit trail.

DI wiring (interface/dependencies/generator.py), matching the prod chain
(get_db_session -> repository -> service -> Depends in the endpoint):

    from jwg_app.interface.dependencies.theme import get_theme_service

    async def get_generator_service(
        ...,
        theme_service: ThemeService = Depends(get_theme_service),
    ) -> GeneratorService:
        return GeneratorService(..., theme_service=theme_service)

``get_theme_service`` already exists (interface/dependencies/theme.py): it wires the five
repositories to the request's AsyncSession - the same shape as get_value_stream_service.
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import List, Optional, Tuple

from worklet_data_api import User, Worklet, WorkletDataAPI, WorkletType  # prod package

from jwg_app.domain.exceptions.custom_exception import CustomException
from jwg_app.domain.interfaces.platform_client import PlatformClient
from jwg_app.domain.models.base import ValueStreamAction
from jwg_app.domain.services.coverage_analysis import CoverageAnalysisService
from jwg_app.domain.services.theme_generation_handler import ThemeGenerationHandler
from jwg_app.domain.services.theme_service import ThemeService


class GeneratorService:
    """Partial reference — theme-generation methods only.

    Assumes ``self.theme_service`` (a ThemeService) is injected via the GeneratorService DI provider,
    alongside the existing ``self.platform_client`` / helpers.
    """

    def __init__(
        self,
        worklet_api: WorkletDataAPI,
        worklet_api_er: WorkletDataAPI,
        worklet_api_theme: WorkletDataAPI,
        worklet_api_vs: WorkletDataAPI,
        jira_client,            # JIRAClient (prod)
        auth_info,              # AuthInfo (prod)
        jira_field_provider,    # JIRAFieldProvider (prod)
        platform_client: PlatformClient,
        theme_service: ThemeService,   # NEW: the catalogue reader for theme generation
    ) -> None:
        self.worklet_api = worklet_api
        self.worklet_api_er = worklet_api_er
        self.worklet_api_theme = worklet_api_theme
        self.worklet_api_vs = worklet_api_vs
        self.jira_client = jira_client
        self.auth_info = auth_info
        self.jira_field_provider = jira_field_provider
        self.platform_client = platform_client
        self.theme_service = theme_service   # NEW: catalogue reader for theme generation
        self.coverage_service = CoverageAnalysisService()   # NEW: coverage/creativity scoring (ANALYSE)
        self.logger = logging.getLogger(__name__)

    async def handle_value_stream_action(
        self,
        action: Optional[str],
        engagement_request_id: str,
        worklets: List[Worklet],
        user: User,
    ) -> Tuple[List[Worklet], str]:
        """
        Route value stream actions at the 2-level endpoint (ER -> VS).

        Endpoint: POST /{erWorkletId}/worklets

        Actions:
            - null:     Upsert (save/edit VS worklets)
            - GENERATE: Generate Theme package (TEGApiSpec §6 - Screen 3). Input: the approved
              VALUE_STREAM worklets (each with a valueStreamId property = the VS id).
        """
        await self.worklet_api_vs.begin()

        match action:
            case None:
                result = await self.upsert_value_streams(
                    engagement_request_id=engagement_request_id,
                    value_streams=worklets,
                    user_info=user,
                )
                await self.worklet_api_vs.commit()
                return result, "Value Streams saved successfully"

            case ValueStreamAction.GENERATE:
                # Theme generation (TEGApiSpec §6 - Screen 3): the approved VALUE_STREAM worklets.
                # The handler returns one THEME worklet per VS - a generated theme or a failure
                # worklet (generationError) - so generation is partial-success, not all-or-nothing.
                generated_themes, failed_value_streams = await self._generate_theme_package(
                    engagement_request_id=engagement_request_id,
                    vs_worklets=worklets,
                    user_info=user,
                )
                await self.worklet_api_vs.commit()
                if failed_value_streams:
                    if not generated_themes:
                        # every value stream failed -> total failure.
                        raise CustomException(
                            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="Theme generation failed for all value streams",
                        )
                    # some succeeded, some failed -> partial success; return the generated themes.
                    raise CustomException(
                        status_code=HTTPStatus.MULTI_STATUS,
                        detail=(
                            f"Generated themes for {len(generated_themes)} value stream(s), "
                            f"failed for {len(failed_value_streams)} value stream(s)"
                        ),
                        data=[t.model_dump(by_alias=True) for t in generated_themes],
                    )
                return generated_themes, "Theme package generated successfully"

            case _:
                raise CustomException(
                    status_code=HTTPStatus.BAD_REQUEST,
                    detail="Invalid action value for Value Stream",
                )

    async def _generate_theme_package(
        self,
        engagement_request_id: str,
        vs_worklets: List[Worklet],
        user_info: User,
    ) -> Tuple[List[Worklet], List[Worklet]]:
        """
        Generate Theme worklets for the approved Value Streams via ThemeGenerationHandler.

        TEGApiSpec §6 - Screen 3. Endpoint: POST /api/v1/worklets/{erWorkletId}/worklets, GENERATE.
        The request body is the approved VALUE_STREAM worklets (each with a valueStreamId property).
        The handler is multi-VS: it is called ONCE with all VS so it can batch stage/description/
        capability selection across them, and it returns one THEME worklet per value stream - a
        generated theme, or a failure worklet carrying ``generationError`` (a shared-call failure
        fails every VS; a per-VS failure fails only that VS). The handler does not raise on LLM
        failures; this method splits the returned worklets into generated vs failed.

        Args:
            engagement_request_id: ER worklet ID (URL path param).
            vs_worklets: The approved VALUE_STREAM worklets from the request body.
            user_info: Authenticated user performing the operation.

        Returns:
            ``(generated_themes, failed_value_streams)`` - the saved generated THEME worklets and the
            saved failure worklets (each carrying ``generationError``). Both are persisted.
        """
        # Step 0 - require at least one VS worklet; collect the value-stream ids (deduped) for the
        # audit trail. A VS worklet missing valueStreamId just becomes a failure worklet downstream
        # (the handler looks up an empty catalogue), so it is not rejected here.
        if not vs_worklets:
            raise CustomException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="GENERATE action requires at least one Value Stream worklet in source",
            )
        value_stream_ids: List[str] = []
        for vs_worklet in vs_worklets:
            vs_id = vs_worklet.get_property_value("valueStreamId")
            if vs_id and vs_id not in value_stream_ids:
                value_stream_ids.append(vs_id)

        # Step 1 - fetch and validate the Engagement Request.
        er_worklet = await self.get_worklet_by_id(engagement_request_id)
        er_validation = await self.validate_worklet(
            er_worklet, WorkletType.ENGAGEMENT_REQUEST, er_worklet.source_id
        )
        if er_validation:
            raise CustomException(
                status_code=er_validation["status_code"], detail=er_validation["detail"]
            )

        # Step 2 - validate EACH input VS worklet (correct type, parented to this ER).
        for vs_worklet in vs_worklets:
            vs_validation = await self.validate_worklet(
                vs_worklet,
                WorkletType.VALUE_STREAM,
                source_id=vs_worklet.source_id,
                parent_worklet_id=er_worklet.id,
            )
            if vs_validation:
                raise CustomException(
                    status_code=vs_validation["status_code"], detail=vs_validation["detail"]
                )

        # Step 3 - generate. The catalogue reader (ThemeService) is injected via DI; the handler reads
        # each VS's attributes/stages/capabilities from Azure SQL (keyed by each VS worklet's
        # valueStreamId) and generates one THEME worklet per VS, parented to that VS worklet.
        handler = ThemeGenerationHandler(
            azure_sql_client=self.theme_service,
            platform_client=self.platform_client,
            user_config_path="configs/user_config.yaml",
        )
        theme_worklets = await handler.run(er_worklet=er_worklet, vs_worklets=vs_worklets)

        # Step 4 - persist each THEME worklet and split successes from failures. A failure worklet
        # carries a generationError property (the generated content is replaced by the error).
        generated_themes: List[Worklet] = []
        failed_value_streams: List[Worklet] = []
        for theme_worklet in theme_worklets:
            theme_worklet.current_user = user_info
            saved = await self.upsert_worklet(theme_worklet, user_info)
            # a failure worklet carries a generationError property (theme worklet_mapper is
            # theme-internal, so the property name is read directly here).
            if saved.get_property_value("generationError"):
                failed_value_streams.append(saved)
            else:
                generated_themes.append(saved)

        # Step 5 - update the ER worklet's selected_VS_ids audit trail with ALL value streams.
        er_properties = {
            p.get("propertyName"): p.get("propertyValue")
            for p in (er_worklet.model_dump().get("properties") or [])
        }
        similar_entities = er_properties.get("similarEntitiesId") or {}
        selected_vs_ids = similar_entities.get("selected_VS_ids", [])
        changed = False
        for value_stream_id in value_stream_ids:
            if value_stream_id not in selected_vs_ids:
                selected_vs_ids.append(value_stream_id)
                changed = True
        if changed:
            similar_entities["selected_VS_ids"] = selected_vs_ids
            er_worklet.upsert_property(name="similarEntitiesId", value=similar_entities)
            er_worklet.current_user = user_info
            await self.upsert_worklet(er_worklet, user_info)

        self.logger.info(
            "Theme generation for ER %s: %d generated, %d failed",
            engagement_request_id, len(generated_themes), len(failed_value_streams),
        )
        return generated_themes, failed_value_streams

    async def _analyze_worklets(self, source_worklet: Worklet, user: User) -> Worklet:
        """
        Analyse an Engagement Request: coverage + creativity of its generated themes.

        Worklet in, the same worklet out. The coverage service is pure scoring: it reads the source
        context off the ER's ``rawText`` property, scores each theme's ``description`` + ``Business
        Needs`` against it, and **returns** the JSON-ready metrics. This method owns the worklet I/O:
        it upserts the metrics onto the ER's ``analysis`` property and persists it. Replaces the
        previous STUB (mock 0.0 scores).
        """
        # Step 1-2 - fetch + validate the ER (unchanged from the stub).
        er_worklet = await self.get_worklet_by_id(source_worklet.id)
        er_validation = await self.validate_worklet(
            er_worklet, WorkletType.ENGAGEMENT_REQUEST, er_worklet.source_id
        )
        if er_validation:
            raise CustomException(
                status_code=er_validation["status_code"], detail=er_validation["detail"]
            )

        # Step 3 - the generated THEME worklets to score (only valid themes are passed in).
        themes = await self._get_generated_themes_for_analysis(er_worklet)  # returns THEME worklets

        # Step 4 - score the themes (the coverage service returns the metrics; it does not mutate).
        analysis = self.coverage_service.analyze(er_worklet=er_worklet, themes=themes)

        # Step 5 - upsert the analysis onto the ER worklet and persist it (worklet I/O owned here).
        er_worklet.upsert_property(name=self.coverage_service.ANALYSIS_PROPERTY, value=analysis)
        er_worklet.current_user = user
        er_worklet = await self.worklet_api_er.update_worklet(er_worklet.id, er_worklet, user)
        return er_worklet
