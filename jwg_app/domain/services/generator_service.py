"""PARTIAL REFERENCE — theme-generation methods of GeneratorService only.

This file is NOT the full prod GeneratorService (which also handles VS recommendation, feedback,
similar-entities, etc.). It reconstructs the two methods that drive theme generation, with the
changes needed for the current multi-VS ``ThemeGenerationHandler``. Merge ``_generate_theme_package``
(and the GENERATE case of ``handle_value_stream_action``) into the prod file; the ``self.*`` helpers
(get_worklet_by_id, validate_worklet, upsert_worklet, worklet_api_vs, session, platform_client,
logger) are the existing prod methods/attributes.

What changed vs the previous _generate_theme_package:
  1. Inject ThemeService as azure_sql_client (the handler reads VS attributes/stages/capabilities
     from Azure SQL; the constructor now requires it).
  2. Multi-VS: collect ALL VS ids from the theme stubs, fetch all VS worklets, run(list) -> list.
  3. Persist each enriched worklet (to_theme_worklet edits the VS worklet in place).
  4. Add all vs_ids to the ER selected_VS_ids audit trail.
"""

from http import HTTPStatus
from typing import List, Optional, Tuple

from worklet_data_api import User, Worklet, WorkletType  # prod package

from jwg_app.domain.exceptions.custom_exception import CustomException
from jwg_app.domain.models.base import ValueStreamAction
from jwg_app.domain.services.theme_generation_handler import ThemeGenerationHandler
from jwg_app.domain.services.theme_service import ThemeService
from jwg_app.infrastructure.repositories.l2_capability_repository import L2CapabilityRepository
from jwg_app.infrastructure.repositories.l3_capability_repository import L3CapabilityRepository
from jwg_app.infrastructure.repositories.value_stream_capability_repository import (
    ValueStreamCapabilityRepository,
)
from jwg_app.infrastructure.repositories.value_stream_repository import ValueStreamRepository
from jwg_app.infrastructure.repositories.value_stream_stage_repository import (
    ValueStreamStageRepository,
)


class GeneratorService:
    """Partial reference — theme-generation methods only."""

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
            - GENERATE: Generate Theme package (TEGApiSpec §6 - Screen 3). Input: THEME worklet stubs
              with parentWorkletId = vsWorkletId.
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
                # Theme generation (TEGApiSpec §6 - Screen 3): THEME stubs carry the vsWorkletId.
                result = await self._generate_theme_package(
                    engagement_request_id=engagement_request_id,
                    theme_stubs=worklets,
                    user_info=user,
                )
                await self.worklet_api_vs.commit()
                return result, "Theme package generated successfully"

            case _:
                raise CustomException(
                    status_code=HTTPStatus.BAD_REQUEST,
                    detail="Invalid action value for Value Stream",
                )

    async def _generate_theme_package(
        self,
        engagement_request_id: str,
        theme_stubs: List[Worklet],
        user_info: User,
    ) -> List[Worklet]:
        """
        Generate Theme packages for the approved Value Streams via ThemeGenerationHandler.

        TEGApiSpec §6 - Screen 3. Endpoint: POST /api/v1/worklets/{erWorkletId}/worklets, GENERATE.
        Each THEME worklet stub carries parentWorkletId = vsWorkletId. The handler is multi-VS: it
        takes the full list of VS worklets and batches stage/description/capability selection across
        them.

        Args:
            engagement_request_id: ER worklet ID (URL path param).
            theme_stubs: THEME worklet stubs from the request body (parentWorkletId = a VS worklet ID).
            user_info: Authenticated user performing the operation.

        Returns:
            The list of saved THEME worklets (one per approved Value Stream).
        """
        # Step 0 - collect ALL VS worklet ids from the stubs' parentWorkletId (deduped, order kept).
        if not theme_stubs:
            raise CustomException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="GENERATE action requires at least one THEME worklet stub in source",
            )
        value_stream_ids: List[str] = []
        for stub in theme_stubs:
            if not stub.parent_worklet_id:
                raise CustomException(
                    status_code=HTTPStatus.BAD_REQUEST,
                    detail="Theme stub must have parentWorkletId set to the VS worklet ID",
                )
            if stub.parent_worklet_id not in value_stream_ids:
                value_stream_ids.append(stub.parent_worklet_id)

        # Step 1 - fetch and validate the Engagement Request.
        er_worklet = await self.get_worklet_by_id(engagement_request_id)
        er_validation = await self.validate_worklet(
            er_worklet, WorkletType.ENGAGEMENT_REQUEST, er_worklet.source_id
        )
        if er_validation:
            raise CustomException(
                status_code=er_validation["status_code"], detail=er_validation["detail"]
            )

        # Step 2 - fetch and validate EACH Value Stream worklet.
        vs_worklets: List[Worklet] = []
        for value_stream_id in value_stream_ids:
            vs_worklet = await self.get_worklet_by_id(value_stream_id)
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
            vs_worklets.append(vs_worklet)

        # Step 3 - build the SQL catalogue reader (ThemeService) and run generation (list -> list).
        theme_service = ThemeService(
            value_stream_repository=ValueStreamRepository(session=self.session),
            stage_repository=ValueStreamStageRepository(session=self.session),
            capability_repository=ValueStreamCapabilityRepository(session=self.session),
            l3_repository=L3CapabilityRepository(session=self.session),
            l2_repository=L2CapabilityRepository(session=self.session),
        )
        handler = ThemeGenerationHandler(
            azure_sql_client=theme_service,
            platform_client=self.platform_client,
            user_config_path="configs/user_config.yaml",
        )
        theme_worklets = await handler.run(er_worklet=er_worklet, vs_worklets=vs_worklets)

        # Step 4 - persist each enriched THEME worklet (the handler edited the VS worklets in place).
        saved_themes: List[Worklet] = []
        for theme_worklet in theme_worklets:
            theme_worklet.current_user = user_info
            saved_themes.append(await self.upsert_worklet(theme_worklet, user_info))

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
            f"Generated Theme package(s) for {len(saved_themes)} VS under ER {engagement_request_id}"
        )
        return saved_themes
