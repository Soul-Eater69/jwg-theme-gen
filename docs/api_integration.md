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
    vs_worklets: list[Worklet],    # the approved VALUE_STREAM worklets (each has a valueStreamId property)
) -> list[Worklet]                 # a NEW THEME worklet per value stream, parented to its VS worklet
```

### How to construct it (dependency injection)

- **`azure_sql_client`** → `ThemeService`, built by the DI provider `get_theme_service(session)`
  (`jwg_app/interface/dependencies/theme.py`). It wires a `ValueStreamCatalogueRepository` to a
  SQLAlchemy `AsyncSession` from `get_db_session`; the repository runs one projected join for the
  whole catalogue and `ThemeService` assembles it. It implements the `ThemeCatalogueReader` protocol:
  `async def fetch_theme_inputs(vs_ids: Sequence[str]) -> dict[str, ValueStreamCatalogue]`.
- **`platform_client`** → the `PlatformRestClient`
  (`jwg_app/infrastructure/external/platform_rest_client.py`). The handler calls its
  `agenerate(message, model_params, output_function) -> (data, error, status_code)`.
- **`user_config_path`** → the path to `configs/user_config.yaml` (prompts + model params).

The handler takes **only** those three. LLM retry is built in (see §4) - not a constructor input.

### What it returns

A `list[Worklet]`, one **newly generated THEME** worklet per approved value stream, each parented to
its value-stream worklet. All-or-nothing: either every value stream produces a theme, or `run()`
raises (see §3). The caller persists the worklets.

---

## 2. Worklet inputs & outputs

`Worklet` is the platform envelope (`worklet_data_api.Worklet`): `id`, `source_id`, `parent_worklet_id`,
`worklet_type`, `state`, and `properties` (a list of `{ property_name, property_value }`). Property
names below are read/written exactly as shown.

### 2.1 Engagement Request (ER) worklet — input

| Read | Worklet field / property | Used for |
| --- | --- | --- |
| ticket title | property `title` | the THEME title |
| raw ticket text | property `rawText` | the only ticket input generation reads ("raw to decide") |

That's all generation reads from the ER. Summary-derived fields are **not** used.

### 2.2 VALUE_STREAM worklets — input

`run` takes the **list of approved VALUE_STREAM worklets** (one per value stream) and generates a
theme for every one in a single call. From **each** VS worklet, two things are read:

| Read (per VS worklet) | Worklet field |
| --- | --- |
| value-stream id (e.g. `VS10000372`) | `valueStreamId` **property** (the catalogue lookup key) |
| the VS worklet's own id | `id` (becomes the generated theme's `parentWorkletId`) |

**Only the `valueStreamId` property and the worklet `id`.** Name, description, value proposition,
trigger, stages, and capabilities all come from SQL (the catalogue), keyed by the `valueStreamId`.
Nothing is written back onto the VS worklet.

### 2.3 Output — a newly generated THEME worklet per value stream

`run` **creates** a new THEME worklet for each value stream (it does not edit the input). Each
generated worklet has:

| Field | Value |
| --- | --- |
| `workletType` | `THEME` |
| `parentWorkletId` | the value-stream worklet's `id` |
| `sourceId` | carried down from the value-stream worklet |
| `properties` | the seven generated properties below |

Written properties:

| Property written | Value |
| --- | --- |
| `title` | `"<ticket title> - <value stream name>"` |
| `description` | the value stream's framing paragraph over the shared body |
| `businessNeeds` | the Business Needs document (text; structure is inside the text) |
| `generatedByLLM` | `true` |
| `selectedStages` | list of selected stages (see type below) |
| `l3BusinessCapability` | list of selected L3 capabilities |
| `l2BusinessCapability` | list of derived L2 capabilities |

### Example — the properties written onto one theme worklet

```json
[
  { "propertyName": "title",          "propertyValue": "CareWay+ commercial claims activation - Claims Adjudication" },
  { "propertyName": "description",    "propertyValue": "Under Claims Adjudication, ... <framing> ... <shared body> ..." },
  { "propertyName": "businessNeeds",  "propertyValue": "Eligibility Determination\n- The plan must ... <needs document> ..." },
  { "propertyName": "generatedByLLM", "propertyValue": true },
  { "propertyName": "selectedStages", "propertyValue": [
      { "stageId": "VSS00074614", "stageName": "Eligibility Determination",
        "stageDescription": "Determine member eligibility for the claim",
        "entranceCriteria": "claim registered", "exitCriteria": "eligibility decided",
        "reason": "the ticket adjudicates CareWay+ members' claims, which runs through eligibility" }
  ] },
  { "propertyName": "l3BusinessCapability", "propertyValue": [
      { "id": "CAP00000097", "name": "Eligibility Check", "description": "Verify member eligibility",
        "stageId": "VSS00074614", "levelTwoId": "CAP00000036" }
  ] },
  { "propertyName": "l2BusinessCapability", "propertyValue": [
      { "id": "CAP00000036", "name": "Claim Adjudication", "description": "..." }
  ] }
]
```

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
| `503` | LLM output failed schema validation after retries |
| `400` | A value stream resolved no stages (defensive; not expected for an approved value stream) |

LLM retry (before a `503`): transient statuses `429, 502, 503, 504` are retried; `400/401/403/404/500`
fail fast. A 200 whose body fails schema validation is also retried (see §4).

---

## 4. LLM retry + strict output (built in)

Nothing to pass - both are inside the handler:

- **Strict structured output.** Every LLM call is sent with a strict `response_format` (constrained
  decoding), so the model is forced to match the schema - it cannot rename, omit, or mistype a field.
  Built from the call's schema; no config needed.
- **Transport retry.** Transient gateway failures (`429, 502, 503, 504`) are retried; `400/401/403/
  404/500` fail fast. Defaults (`RetryConfig` in
  `jwg_app/infrastructure/external/retry_config.py` - shared, reusable by other LLM-calling modules):
  3 attempts, ~1s fixed delay + jitter (not exponential).
- **Validation retry.** A `200` whose body does not match the schema (or is malformed JSON) is
  re-sampled, up to the same attempt count, before surfacing a `503`. Strict output makes this rare;
  it is the backstop for when the gateway does not honor strict.

To change either policy, edit the `RetryConfig` defaults.

---

## 5. Coverage analysis

Scores how well the generated themes cover the ER's raw text. Run **after** generation; the result is
upserted as an `analysis` property on the **ER** worklet.

### Entry point

```python
CoverageAnalysisService(evaluator: CoverageEvaluator | None = None)   # default loads NgramEvaluator

# Worklet in -> the same worklet out (preferred): reads the context off the ER, scores the themes,
# attaches the JSON-ready ``analysis`` property on the ER worklet in place, and returns it.
def analyze_worklet(
    *, er_worklet: Worklet,                # the ANALYSE source (Engagement Request) worklet
    themes: list[Worklet],                 # the generated THEME worklets
    n: int = 1,
    remove_stopwords: bool = True,
    coverage_color: Any = "green",
    creativity_color: Any = "orange",
) -> Worklet                              # the same er_worklet, with the "analysis" property attached

# Lower-level (text in -> scores out), if you already hold the raw text:
def analyze(*, raw_text: str, themes: list[Worklet], ...) -> list[dict]   # one dict per metric, serialized
def analysis_property(result: list) -> dict   # -> the worklet "analysis" property (JSON-safe)
```

### Context source (what the themes are scored against)

`analyze_worklet` scores the themes against the ER worklet's **`rawText`** property only — the raw
ticket text generation was grounded on. There is no fallback; the ANALYSE payload must carry
`rawText`. On the generated side, only the theme **`description`** and **`businessNeeds`** texts are
scored — nothing else.

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

Like theme generation, this is an **append/upsert**: the caller adds (or overwrites) the single
`analysis` property on the **ER** worklet's existing properties - it does not replace the ER's other
properties.

---

## 6. Types reference

Domain models (`jwg_app/domain/models/theme_generation.py`). The list-property values above are these,
serialized with `model_dump()` (camelCase on the wire).

**`selectedStages`** entries

| field | type | notes |
| --- | --- | --- |
| `stageId` | str | the catalogue stage id (VSS…) — the Jira Epic |
| `stageName` | str | canonical catalogue name |
| `stageDescription` | str | catalogue scope |
| `entranceCriteria` / `exitCriteria` | str | catalogue scope |
| `reason` | str | the model's grounding — why the work falls in this stage |

**`L3Capability`** (`l3BusinessCapability` entries) — the list holds the selected capabilities only

| field | type | notes |
| --- | --- | --- |
| `id` | str | L3 capability id (CAP…) |
| `name` / `description` | str | |
| `stageId` | str | the stage this L3 belongs to |
| `levelTwoId` | str | parent L2 id — the link; the L2's name/description live on the `l2BusinessCapability` entry, not duplicated here |

**`L2Capability`** (`l2BusinessCapability` entries) — the deduped L2 rollup of the selected L3

| field | type | notes |
| --- | --- | --- |
| `id` | str | L2 capability id (CAP…) |
| `name` / `description` | str | |

No stage/L3 link on L2 — one L2 can parent L3s across several stages, so it carries only its own
id/name/description; the L2↔L3↔stage links live on each L3 entry (`levelTwoId` + `stageId`).

**`ValueStreamCatalogue`** (what `ThemeCatalogueReader.fetch_theme_inputs` returns per VS) — internal
to generation; the API team does not build it (the `ThemeService` does). It holds
`value_stream` (name, description, value proposition, trigger), `stage_list`, and `l3_capabilities`.

---

## 7. Minimal call sequence (backend)

```python
# theme generation (per ANALYSE/GENERATE request)
catalogue = await get_theme_service(session)                     # ThemeCatalogueReader
handler = ThemeGenerationHandler(catalogue, platform_client, USER_CONFIG_PATH)
themes = await handler.run(er_worklet, vs_worklets)            # new THEME worklets per VS; raises on failure
# persist `themes`

# coverage (after generation, on the ER) - worklet in, the same worklet out
service = CoverageAnalysisService()                              # default NgramEvaluator
er_worklet = service.analyze_worklet(er_worklet=er_worklet, themes=themes)  # "analysis" attached in place
# update + commit the ER worklet
```
