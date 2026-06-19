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

Read by `to_vs_context`, combined with the SQL catalogue enrichment. **By contract, the VS worklet
carries the id, name, and description**; the catalogue supplies value proposition, trigger, stages,
and capabilities.

| Domain field (`VSContext`) | Source | Property / catalogue field |
| --- | --- | --- |
| `vs_id` | **worklet** identity | `source_id` (fallback `id`) — the VSR id used to look up the catalogue |
| `vs_name` | **worklet** property | `title` |
| `vs_description` | **worklet** property | `valueStreamDescription` |
| `value_proposition` | **SQL catalogue** | `value_stream_value_proposition` |
| `trigger` | **SQL catalogue** | `value_stream_trigger` |

So the only field strictly required for correctness is **`vs_id`** (the catalogue join key); `vs_name`
and `vs_description` are contractually provided on the worklet. Everything else for the value stream
(stages, L3/L2 capabilities) comes from SQL — see [sql_catalogue.md] / the catalogue service.

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

## 3. THEME worklet — output

Built by `to_theme_worklet`, one per approved value stream. Returned unsaved; the caller persists it.

**Envelope**

| Attribute | Value |
| --- | --- |
| `worklet_type` | `WorkletType.THEME` |
| `parent_worklet_id` | the VS worklet's `id` |
| `state` | `RecordState.CREATED` |
| `id` / `source_id` | `None` (assigned on persist) |

**Properties** (set via `set_property`)

| Property name | Content |
| --- | --- |
| `title` | `"<idmt ticket title> -- <vs name>"` |
| `description` | per-VS framing paragraph over the shared body |
| `Business Needs` | the Business Needs text for this value stream |
| `Rationale` | reserved (currently empty) |
| `generatedByLLM` | `True` |
| `selectedStages` | list of selected stages (`SelectedStage.model_dump()`) |
| `L3 Business Capability` | selected L3 capabilities (`L3Capability.model_dump()`) |
| `L2 Business Capability` | derived L2 capabilities (`L2Capability.model_dump()`) |
| `generationStatus` | `"complete"` |

A **failed** value stream (see partial failure below) returns a THEME worklet with only:

| Property name | Content |
| --- | --- |
| `generationStatus` | `"failed"` |
| `generationError` | `"<status>: <detail>"` (e.g. `"503: LLM service unavailable: ..."`) |
| `generatedByLLM` | `True` |

---

## Failure handling

`run()` returns `list[Worklet]`; the API reads `generationStatus` per worklet. Failures fall in two
tiers:

- **Core failure → the whole request raises** `CustomException` (no list returned). Core =
  catalogue read + the batched, all-value-stream LLM calls (description body, description framing,
  stage selection, capabilities). These are shared/foundational, so if any fails after retries the
  request fails: `404` (missing worklets), `503` (Azure SQL or a core LLM call unavailable).
- **Per-VS failure → that value stream is flagged, others still succeed.** After the core phase,
  each value stream's own flow (business needs + assembly) runs in isolation. If one fails, its
  worklet comes back with `generationStatus="failed"` + `generationError`, and the remaining value
  streams return complete themes; the request does **not** raise. Per-VS failures include `503`
  (business needs unavailable after retries) and `400` (the value stream has no governed stages in
  the catalogue - nothing to build). Note: when the LLM selects no stage for a value stream that
  *does* have catalogue stages, the resolver falls back to all of them (not a failure).

Transient LLM failures (429 / 5xx / timeout) are retried per the theme retry config before either
tier treats the call as failed.

---

## Notes / assumptions

- **VS worklet contract:** the worklet is assumed to provide `title` and `valueStreamDescription`. If
  that ever changes to an id-only worklet, source `vs_name` / `vs_description` from the SQL VS table
  (`value_stream_name` / `value_stream_description`) instead — the catalogue already reads that table.
- **`vs_id` source:** `source_id` falls back to `id`. This is the SQL join key, so it must be the VSR
  id of the approved value stream.
- Property names with spaces (`Business Needs`, `L3 Business Capability`, `L2 Business Capability`)
  are intentional — they match the existing worklet property naming.
