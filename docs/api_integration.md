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

A `list[Worklet]`, one THEME worklet per approved value stream, each parented to its value-stream
worklet. Each is **either** a generated theme worklet **or** a **failure worklet** carrying a
`generationError` property (see §2.4). A shared-call failure (description body/framing, stage or
capability selection) makes **every** value stream a failure worklet, since no theme can be built
without that shared data; a per-value-stream failure (business needs unavailable, or no stages
resolved) makes **only that** value stream a failure worklet and the rest are returned as normal
themes. `run()` itself only raises when there is nothing to return (see §3). The caller persists the
worklets and can split them on the presence of `generationError`.

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
| `businessValueStream` | property — **carried over** onto the theme worklet as-is |

**The `valueStreamId` property, the worklet `id`, and `businessValueStream`.** Name, description, value
proposition, trigger, stages, and capabilities all come from SQL (the catalogue), keyed by the
`valueStreamId`. Nothing is written back onto the VS worklet.

### 2.3 Output — a newly generated THEME worklet per value stream

`run` **creates** a new THEME worklet for each value stream (it does not edit the input). Each
generated worklet has:

| Field | Value |
| --- | --- |
| `workletType` | `THEME` |
| `parentWorkletId` | the value-stream worklet's `id` |
| `sourceId` | carried down from the value-stream worklet |
| `properties` | the eight properties below (`businessValueStream` is carried from the VS worklet; the rest are generated) |

Written properties:

| Property written | Value |
| --- | --- |
| `businessValueStream` | carried over from the VS worklet (e.g. `"Acquire Asset {VSR00074583}"`) |
| `summary` | `"<ticket title> - <value stream name>"` |
| `description` | the value stream's framing paragraph over the shared body |
| `businessNeeds` | the Business Needs document (text; structure is inside the text) |
| `generatedByLLM` | `true` |
| `selectedStages` | `{ stageId: "stageName {stageId}" }` map (key = stage id) |
| `l3BusinessCapabilityModel` | `{ capId: "name {capId}" }` map (key = L3 cap id) |
| `l2BusinessCapabilityModel` | `{ capId: "name {capId}" }` map (key = L2 cap id) |

`selectedStages`, `l3BusinessCapabilityModel`, and `l2BusinessCapabilityModel` are **objects (maps)**,
not lists: the key is the catalogue id and the value is `"<name> {<id>}"`.

### Example — the properties written onto one theme worklet

```json
[
  { "propertyName": "businessValueStream", "propertyValue": "Acquire Asset {VSR00074583}" },
  { "propertyName": "summary",        "propertyValue": "CareWay+ commercial claims activation - Claims Adjudication" },
  { "propertyName": "description",    "propertyValue": "Under Claims Adjudication, ... <framing> ... <shared body> ..." },
  { "propertyName": "businessNeeds",  "propertyValue": "Eligibility Determination\n- The plan must ... <needs document> ..." },
  { "propertyName": "generatedByLLM", "propertyValue": true },
  { "propertyName": "selectedStages", "propertyValue": {
      "VSS00074614": "Eligibility Determination {VSS00074614}"
  } },
  { "propertyName": "l3BusinessCapabilityModel", "propertyValue": {
      "CAP00000364": "Account Analytics and Reporting {CAP00000364}",
      "CAP00000220": "Account Association Management {CAP00000220}"
  } },
  { "propertyName": "l2BusinessCapabilityModel", "propertyValue": {
      "CAP00000036": "Claim Adjudication {CAP00000036}"
  } }
]
```

### 2.4 Output — a failure worklet (when a value stream could not be generated)

A value stream whose theme could not be generated comes back as a THEME worklet too (same envelope,
parented to its VS worklet), but the generated content is replaced by a single `generationError`
property. The caller tells the two apart by the presence of `generationError`.

| Field | Value |
| --- | --- |
| `workletType` | `THEME` |
| `parentWorkletId` | the value-stream worklet's `id` |
| `sourceId` | carried down from the value-stream worklet |
| `businessValueStream` | carried over from the VS worklet (so the failed row is still labelled) |
| `generationError` | the error detail text (a string) |

```json
[
  { "propertyName": "businessValueStream", "propertyValue": "Acquire Asset {VSR00074583}" },
  { "propertyName": "generationError",     "propertyValue": "LLM service unavailable: needs gateway down" }
]
```

When a **shared** call fails, every value stream comes back like this; when a **per-value-stream**
call fails (business needs, or no stages), only that value stream does.

---

## 3. Errors (theme generation)

`run()` only **raises** `CustomException(status_code, detail)`
(`jwg_app/domain/exceptions/custom_exception.py`) for failures that leave nothing to return. LLM-call
failures do **not** raise - they come back as failure worklets (§2.4). Every error is logged
(`logger.error`) before it surfaces.

| Outcome | Condition |
| --- | --- |
| raises `404` | ER worklet or VS worklet not found (missing/empty input) |
| raises `503` | Azure SQL service unavailable |
| failure worklet(s) | LLM service unavailable or output failed schema validation. A shared call (description body/framing, stage or capability selection) fails **every** value stream; business needs fails **only** that value stream. |
| failure worklet | A value stream resolved no stages (defensive; not expected for an approved value stream) |

There is no retry: each LLM call is made once. Any non-200 status, missing data, or schema-validation
failure becomes a `generationError` (or raises, for Azure SQL) immediately (see §4).

---

## 4. Strict structured output (built in)

Nothing to pass - it is inside the handler:

- **Strict structured output.** Every LLM call is sent with a strict `response_format` (constrained
  decoding), so the model is forced to match the schema - it cannot rename, omit, or mistype a field.
  Built from the call's schema; no config needed.
- **No retry.** Each call is made once. Strict decoding is the only guard; a gateway failure or a
  body that still fails schema validation surfaces a `503` (no transport or validation re-sampling).

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

`Metric` objects are serialized to plain dicts automatically (via each metric's `as_dict()`), so the property drops
straight into the API JSON. Requires the `text_evaluation.ngram_evaluation.NgramEvaluator` package and
NLTK `stopwords`/`punkt` data on the path.

Like theme generation, this is an **append/upsert**: the caller adds (or overwrites) the single
`analysis` property on the **ER** worklet's existing properties - it does not replace the ER's other
properties.

---

## 6. Types reference

`selectedStages`, `l3BusinessCapabilityModel`, and `l2BusinessCapabilityModel` are all the **same map
shape**:

```json
{ "<catalogue id>": "<name> {<catalogue id>}" }
```

| Property | key | value |
| --- | --- | --- |
| `selectedStages` | stage id (VSS…) | `"<stageName> {<stageId>}"` |
| `l3BusinessCapabilityModel` | L3 cap id (CAP…) | `"<l3Name> {<l3Id>}"` |
| `l2BusinessCapabilityModel` | L2 cap id (CAP…) | `"<l2Name> {<l2Id>}"` |

The L2↔L3↔stage relationships are not stored on these maps; they are recoverable from the catalogue
(each stage's L3s, each L3's parent L2). One L2 can roll up L3s from several stages.

**`ValueStreamCatalogue`** (what `ThemeCatalogueReader.fetch_theme_inputs` returns per VS) — internal
to generation; the API team does not build it (the `ThemeService` does). It holds
`value_stream` (name, description, value proposition, trigger), `stage_list`, and `l3_capabilities`.

---

## 7. Minimal call sequence (backend)

```python
# theme generation (per ANALYSE/GENERATE request)
catalogue = await get_theme_service(session)                     # ThemeCatalogueReader
handler = ThemeGenerationHandler(catalogue, platform_client, USER_CONFIG_PATH)
themes = await handler.run(er_worklet, vs_worklets)            # one THEME worklet per VS (success or generationError)
# persist `themes`; a worklet with a `generationError` property is a failed value stream

# coverage (after generation, on the ER) - worklet in, the same worklet out
service = CoverageAnalysisService()                              # default NgramEvaluator
er_worklet = service.analyze_worklet(er_worklet=er_worklet, themes=themes)  # "analysis" attached in place
# update + commit the ER worklet
```
