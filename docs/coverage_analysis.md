# Coverage Analysis

How a generated Theme is scored for **grounding** — how much of its text is supported by the original
ticket, and how much is invented. Implemented by `CoverageAnalysisService`
(`jwg_app/domain/services/coverage_analysis.py`), which adapts Theme output to the existing n-gram
evaluator (`text_evaluation.ngram_evaluation.NgramEvaluator`, an external dependency).

## What it measures

The evaluator compares two texts with **n-gram overlap**:

- **Coverage** — of the source (raw ticket text), how much is reflected in the generated text. High
  coverage = the Theme actually uses the ticket's content.
- **Creativity** — of the generated text, how much is *not* grounded in the source. High creativity =
  the Theme invented detail the ticket never stated (the risk we guard against).

Both are reported as scores plus highlight spans: covered source text is highlighted in
``coverage_color`` (default green), ungrounded generated text in ``creativity_color`` (default orange).

## Inputs

`analyze(raw_text, themes, n=1, remove_stopwords=True, coverage_color="green", creativity_color="orange")`:

| Arg | Meaning |
| --- | --- |
| `raw_text` | the original raw ticket text (description + extracted attachments) — the grounding source |
| `themes` | the list of generated Theme worklets (`run()`'s output) |
| `n` | n-gram size (1 = unigram recall) |
| `remove_stopwords` | drop stopwords before matching, so overlap reflects content words |
| `coverage_color` / `creativity_color` | highlight colors (enums or strings) |

## How a Theme maps onto the evaluator

The evaluator's contract expects a context field named `acceptanceCriteria` and generated entities
with `title` / `description` properties. Themes don't have those exact fields, so the service maps:

| Evaluator slot | Fed with |
| --- | --- |
| `acceptanceCriteria` (context) | the raw ticket text — the source to cover |
| `title` (generated) | the Theme **Business Needs** |
| `description` (generated) | the Theme **description** |

`title` / `description` are **evaluator slot names, not semantic fields** — both Theme text outputs
(business needs + description) are scored against the raw text. (Stages and capabilities are catalogue
ids, not free text, so they are not coverage-scored.)

## Dataset shape

`build_dataset(...)` produces the evaluator input without running it (useful for inspection):

```json
{
  "context": [ { "propertyName": "acceptanceCriteria", "propertyValue": "<raw ticket text>" } ],
  "generated_text": [
    [
      { "propertyName": "title",       "propertyValue": "<theme business needs>" },
      { "propertyName": "description", "propertyValue": "<theme description>" }
    ]
  ],
  "n": 1,
  "remove_stopwords": true,
  "coverage_color": "green",
  "creativity_color": "orange"
}
```

`analyze(...)` builds this, runs the evaluator, and returns one entry per metric (Coverage,
Creativity) **already converted to JSON-safe dicts** - the evaluator hands back `Metric` objects,
which `analyze` serializes (`_to_jsonable`) so the result can be returned/serialized directly.
`analysis_property(result)` wraps those dicts as the `analysis` worklet property the API sets on the
ER:

```json
{
  "propertyName": "analysis",
  "propertyValue": [
    {
      "metric_name": "Coverage",
      "metric_value": { "score": 0.78, "highlighted_text": "<span style='background-color: green'>member portal</span> ..." }
    },
    {
      "metric_name": "Creativity",
      "metric_value": {
        "score": 0.42,
        "scores": [0.35, 0.50, 0.41],
        "highlighted_text": [
          [ { "propertyName": "title", "propertyValue": "... <span style='background-color: orange'>...</span>" },
            { "propertyName": "description", "propertyValue": "..." } ]
        ]
      }
    }
  ]
}
```

The `Metric` objects aren't natively JSON-serializable, so `analysis_property` runs them through a
recursive `_to_jsonable` pass (pydantic `model_dump` / `__dict__` / dict / list) before wrapping -
the result drops straight into a worklet property and the API response. The caller upserts this
property on the **ER** worklet (the analysis scores how well the generated themes cover the ER).

## Behaviour notes

- **The evaluator is an external dependency.** If `text_evaluation.ngram_evaluation` is not importable,
  `analyze` raises `RuntimeError`; `build_dataset` still works (no evaluator needed), so callers can
  inspect what *would* be scored.
- **Try it via the smoke:** `python scripts/theme_test/smoke_theme.py --real-db --real-llm --coverage`
  scores the generated themes against `scripts/theme_test/raw_text.txt`.
