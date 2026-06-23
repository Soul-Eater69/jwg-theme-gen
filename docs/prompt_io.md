# Theme Generation — Prompt I/O Contract

What goes **into** each LLM call and what comes **out**, with a concrete example of the rendered
prompt for every call. This is the contract view: the inputs are built by
`jwg_app/domain/services/theme/prompt_builder.py` from the engagement-request + the SQL catalogue, the
prompt text lives in `configs/user_config.yaml`, and each output is a pydantic schema in
`jwg_app/domain/models/theme_generation.py`.

Two ground rules that apply to every call:

- **Grounding is the raw ticket text only.** Every prompt's `ticket_context` is just
  `- content: <rawText>`. Summary-derived fields are not sent.
- **Structured output is strict.** Each call passes its schema as a strict `response_format`
  (constrained decoding), so the model must return exactly that shape.

For one engagement request with **N** approved value streams, theme generation makes **4 + N** LLM
calls: description body (1), framing (1), stage selection (1), capability selection (1), and business
needs (N, one per value stream).

---

## Shared example data

All examples below use this one ticket and one value stream:

```
rawText : "The plan must onboard CareWay+ commercial members, adjudicate their
           claims, and price provider services for the new fiscal year."
title   : "CareWay+ commercial claims activation"

Value stream  VSR00074584  "Claims Adjudication"
  description       : Adjudicate and price member and provider claims
  value proposition : Accurate, timely claim adjudication and pricing
  trigger           : A claim is submitted

  catalogue stages
    VSS00074614  Eligibility Determination   (entrance: claim registered | exit: eligibility decided)
    VSS00074613  Benefit Determination       (entrance: eligibility decided | exit: benefit priced)

  catalogue L3 (under Eligibility Determination)
    CAP00000097  Eligibility Determination   -> L2  CAP00000036  Claim Adjudication
```

---

## 1. Description body — `TextOut`

The VS-agnostic body of the Theme description, written once for the ticket and reused under every
value stream's theme.

**Input** — `ticket_context` only (no value stream; the body is shared).

**Rendered prompt** (user message):

```
Ticket context:
- content: The plan must onboard CareWay+ commercial members, adjudicate their
  claims, and price provider services for the new fiscal year.
```

**Output schema** `TextOut`:

```json
{ "text": "<the shared description body paragraph(s)>" }
```

---

## 2. Description framing — `FramingsOut`

One opening paragraph **per value stream**, prepended to the shared body to make each theme's
description value-stream specific.

**Input** — `ticket_context` + `value_streams` (id, name, description, value proposition, trigger).

**Rendered prompt**:

```
Ticket context:
- content: The plan must onboard CareWay+ commercial members, adjudicate their
  claims, and price provider services for the new fiscal year.

Approved value streams:
- valueStreamId: VSR00074584
  valueStreamName: Claims Adjudication
  valueStreamDescription: Adjudicate and price member and provider claims
  valueProposition: Accurate, timely claim adjudication and pricing
  trigger: A claim is submitted
```

**Output schema** `FramingsOut` — one entry per value stream:

```json
{
  "framings": [
    { "valueStreamId": "VSR00074584", "text": "<framing paragraph for this VS>" }
  ]
}
```

The final `description` property = `<framing paragraph>` + the shared body from call 1.

---

## 3. Stage selection — `BatchedStageSelection`

Selects, for **every** value stream at once, which of its catalogue stages the work runs through.
Each selected stage becomes a Jira Epic.

**Input** — `ticket_context` + `value_streams`, each VS rendered with its **candidate stages**.

**Rendered prompt**:

```
## Ticket context
- content: The plan must onboard CareWay+ commercial members, adjudicate their
  claims, and price provider services for the new fiscal year.


## Approved value streams (each with its own candidate stages)
## Value Stream VSR00074584
Name: Claims Adjudication
Description: Adjudicate and price member and provider claims
Value proposition: Accurate, timely claim adjudication and pricing
Trigger: A claim is submitted
Candidate stages:
[VSS00074614] Eligibility Determination
Description: Determine member eligibility for the claim
Entrance: claim registered | Exit: eligibility decided
[VSS00074613] Benefit Determination
Description: Determine and price the benefit
Entrance: eligibility decided | Exit: benefit priced
```

**Output schema** `BatchedStageSelection` — picks keyed by `valueStreamId`:

```json
{
  "valueStreams": [
    {
      "valueStreamId": "VSR00074584",
      "selectedStages": [
        { "stageId": "VSS00074614", "stageName": "Eligibility Determination" }
      ]
    }
  ]
}
```

The model returns `stageId` (+ echoes `stageName`). On resolve we keep only ids that belong to the
value stream, **overwrite the name + fill the scope** from the catalogue, drop unknown ids, move a
stage placed under the wrong value stream back to its owner, and — if a VS got no valid pick — fall
back to all of its stages (never empty). See [resolve internals](#resolution-how-picks-are-cleaned).

---

## 4. Capability selection — `BatchedCapabilitySelection`

Selects the L3 business capabilities for **every selected stage** at once. The value stream is shown
as context, but picks come back keyed by **stage**, not value stream.

**Input** — `ticket_context` + `value_streams`, each VS rendered with its **selected stages** and,
under each stage, that stage's **candidate L3 capabilities**.

**Rendered prompt**:

```
## Ticket context
- content: The plan must onboard CareWay+ commercial members, adjudicate their
  claims, and price provider services for the new fiscal year.

## Approved value streams, each with its selected stages and each stage's own candidate L3
## Value Stream VSR00074584
Name: Claims Adjudication
Description: Adjudicate and price member and provider claims
Value proposition: Accurate, timely claim adjudication and pricing
Trigger: A claim is submitted

### Stage VSS00074614: Eligibility Determination
Description: Determine member eligibility for the claim
Candidate L3 capabilities (choose by id; each shows its parent L2):
[CAP00000097] Eligibility Determination - Verify member eligibility (L2: Claim Adjudication)
```

**Output schema** `BatchedCapabilitySelection` — picks keyed by `stageId`:

```json
{
  "stages": [
    {
      "stageId": "VSS00074614",
      "capabilities": [
        { "id": "CAP00000097", "name": "Eligibility Determination" }
      ]
    }
  ]
}
```

The model returns each pick as `{ id, name }` (it varies the id key — `id` / `capabilityId` — both
accepted). On resolve we keep only ids that are real candidates of that stage, take name/description/
L2 from the catalogue, drop unknown ids, and move a capability placed under the wrong stage back to
its owner. L2 is then **derived in code** (no LLM) from the selected L3.

---

## 5. Business needs — `TextOut` (one call per value stream)

Writes the Business Needs document for **one** value stream, scoped to its selected stages. Runs once
per approved value stream.

**Input** — `ticket_context` + that value stream's attributes + its `selected_stages` (with scope).

**Rendered prompt**:

```
## Approved value stream
ID: VSR00074584
Name: Claims Adjudication
Description: Adjudicate and price member and provider claims
Value proposition: Accurate, timely claim adjudication and pricing

## Selected stages (write needs for these stages only)
[VSS00074614] Eligibility Determination
  Description: Determine member eligibility for the claim
  Entrance: claim registered | Exit: eligibility decided

## Ticket context
- content: The plan must onboard CareWay+ commercial members, adjudicate their
  claims, and price provider services for the new fiscal year.
```

**Output schema** `TextOut`:

```json
{ "text": "<the Business Needs document for this value stream>" }
```

---

## Final assembly — the THEME worklet

The five calls' outputs are attached onto each incoming THEME stub (one per value stream):

Only these six generated properties are written onto the theme stub; no value-stream attributes are
added.

| Property | From |
| --- | --- |
| `title` | `"<ticket title> -- <vs name>"` |
| `description` | framing paragraph (call 2) + shared body (call 1) |
| `businessNeeds` | call 5 |
| `selectedStages` | call 3, resolved against the catalogue |
| `l3BusinessCapability` | call 4, resolved against the catalogue |
| `l2BusinessCapability` | derived in code from the selected L3 |

Full worklet shape and field tables: see [api_integration.md](api_integration.md) and
[worklet_contract.md](worklet_contract.md).

---

## Coverage analysis (ANALYSE) — not an LLM call

Coverage is a **separate action** that runs **after** generation, and it is **not a prompt**: it is
deterministic n-gram scoring (`text_evaluation.ngram_evaluation.NgramEvaluator`). It is included here
because it is the other half of the theme-generation contract. Entry point:
`CoverageAnalysisService.analyze_worklet(er_worklet, themes)`.

**Input** — read off the worklets (no prompt, no model):

| Read | From | Used as |
| --- | --- | --- |
| source text | ER worklet `rawText` property (only — no fallback) | the context to score against |
| generated text | each theme's `description` + `businessNeeds` properties | the text being scored |

Internally it builds this evaluator dataset (the property names match the evaluator's existing
contract — `acceptanceCriteria` for the source, `title`/`description` for the generated side; the
theme's **Business Needs** is scored through the `title` slot and the theme **description** through
the `description` slot):

```json
{
  "context": [ { "propertyName": "acceptanceCriteria", "propertyValue": "<ER rawText>" } ],
  "generated_text": [
    [
      { "propertyName": "title",       "propertyValue": "<theme 1 Business Needs>" },
      { "propertyName": "description", "propertyValue": "<theme 1 description>" }
    ]
  ],
  "n": 1, "remove_stopwords": true, "coverage_color": "green", "creativity_color": "orange"
}
```

**Output** — the same ER worklet, with one `analysis` property attached (JSON-ready, list of two
metrics):

```json
{
  "propertyName": "analysis",
  "propertyValue": [
    {
      "metric_name": "Coverage",
      "metric_value": {
        "score": 0.78,
        "highlighted_text": "<span style='background-color: green'>...covered raw text...</span> ..."
      }
    },
    {
      "metric_name": "Creativity",
      "metric_value": {
        "score": 0.42,
        "scores": [0.35, 0.50, 0.41],
        "highlighted_text": [
          [
            { "propertyName": "title",       "propertyValue": "... <span style='background-color: orange'>new text</span>" },
            { "propertyName": "description", "propertyValue": "..." }
          ]
        ]
      }
    }
  ]
}
```

- **Coverage** = one overall `score` + `highlighted_text` (the full raw text with covered spans
  highlighted in green).
- **Creativity** = overall `score`, plus `scores` (per-theme), plus `highlighted_text` (per-theme:
  the generated title/description with not-grounded spans highlighted in orange).

`Metric` objects are serialized to plain dicts automatically, so the property drops straight into the
API response. Worklet-in / worklet-out: the ER's other properties are untouched; `analysis` is
added (overwritten on a re-run).

---

## Resolution — how picks are cleaned

Both stage and capability picks are reconciled against the catalogue (the source of truth) in
`output_resolver.py`. The model says *which* ids it wants; the catalogue decides *where each belongs*
and *what its canonical name/scope are*:

- **Filter** — keep only ids that are real candidates of that parent (VS for stages, stage for caps).
- **Canonicalize** — name and scope come from the catalogue record, not the model's echo.
- **Reassign** — an id filed under the wrong parent is moved to its real parent (one level each:
  stage↔VS, then cap↔stage).
- **Drop** — an id in no catalogue is discarded.
- **Stage-only fallback** — a VS with no valid stage pick gets all its stages (never empty);
  capabilities have no fallback (a stage may end up with none).
