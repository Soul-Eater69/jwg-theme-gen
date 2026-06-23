# Theme Generation — Worklet Contract

How the theme generation handler reads its input worklets and shapes its output worklet. All
worklet ↔ domain translation lives in `jwg_app/domain/services/theme/worklet_mapper.py`; the property
names below are the only coupling to the worklet shape and are defined there as class-namespaced
constants (`ERProps`, `DocsSummaryKeys`, `VSProps`, `ThemeProps`).

`ThemeGenerationHandler.run(er_worklet, vs_worklets)` takes one engagement-request worklet and the
list of approved VALUE_STREAM worklets (one per value stream; each carries a `valueStreamId` property
= the VS id), and **generates** a new THEME worklet per value stream, parented to its VS worklet.

---

## 1. Engagement Request (ER) worklet — input

Read by `to_er_context`. Generation grounds on the **raw ticket text only** ("raw to decide").

| Domain field (`ERContext`) | Worklet source | Property name |
| --- | --- | --- |
| `idmt_ticket_title` | property | `title` |
| `raw_text` | property | `rawText` |

That is the entire ER input — two properties, `title` and `rawText`. `raw_text` is the raw ticket
text generation reads ("raw to decide"). Summary-derived fields (`businessProblem`,
`businessCapability`, `keyTerms`, `stakeholders`, `systemsAndProducts`) are **not** used by
generation — per the prompt I/O contract, the prompts read raw text only; the summary is a separate
retrieval artifact.

---

## 2. VALUE_STREAM worklet — input

One VS worklet per approved value stream. **The worklet supplies the value-stream id** via its
`valueStreamId` **property** (e.g. `VS10000372`) — the catalogue key — and its own `id`, which becomes
the generated theme's `parentWorkletId`. Every other attribute comes from the governed SQL catalogue
(the single source of truth), keyed by the `valueStreamId`.

| Domain field (`VSContext`) | Source | Property / catalogue field |
| --- | --- | --- |
| `vs_id` | **stub property** | `valueStreamId` — the VS id used to look up the catalogue |
| `vs_name` | **SQL catalogue** | `value_stream_name` |
| `vs_description` | **SQL catalogue** | `value_stream_description` |
| `value_proposition` | **SQL catalogue** | `value_stream_value_proposition` |
| `trigger` | **SQL catalogue** | `value_stream_trigger` |

So the stub only needs to carry the **`valueStreamId`** property (the catalogue join key). Name,
description, value proposition, trigger, stages, and L3/L2 capabilities all come from SQL — see the
catalogue service (`ThemeService` / `ValueStreamCatalogue`).

### VS fields used per prompt

`ticket_context` (raw text + ER signals) goes to every prompt. The VS fields are used as follows:

| VS field | description_body | framing | stage_selection | capability_selection | business_needs |
| --- | :--: | :--: | :--: | :--: | :--: |
| `vs_id` | — | ✓ | ✓ | ✓ | ✓ |
| `vs_name` | — | ✓ | ✓ | ✓ | ✓ |
| `vs_description` | — | ✓ | ✓ | ✓ | ✓ |
| `value_proposition` | — | ✓ | ✓ | ✓ | ✓ |
| `trigger` | — | ✗ | ✓ | ✓ | ✗ |

- `description_body` is VS-agnostic on purpose: it is generated once for the ticket and reused across
  every VS theme; the per-VS framing paragraph (which does get VS fields) is prepended to it.
- `trigger` is included in framing, stage selection, and capability selection; it is omitted only
  from business needs. This is a soft tuning choice, not a hard rule.

---

## 3. Output — a generated THEME worklet per value stream

`to_theme_worklet` **creates a new THEME worklet** for each value stream: `workletType = THEME`,
`parentWorkletId =` the VS worklet's `id`, `sourceId` carried down from the VS worklet, and the seven
generated properties below. The input VS worklet is not modified.

**Properties written**

| Property name | Content |
| --- | --- |
| `title` | `"<idmt ticket title> - <vs name>"` |
| `description` | per-VS framing paragraph over the shared body |
| `businessNeeds` | the Business Needs text for this value stream |
| `generatedByLLM` | `True` |
| `selectedStages` | selected stages (`SelectedStage.model_dump()`: id, name, scope, reason) |
| `l3BusinessCapability` | selected L3 capabilities (`L3Capability.model_dump()`, incl. description) |
| `l2BusinessCapability` | derived L2 capabilities (`L2Capability.model_dump()`, incl. description) |

Example of the written properties:

```json
[
  { "propertyName": "title",          "propertyValue": "CareWay+ commercial claims activation - Claims Adjudication" },
  { "propertyName": "description",    "propertyValue": "<framing paragraph over the shared body>" },
  { "propertyName": "businessNeeds",  "propertyValue": "<Business Needs document text>" },
  { "propertyName": "generatedByLLM", "propertyValue": true },
  { "propertyName": "selectedStages", "propertyValue": [
      { "stageId": "VSS00074614", "stageName": "Eligibility Determination",
        "stageDescription": "...", "entranceCriteria": "...", "exitCriteria": "...",
        "reason": "<why the work falls in this stage>" }
  ] },
  { "propertyName": "l3BusinessCapability", "propertyValue": [
      { "id": "CAP00000097", "name": "Eligibility Check", "description": "...",
        "stageId": "VSS00074614", "levelTwoId": "CAP00000036" }
  ] },
  { "propertyName": "l2BusinessCapability", "propertyValue": [
      { "id": "CAP00000036", "name": "Claim Adjudication", "description": "..." }
  ] }
]
```

---

## Failure handling

Generation is **all-or-nothing**: `run()` returns `list[Worklet]` (one theme per value stream) only
when *every* value stream succeeds; otherwise it raises `CustomException` and returns nothing. There
are no partial results and no per-theme failure flags - the UI either shows the full set or a clean
error, which is the right contract when failed themes aren't surfaced in the UI and there is no
per-theme regeneration.

Every value stream is attempted, and each LLM call retried (429 / 5xx / timeout, per the theme retry
config), **before** the request fails. Every error is logged (`logger.error`) before it surfaces, so
an aborted request is traceable in the logs as well as the response.

### Error reference

| Status | Condition |
| --- | --- |
| `404` | ER worklet or VS worklet not found |
| `503` | Azure SQL service unavailable |
| `503` | LLM service unavailable after retries (description body/framing, stage selection, capabilities, or any value stream's business needs) |
| `400` | A value stream resolved no stages (defensive; not expected, since an approved value stream has governed stages) |

Note: when the LLM selects no stage for a value stream, the resolver falls back to all of that value
stream's catalogue stages (not a failure). Retryable before the above: `429`, `502`, `503`, `504`.
Not retried (fail fast): `400`, `401`, `403`, `404`, `500` (the gateway folds real bugs into `500`).

---

## Notes / assumptions

- **VS worklet contract:** the worklet is assumed to provide `title` and `valueStreamDescription`. If
  that ever changes to an id-only worklet, source `vs_name` / `vs_description` from the SQL VS table
  (`value_stream_name` / `value_stream_description`) instead — the catalogue already reads that table.
- **`vs_id` source:** `source_id` falls back to `id`. This is the SQL join key, so it must be the VSR
  id of the approved value stream.
- All output property names are camelCase (`businessNeeds`, `l3BusinessCapability`,
  `l2BusinessCapability`, …) — the worklet contract sends camelCase only.
