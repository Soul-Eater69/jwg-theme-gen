# Theme Generation — Worklet Contract

How the theme generation handler reads its input worklets and shapes its output worklet. All
worklet ↔ domain translation lives in `jwg_app/domain/services/theme/worklet_mapper.py`; the property
names below are the only coupling to the worklet shape and are defined there as class-namespaced
constants (`ERProps`, `DocsSummaryKeys`, `VSProps`, `ThemeProps`).

`ThemeGenerationHandler.run(er_worklet, vs_worklets)` takes one engagement-request worklet and the
list of approved value-stream worklets, and returns one unsaved **THEME** worklet per value stream.

---

## 1. Engagement Request (ER) worklet — input

Read by `to_er_context`. Grounds every generation prompt; `rawText` carries the raw ticket text used
for generation ("raw to decide").

| Domain field (`ERContext`) | Worklet source | Property name |
| --- | --- | --- |
| `idmt_ticket_id` | worklet identity | `source_id` (fallback `id`) |
| `idmt_ticket_title` | property | `title` |
| `generated_summary` | property | `rawText` |
| `business_problem` | `Docs Summary` dict | `businessProblem` |
| `business_capability` | `Docs Summary` dict | `businessCapability` |
| `key_terms` | `Docs Summary` dict | `keyTerms` |
| `stakeholders` | `Docs Summary` dict | `stakeholders` |
| `systems_and_products` | `Docs Summary` dict | `systemsAndProducts` |

`Docs Summary` is a single property whose value is a dict; the keys above are read from it. If it is
absent or not a dict, the summary-derived fields default to empty (the mapper guards the type).

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
- `trigger` is included only where lifecycle/process reasoning matters (stage and capability
  selection); it is omitted from framing and business needs as marginal there. This is a soft tuning
  choice, not a hard rule.

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

---

## Notes / assumptions

- **VS worklet contract:** the worklet is assumed to provide `title` and `valueStreamDescription`. If
  that ever changes to an id-only worklet, source `vs_name` / `vs_description` from the SQL VS table
  (`value_stream_name` / `value_stream_description`) instead — the catalogue already reads that table.
- **`vs_id` source:** `source_id` falls back to `id`. This is the SQL join key, so it must be the VSR
  id of the approved value stream.
- Property names with spaces (`Docs Summary`, `Business Needs`, `L3 Business Capability`,
  `L2 Business Capability`) are intentional — they match the existing worklet property naming.
