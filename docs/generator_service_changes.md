# `generator_service.py` — changes for the multi-VS theme handler

The prod `GeneratorService._generate_theme_package` must change to match `ThemeGenerationHandler`'s
current contract. Paste the updated method below into prod's `generator_service.py`. (This file is
prod-only and not in this repo, so this is a reference, not a compiled drop-in - adapt the session /
helper calls to your actual wiring.)

## What changed vs the current method

1. **Inject the catalogue reader.** The handler now needs `azure_sql_client` (a `ThemeService` that
   reads VS attributes/stages/capabilities from Azure SQL). The current constructor call omits it and
   would fail. Build `ThemeService` from the five repositories on a DB session and pass it.
2. **Multi-VS (list in, list out).** `run(er_worklet, vs_worklets: list[Worklet]) -> list[Worklet]`.
   Collect **all** VS ids from the theme stubs (not `theme_stubs[0]`), fetch all VS worklets, pass the
   list, and persist each returned worklet. The batched single LLM call for stages/description/
   capabilities across all VS is the reason it takes the list.
3. **Output = enriched VS worklets.** `to_theme_worklet` appends the generated properties onto each
   incoming VS worklet and returns it (edited in place, existing properties preserved). Persist each.
4. **ER audit trail** adds **all** vs_ids to `selected_VS_ids`.

## New imports

```python
from jwg_app.domain.services.theme_generation_handler import ThemeGenerationHandler
from jwg_app.domain.services.theme_service import ThemeService
from jwg_app.infrastructure.repositories.value_stream_repository import ValueStreamRepository
from jwg_app.infrastructure.repositories.value_stream_stage_repository import ValueStreamStageRepository
from jwg_app.infrastructure.repositories.value_stream_capability_repository import ValueStreamCapabilityRepository
from jwg_app.infrastructure.repositories.l3_capability_repository import L3CapabilityRepository
from jwg_app.infrastructure.repositories.l2_capability_repository import L2CapabilityRepository
```

## Updated method

```python
async def _generate_theme_package(
    self,
    engagement_request_id: str,
    theme_stubs: List[Worklet],
    user_info: User,
) -> List[Worklet]:
    """
    Generate Theme packages for the approved Value Streams via ThemeGenerationHandler.

    TEGApiSpec §6 - Screen 3. Endpoint: POST /api/v1/worklets/{erWorkletId}/worklets, action GENERATE.
    Each THEME worklet stub carries parentWorkletId = vsWorkletId. The handler is multi-VS: it takes
    the full list of VS worklets and batches stage/description/capability selection across them.

    Args:
        engagement_request_id: ER worklet ID (URL path param).
        theme_stubs: THEME worklet stubs from the request body (parentWorkletId = a VS worklet ID).
        user_info: Authenticated user performing the operation.

    Returns:
        The list of saved THEME worklets (one per approved Value Stream).
    """
    # Step 0 - collect ALL VS worklet ids from the stubs' parentWorkletId (deduped, order preserved)
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

    # Step 1 - fetch and validate the Engagement Request
    er_worklet = await self.get_worklet_by_id(engagement_request_id)
    er_validation = await self.validate_worklet(
        er_worklet, WorkletType.ENGAGEMENT_REQUEST, er_worklet.source_id
    )
    if er_validation:
        raise CustomException(
            status_code=er_validation["status_code"], detail=er_validation["detail"]
        )

    # Step 2 - fetch and validate EACH Value Stream worklet
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

    # Step 3 - build the SQL catalogue reader (ThemeService) and run generation (list in, list out)
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

    # Step 4 - persist each enriched THEME worklet (the handler edited the VS worklets in place)
    saved_themes: List[Worklet] = []
    for theme_worklet in theme_worklets:
        theme_worklet.current_user = user_info
        saved_themes.append(await self.upsert_worklet(theme_worklet, user_info))

    # Step 5 - update the ER worklet's selected_VS_ids audit trail with ALL value streams
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
```

## `handle_value_stream_action` - no change needed

The `GENERATE` case already passes `theme_stubs=worklets` and returns `result` - it just forwards the
list, which now flows through correctly.

## Notes / things to confirm on the prod side

- **DB session.** `ThemeService` needs the five repos on an async SQLAlchemy session. The snippet uses
  `self.session`; wire it to however `GeneratorService` holds its session (or inject `ThemeService`
  via DI like `get_theme_service`).
- **One stub vs many.** If a GENERATE request only ever carries one theme stub, this still works (a
  one-element list); the batching just has nothing to batch. If it can carry several, this now handles
  all of them in one batched call.
- **Coverage / ANALYSE** is a separate action and uses `CoverageAnalysisService` (see
  `api_integration.md` §5); it is not part of this method.
