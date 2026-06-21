# `generator_service.py` — changes for the multi-VS theme handler

The prod `GeneratorService._generate_theme_package` must change to match `ThemeGenerationHandler`'s
current contract. Paste the updated method below into prod's `generator_service.py`. (This file is
prod-only and not in this repo, so this is a reference, not a compiled drop-in - adapt the session /
helper calls to your actual wiring.)

> **The full, current method lives in `jwg_app/domain/services/generator_service.py`** (the partial
> reference in this repo). That is the authoritative copy — use it. This doc is just the summary of
> what changed and the DI wiring.

## What changed vs the current method

1. **Inject the catalogue reader.** The handler now needs `azure_sql_client` (a `ThemeService` that
   reads VS attributes/stages/capabilities from Azure SQL). The current constructor call omits it and
   would fail. Inject `ThemeService` into `GeneratorService` via DI (see below) and pass it.
2. **Multi-VS (list in, list out).** `run(er_worklet, theme_stubs: list[Worklet]) -> list[Worklet]`.
   Collect **all** VS ids from the stubs' **`valueStreamId` property** (not `theme_stubs[0]`, not
   `parentWorkletId`), validate each VS exists, pass the stub list, and persist each returned stub.
   The batched single LLM call for stages/description/capabilities across all VS is why it takes the list.
3. **Output = enriched THEME stubs.** `to_theme_worklet` attaches the generated properties onto each
   incoming THEME stub and returns it (edited in place, existing properties preserved). Persist each.
4. **ER audit trail** adds **all** vs_ids to `selected_VS_ids`.

## DI wiring (matches the prod `get_value_stream_service` pattern)

`ThemeService` is **injected** into `GeneratorService` via DI - not built inline. The provider chain
is `get_db_session -> repositories -> ThemeService`, exactly like value streams. `get_theme_service`
already exists (`interface/dependencies/theme.py`); add it to the generator's provider:

```python
# interface/dependencies/generator.py
from jwg_app.interface.dependencies.theme import get_theme_service

async def get_generator_service(
    ...,
    theme_service: ThemeService = Depends(get_theme_service),
) -> GeneratorService:
    return GeneratorService(..., theme_service=theme_service)
```

Then `_generate_theme_package` uses `self.theme_service` (no repos/session imports in the service).

## New import

```python
from jwg_app.domain.services.theme_generation_handler import ThemeGenerationHandler
```

## Updated method

See `jwg_app/domain/services/generator_service.py` for the full, current `_generate_theme_package` (and the GENERATE case of `handle_value_stream_action`). It reads each stub's `valueStreamId` property, validates each VS exists, runs the handler on the stubs, persists each enriched stub, and updates the ER audit trail.

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
