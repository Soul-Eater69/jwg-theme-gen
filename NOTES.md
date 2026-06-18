# Theme Generation — staging for `idp-user-story-gen-api` / `jwg_app`

A copy-paste-ready slice mirroring the prod `jwg_app/` paths. Implements the
`ThemeGenerationHandler` (LLD §8.3): given the ER worklet and the approved Value Stream
worklets, it returns one THEME worklet per Value Stream.

## Layout
```
jwg_app/
  domain/
    interfaces/
      platform_client.py            # PlatformClient Protocol (structured-output call)
      theme_catalogue.py            # ThemeCatalogueReader Protocol (governed-catalogue read)
    models/
      theme_generation.py           # data models + LLM output schemas
      worklet.py                    # Worklet envelope + property accessors (staging; swap for prod import)
    services/
      theme_generation_handler.py   # the handler (orchestration only)
      theme_generation_helper.py    # pure render/resolve helpers
      prompts/
        loader.py
        theme/{stage_selection,capability_selection,business_needs}.yaml
  infrastructure/external/          # azure_sql_client.py (TODO)
  interface/dependencies/           # generator.py DI wiring (TODO)
```

## Design
- **SRP** — orchestration (handler), pure rendering/resolution (helper), data contracts (models) are separated.
- **DIP / ISP** — the handler depends on the `PlatformClient` and `ThemeCatalogueReader` Protocols, injected
  via the constructor; each Protocol declares only the one method the handler uses. Unit-testable with fakes;
  the handler never persists.
- `run(er_worklet, vs_worklets)` resolves the ER context once and fans the per-VS pipelines out in parallel.
  Execution order per VS: stages ∥ description → business needs ∥ L3 → derive L2 → assemble.

## Implemented & smoke-tested (injected fakes, no network)
- `run` (list in → list out), `_predict_stages`, `_generate_business_needs`, `_generate_l3_capabilities`,
  `_derive_l2_capabilities`, `_assemble_theme_worklet`, the ER/VS worklet → context mappers, and the
  `_complete` adapter over `platform_client.agenerate`.
- Worklet property values serialize camelCase (`stageId`, `levelTwoId`, `llmSelected`).
- The full property contract (reads + the 8 THEME writes) is centralized at the top of the handler.

## TODO
- **`_generate_theme_description`** — the per-VS theme description (overview + structured body sections);
  prompt + output shape to be agreed, then wired.
- **`azure_sql_client`** — concrete `ThemeCatalogueReader` (`fetch_theme_inputs(vs_id) -> AzureSQLData`).
- **`generator.py`** — DI wiring (factory for the handler).
- **Prompt strings** — the two prompts (`stage_selection`, `capability_selection`) want the standard
  wording pass applied (input labelled "content"; no internal jargon).

## Reconcile on integration
- The Worklet property-name strings (centralized in the handler) — confirm they match the ER/VS worklets.
- ER mapping: `generated_summary` is filled from the worklet's `rawText` (generation reads raw text).
- VS enrichment (`valueProposition`/`trigger`/`assumptions`) is not sourced from the worklet today; the
  prompts simply omit those lines when absent.
