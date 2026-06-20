# Theme Generation & Coverage — API Integration Guide

Everything the API/backend team needs to call theme generation and coverage analysis: entry points,
the functions to call, the types, the worklet inputs/outputs, and the errors. The handler and
service contain no API/HTTP code - the backend constructs them (via DI), calls one method, and
persists/returns the result.

Related: [worklet_contract.md] (worklet field detail), [prompt_io.md] (LLM I/O),
[coverage_analysis.md] (coverage internals).

---

## 1. Theme generation

### Entry point

```python
ThemeGenerationHandler(
    azure_sql_client: ThemeCatalogueReader,   # the catalogue reader (ThemeService)
    platform_client:  PlatformClient,         # the LLM client (PlatformRestClient)
    user_config_path: str,                    # path to configs/user_config.yaml
)

async def run(
    er_worklet:  Worklet,          # the Engagement Request worklet
    vs_worklets: list[Worklet],    # ALL approved Value Stream worklets (themes generated together)
) -> list[Worklet]                 # one unsaved THEME worklet per value stream
```

### How to construct it (dependency injection)

- **`azure_sql_client`** → `ThemeService`, built by the DI provider `get_theme_service(session)`
  (`jwg_app/interface/dependencies/theme.py`). It wires the five repositories to a SQLAlchemy
  `AsyncSession` from `get_db_session`. It implements the `ThemeCatalogueReader` protocol:
  `async def fetch_theme_inputs(vs_ids: Sequence[str]) -> dict[str, ValueStreamCatalogue]`.
- **`platform_client`** → the prod `PlatformRestClient`
  (`jwg_app/infrastructure/external/platform_rest_client.py`). The handler calls its
  `agenerate(message, model_params, output_function) -> (data, error, status_code)`.
- **`user_config_path`** → the path to `configs/user_config.yaml` (prompts + model params).

The handler takes **only** those three. LLM retry is built in (see §4) - not a constructor input.

### What it returns

A `list[Worklet]`, one **THEME** worklet per approved value stream. All-or-nothing: either every
value stream produces a theme, or `run()` raises (see §3). The caller persists the worklets.

---

## 2. Worklet inputs & outputs

`Worklet` is the prod envelope (`worklet_data_api.Worklet`): `id`, `source_id`, `parent_worklet_id`,
`worklet_type`, `state`, and `properties` (a list of `{ property_name, property_value }`). Property
names below are read/written exactly as shown.

### 2.1 Engagement Request (ER) worklet — input

| Read | Worklet field / property | Used for |
| --- | --- | --- |
| ticket title | property `title` | the THEME title |
| raw ticket text | property `rawText` | the only ticket input generation reads ("raw to decide") |

That's all generation reads from the ER. Summary-derived fields are **not** used.

### 2.2 Value Stream (VS) worklets — input

`run` takes the **list of all approved VS worklets** and generates every theme in one call. From
**each** worklet in the list, only the id is read:

| Read (per VS worklet) | Worklet field |
| --- | --- |
| value-stream id (VSR…) | `source_id` (falls back to `id`) |

**Only the id.** Name, description, value proposition, trigger, stages, and capabilities all come
from SQL (the catalogue), keyed by that id. Any other properties on the VS worklets are ignored.

### 2.3 THEME worklet — output (one per value stream)

Envelope: `worklet_type = THEME`, `parent_worklet_id = <vs worklet id>`, `state = CREATED`,
`id`/`source_id = None` (assigned on persist).

| Property name | Value |
| --- | --- |
| `title` | `"<ticket title> -- <value stream name>"` |
| `description` | the value stream's framing paragraph over the shared body |
| `Business Needs` | the Business Needs document (text; structure is inside the text) |
| `generatedByLLM` | `true` |
| `selectedStages` | list of selected stages (see type below) |
| `L3 Business Capability` | list of selected L3 capabilities |
| `L2 Business Capability` | list of derived L2 capabilities |

---

## 3. Errors (theme generation)

`run()` raises `CustomException(status_code, detail)` (`jwg_app/domain/exceptions/custom_exception.py`).
Every error is logged (`logger.error`) before it surfaces. Generation is all-or-nothing - any failure
aborts the whole request.

| Status | Condition |
| --- | --- |
| `404` | ER worklet or VS worklet not found (missing/empty input) |
| `503` | Azure SQL service unavailable |
| `503` | LLM service unavailable after retries (any of: description body/framing, stage selection, capabilities, a value stream's business needs) |
| `400` | A value stream resolved no stages (defensive; not expected for an approved value stream) |

LLM retry (before a `503`): transient statuses `429, 502, 503, 504` are retried; `400/401/403/404/500`
fail fast.

---

## 4. LLM retry (built in)

Transient gateway failures are retried automatically inside the handler - nothing to pass. Defaults
(`RetryConfig` in `jwg_app/domain/services/theme/config.py`): 3 attempts, ~1s fixed delay + jitter
(not exponential), retrying only `429, 502, 503, 504`. After the attempts are exhausted the call
surfaces a `503`. To change the policy, edit the `RetryConfig` defaults.

---

## 5. Coverage analysis

Scores how well the generated themes cover the ER's raw text. Run **after** generation; the result is
upserted as an `analysis` property on the **ER** worklet.

### Entry point

```python
CoverageAnalysisService(evaluator: CoverageEvaluator | None = None)   # default loads NgramEvaluator

def analyze(
    *, raw_text: str,
    themes: list[Worklet],                 # the generated THEME worklets
    n: int = 1,
    remove_stopwords: bool = True,
    coverage_color: Any = "green",
    creativity_color: Any = "orange",
) -> list                                  # one entry per metric (Coverage, Creativity)

def analysis_property(result: list) -> dict   # -> the worklet "analysis" property (JSON-safe)
```

### Output — the `analysis` property

`analysis_property(analyze(...))` returns the property to upsert on the ER worklet:

```json
{
  "propertyName": "analysis",
  "propertyValue": [
    { "metric_name": "Coverage",   "metric_value": { "score": 0.78, "highlighted_text": "<span style='background-color: green'>...</span> ..." } },
    { "metric_name": "Creativity", "metric_value": { "score": 0.42, "scores": [0.35, 0.50, 0.41],
        "highlighted_text": [ [ { "propertyName": "title", "propertyValue": "... <span style='background-color: orange'>...</span>" },
                                { "propertyName": "description", "propertyValue": "..." } ] ] } }
  ]
}
```

`Metric` objects are serialized to plain dicts automatically (`_to_jsonable`), so the property drops
straight into the API JSON. Requires the `text_evaluation.ngram_evaluation.NgramEvaluator` package and
NLTK `stopwords`/`punkt` data on the path.

---

## 6. Types reference

Domain models (`jwg_app/domain/models/theme_generation.py`). The list-property values above are these,
serialized with `model_dump()` (camelCase on the wire).

**`SelectedStage`** (`selectedStages` entries)

| field | type | notes |
| --- | --- | --- |
| `stageId` | str | the catalogue stage id (VSS…) — the Jira Epic |
| `stageName` | str | canonical catalogue name |
| `stageDescription` | str | catalogue scope |
| `entranceCriteria` / `exitCriteria` | str | catalogue scope |
| `reason` | str | the model's justification |

**`L3Capability`** (`L3 Business Capability` entries)

| field | type | notes |
| --- | --- | --- |
| `id` | str | L3 capability id (CAP…) |
| `name` / `description` | str | |
| `stageId` | str | the stage this L3 belongs to |
| `levelTwoId` / `levelTwoName` | str | parent L2 |
| `llmSelected` | bool | set by the model, immutable |
| `selected` | bool | starts = `llmSelected`; user toggles via upsert |

**`L2Capability`** (`L2 Business Capability` entries)

| field | type | notes |
| --- | --- | --- |
| `id` | str | L2 capability id (CAP…) |
| `name` / `description` | str | |
| `stageId` | str | |
| `selected` | bool | `true` on derivation; user toggles via upsert |

**`ValueStreamCatalogue`** (what `ThemeCatalogueReader.fetch_theme_inputs` returns per VS) — internal
to generation; the API team does not build it (the `ThemeService` does). It holds
`value_stream` (name, description, value proposition, trigger), `stage_list`, and `l3_capabilities`.

---

## 7. Minimal call sequence (backend)

```python
# theme generation (per ANALYSE/GENERATE request)
catalogue = await get_theme_service(session)                     # ThemeCatalogueReader
handler = ThemeGenerationHandler(catalogue, platform_client, USER_CONFIG_PATH)
themes = await handler.run(er_worklet, vs_worklets)              # list[Worklet]; raises on failure
# persist `themes`

# coverage (after generation, on the ER)
service = CoverageAnalysisService()                              # default NgramEvaluator
result = service.analyze(raw_text=er_raw_text, themes=themes)
er_worklet.set_property("analysis", service.analysis_property(result)["propertyValue"])
# update + commit the ER worklet
```
