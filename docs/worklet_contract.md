# Theme Generation — Worklet Contract

How the theme generation handler reads its input worklets and shapes its output worklet. All
worklet ↔ domain translation lives in `jwg_app/domain/services/theme/worklet_mapper.py`; the property
names below are the only coupling to the worklet shape and are defined there as class-namespaced
constants (`ERProps`, `DocsSummaryKeys`, `VSProps`, `ThemeProps`).

`ThemeGenerationHandler.run(er_worklet, vs_worklets)` takes one engagement-request worklet and the
list of approved value-stream worklets, and returns one unsaved **THEME** worklet per value stream.

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

## 2. Value Stream (VS) worklet — input

Read by `to_vs_context`. **The worklet supplies only the value-stream id**; every other attribute
comes from the governed SQL catalogue (the single source of truth), keyed by that id.

| Domain field (`VSContext`) | Source | Property / catalogue field |
| --- | --- | --- |
| `vs_id` | **worklet** identity | `source_id` (fallback `id`) — the VSR id used to look up the catalogue |
| `vs_name` | **SQL catalogue** | `value_stream_name` |
| `vs_description` | **SQL catalogue** | `value_stream_description` |
| `value_proposition` | **SQL catalogue** | `value_stream_value_proposition` |
| `trigger` | **SQL catalogue** | `value_stream_trigger` |

So the VS worklet only needs to carry the **`vs_id`** (the catalogue join key). Name, description,
value proposition, trigger, stages, and L3/L2 capabilities all come from SQL — see the catalogue
service (`ThemeService` / `ValueStreamCatalogue`).

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

## 3. Output — the enriched VS worklets

`to_theme_worklet` **edits the incoming VS worklet in place**: it appends the generated properties to
the worklet's existing properties (overwriting them on a re-run) and returns the same worklet. The
worklet's identity and type are unchanged - there is no new worklet; the caller persists the same one.

**Appended properties** (set via `set_property` - update-or-append)

| Property name | Content |
| --- | --- |
| `title` | `"<idmt ticket title> -- <vs name>"` |
| `description` | per-VS framing paragraph over the shared body |
| `Business Needs` | the Business Needs text for this value stream |
| `generatedByLLM` | `True` |
| `selectedStages` | list of selected stages (`SelectedStage.model_dump()`) |
| `L3 Business Capability` | selected L3 capabilities (`L3Capability.model_dump()`) |
| `L2 Business Capability` | derived L2 capabilities (`L2Capability.model_dump()`) |

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
- Property names with spaces (`Business Needs`, `L3 Business Capability`, `L2 Business Capability`)
  are intentional — they match the existing worklet property naming.
