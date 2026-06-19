# Theme Generation — Prompt Inputs & Outputs

Exactly what each LLM call sends and what it returns. There are **5 prompts**; with N approved value
streams the handler makes **4 + N** calls (business needs runs once per value stream, the rest are
single batched calls). Every prompt also receives the **ticket context** = the raw ticket text only
("raw to decide"); summary-derived fields are not sent.

Wire format is camelCase (pydantic `CamelModel`); fields are snake_case in Python. Output schemas are
passed to the gateway as structured-output (`json_schema`) so the reply validates against the model.

Order of calls:

```
Step 1 (parallel):  description_body | description_framing | stage_selection
Step 2 (parallel):  capability_selection | business_needs (per value stream)
Step 3:             assemble the THEME worklet (no LLM); L2 derived from L3
```

---

## 1. description_body  (1 call, value-stream-agnostic)

The shared description body, generated once and reused by every theme for the ticket.

**Send**

| Variable | Content |
| --- | --- |
| `ticket_context` | `- content: <raw ticket text>` |

**Get back** — `TextOut`

```json
{ "text": "<the shared description body>" }
```

---

## 2. description_framing  (1 call, all value streams)

One opening paragraph per value stream — how the idea shows up through that value stream's lens.

**Send**

| Variable | Content |
| --- | --- |
| `ticket_context` | raw ticket text |
| `value_streams` | per VS: `valueStreamId`, `valueStreamName`, `valueStreamDescription`, `valueProposition`, `trigger` |

**Get back** — `FramingsOut`

```json
{
  "framings": [
    { "valueStreamId": "VSR00074583", "text": "<framing paragraph>" }
  ]
}
```

A value stream the model omits simply has no framing (its description still gets the shared body).

---

## 3. stage_selection  (1 call, all value streams)

Selects which lifecycle stages of each value stream apply to this ticket.

**Send**

| Variable | Content |
| --- | --- |
| `ticket_context` | raw ticket text |
| `value_streams` | per VS header: `id`, `name`, `description`, `value proposition`, `trigger`; then its **candidate stages**, each: `id`, `name`, `description`, `entrance`, `exit` |

**Get back** — `BatchedStageSelection`

```json
{
  "valueStreams": [
    {
      "valueStreamId": "VSR00074583",
      "selectedStages": [
        { "stageId": "VSS00074679", "stageName": "Approve Request", "reason": "<why>" }
      ]
    }
  ]
}
```

The model emits `stageId` + `stageName` (echo) + `reason`. On resolve we keep only the value
stream's own stage ids, **overwrite the name** with the canonical catalogue name, and **fill the
scope** (`stageDescription`, `entranceCriteria`, `exitCriteria`) from the catalogue. Empty / all-invalid
picks fall back to all of that value stream's stages; a stage placed under the wrong value stream is
moved back to its owner.

---

## 4. capability_selection  (1 merged call, all value streams)

Selects the L3 business capabilities for every selected stage, in one call.

**Send**

| Variable | Content |
| --- | --- |
| `ticket_context` | raw ticket text |
| `value_streams` | per VS header: `id`, `name`, `description`, `value proposition`, `trigger`; then per **selected stage**: `id`, `name`, `description`; then that stage's **candidate L3**, each: `[id] name - description (L2: parentName)` |

**Get back** — `BatchedCapabilitySelection`

```json
{
  "stages": [
    {
      "stageId": "VSS00074679",
      "capabilities": [
        { "capabilityId": "CAP00000588", "name": "Physical Asset Order Management", "reason": "<why>" }
      ]
    }
  ]
}
```

The model picks by `capabilityId`. On resolve we keep only ids governed for that stage (the canonical
record), mark them selected, and move a capability placed under the wrong stage back to its owner.
**L2 is derived, not generated** (`derive_l2`): the unique parent L2 of the selected L3 — no LLM call.

---

## 5. business_needs  (1 call PER value stream)

The detailed Business Needs document for one value stream's selected stages. Runs once per value
stream (in parallel).

**Send**

| Variable | Content |
| --- | --- |
| `ticket_context` | raw ticket text |
| `value_stream_id` | the VS id |
| `value_stream_name` | the VS name |
| `value_stream_description` | the VS description |
| `value_proposition` | the VS value proposition |
| `selected_stages` | per selected stage: `[id] name`, `Description`, `Entrance \| Exit` |

(No `trigger` here — it is sent to framing / stage / capability prompts only.)

**Get back** — `TextOut`

```json
{ "text": "<Business Needs document; sections live inside the text>" }
```

The structure (Value Stage / Business Product Feature / numbered needs / Operational Training /
Reporting) is inside the text, not separate JSON fields. Sections with no grounded evidence are omitted.

---

## What is NOT an LLM call

- **L2 capabilities** — derived from the selected L3 (`derive_l2`), one per distinct parent.
- **Theme title** — `"<ticket title> -- <value stream name>"`, assembled in the handler.
- **Theme description** — the value stream's framing paragraph over the shared body, assembled in the handler.

---

## Field summary (per prompt)

`✓` = sent. Raw ticket text goes to every prompt.

| Field | body | framing | stages | caps | needs |
| --- | :--: | :--: | :--: | :--: | :--: |
| VS id / name / description | — | ✓ | ✓ | ✓ | ✓ |
| VS value proposition | — | ✓ | ✓ | ✓ | ✓ |
| VS trigger | — | ✓ | ✓ | ✓ | — |
| candidate stages (id, name, desc, entrance, exit) | — | — | ✓ | — | — |
| selected stages (id, name) | — | — | — | ✓ | ✓ |
| selected stage scope (desc, entrance, exit) | — | — | — | desc only | ✓ |
| candidate L3 (id, name, desc, parent L2 name) | — | — | — | ✓ | — |
