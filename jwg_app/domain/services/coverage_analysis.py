"""
Coverage analysis for generated Theme worklets.

This service adapts the Theme generation output to the existing n-gram evaluator contract. The
evaluator expects a raw context property named ``acceptanceCriteria`` and generated entities with
``title`` / ``description`` properties. For Themes, we send the Theme description and Business
Needs texts through those two evaluator fields.

``analyze_worklet`` is the worklet-in / worklet-out entry point: it reads the source context off the
ER worklet's ``rawText`` property, scores the themes, and attaches the JSON-ready ``analysis``
property on the ER worklet in place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from worklet_data_api import Worklet


@dataclass(frozen=True)
class AnalysisProperty:
    """One property-shaped text field consumed or produced by the evaluator."""

    property_name: str
    property_value: str

    def to_evaluator_property(self) -> dict[str, str]:
        return {
            "propertyName": self.property_name,
            "propertyValue": self.property_value,
        }


class CoverageEvaluator(Protocol):
    """Evaluator interface implemented by ``NgramEvaluator`` and by tests."""

    def evaluate(self, dataset: dict[str, Any]) -> list[dict[str, Any]]:
        """Return coverage/creativity scoring output for the evaluator dataset."""
        ...


class CoverageAnalysisService:
    """Build evaluator input for generated Themes and run coverage analysis."""

    ANALYSIS_PROPERTY = "analysis"

    # Theme property names read off the generated worklet (match ``theme.worklet_mapper.ThemeProps``
    # without importing the generator stack).
    THEME_DESCRIPTION_PROPERTY = "description"
    THEME_BUSINESS_NEEDS_PROPERTY = "businessNeeds"

    # ER worklet property used as the source context: the raw ticket text generation was grounded on.
    ER_RAW_TEXT_PROPERTY = "rawText"

    CONTEXT_PROPERTY = "acceptanceCriteria"
    GENERATED_TITLE_PROPERTY = "title"
    GENERATED_DESCRIPTION_PROPERTY = "description"

    def __init__(self, evaluator: CoverageEvaluator | None = None) -> None:
        self._evaluator = evaluator

    def analyze_worklet(
        self,
        *,
        er_worklet: Worklet,
        themes: list[Worklet],
        n: int = 1,
        remove_stopwords: bool = True,
        coverage_color: Any = "green",
        creativity_color: Any = "orange",
    ) -> Worklet:
        """
        Score an Engagement Request's generated Themes and attach the result to the ER worklet.

        Worklet in, the same worklet out: reads the source context off ``er_worklet`` (the ``rawText``
        property), scores the Theme descriptions and Business Needs against it, and upserts the
        JSON-safe ``analysis`` property on the ER worklet in place (overwriting it on a re-run). The
        caller persists the returned worklet.

        Args:
            er_worklet: The Engagement Request worklet (the ANALYSE source).
            themes: The generated Theme worklets to score.
            n: N-gram size used by the evaluator.
            remove_stopwords: Whether evaluator stopword filtering is enabled.
            coverage_color: Highlight color for covered source text.
            creativity_color: Highlight color for generated text not grounded in the source.

        Returns:
            The same ``er_worklet`` with the ``analysis`` property attached.
        """
        raw_text = _get_property(er_worklet, self.ER_RAW_TEXT_PROPERTY, "") or ""
        result = self.analyze(
            raw_text=raw_text,
            themes=themes,
            n=n,
            remove_stopwords=remove_stopwords,
            coverage_color=coverage_color,
            creativity_color=creativity_color,
        )
        er_worklet.upsert_property(name=self.ANALYSIS_PROPERTY, value=result)
        return er_worklet

    def analyze(
        self,
        *,
        raw_text: str,
        themes: list[Worklet],
        n: int = 1,
        remove_stopwords: bool = True,
        coverage_color: Any = "green",
        creativity_color: Any = "orange",
    ) -> list[dict[str, Any]]:
        """
        Score generated Themes against the raw engagement-request text.

        Args:
            raw_text: The original raw ticket text.
            themes: Generated Theme worklets.
            n: N-gram size used by the evaluator.
            remove_stopwords: Whether evaluator stopword filtering is enabled.
            coverage_color: Highlight color for covered source text.
            creativity_color: Highlight color for generated text not grounded in the source.

        Returns:
            The coverage/creativity metrics as JSON-serializable dicts (the evaluator returns Metric
            objects; they are converted here so the result can be returned/serialized directly).
        """
        dataset = self.build_dataset(
            raw_text=raw_text,
            themes=themes,
            n=n,
            remove_stopwords=remove_stopwords,
            coverage_color=coverage_color,
            creativity_color=creativity_color,
        )
        result = self._get_evaluator().evaluate(dataset)
        return [_to_jsonable(metric) for metric in result]

    def analysis_property(self, analysis: list[Any]) -> dict[str, Any]:
        """Wrap evaluator output in the ``analysis`` worklet property from the API contract.

        The evaluator returns one entry per metric (Coverage, Creativity). Each is serialized to a
        plain, JSON-safe ``{"metric_name": ..., "metric_value": {...}}`` dict so the property can be
        set on the ER worklet and serialized straight to the API response.
        """
        return {
            "propertyName": self.ANALYSIS_PROPERTY,
            "propertyValue": [_to_jsonable(metric) for metric in analysis],
        }

    def build_dataset(
        self,
        *,
        raw_text: str,
        themes: list[Worklet],
        n: int = 1,
        remove_stopwords: bool = True,
        coverage_color: Any = "green",
        creativity_color: Any = "orange",
    ) -> dict[str, Any]:
        """
        Build the evaluator dataset without running the evaluator.

        The property names intentionally match the existing evaluator contract:
        ``acceptanceCriteria`` for raw context, and ``title`` / ``description`` for generated text.
        """
        return {
            "context": [
                AnalysisProperty(self.CONTEXT_PROPERTY, raw_text).to_evaluator_property()
            ],
            "generated_text": [self._generated_theme_properties(theme) for theme in themes],
            "n": n,
            "remove_stopwords": remove_stopwords,
            "coverage_color": _enum_value(coverage_color),
            "creativity_color": _enum_value(creativity_color),
        }

    def _generated_theme_properties(self, theme: Worklet) -> list[dict[str, str]]:
        # title <- Business Needs, description <- the Theme description.
        description = _get_property(theme, self.THEME_DESCRIPTION_PROPERTY, "") or ""
        business_needs = _get_property(theme, self.THEME_BUSINESS_NEEDS_PROPERTY, "") or ""
        return [
            AnalysisProperty(
                self.GENERATED_TITLE_PROPERTY, str(business_needs)
            ).to_evaluator_property(),
            AnalysisProperty(
                self.GENERATED_DESCRIPTION_PROPERTY, str(description)
            ).to_evaluator_property(),
        ]

    def _get_evaluator(self) -> CoverageEvaluator:
        if self._evaluator is None:
            self._evaluator = _load_default_evaluator()
        return self._evaluator


def _load_default_evaluator() -> CoverageEvaluator:
    try:
        from text_evaluation.ngram_evaluation import NgramEvaluator
    except ImportError as exc:
        raise RuntimeError(
            "Coverage analysis requires text_evaluation.ngram_evaluation.NgramEvaluator"
        ) from exc
    return NgramEvaluator()


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _to_jsonable(obj: Any) -> Any:
    """Recursively convert evaluator output (e.g. Metric objects) to JSON-serializable values.

    A pydantic ``Metric`` becomes ``{"metric_name": ..., "metric_value": {...}}`` via ``model_dump``;
    dicts/lists recurse; plain objects fall back to their ``__dict__``; everything else is stringified.
    """
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {key: _to_jsonable(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(item) for item in obj]
    if hasattr(obj, "model_dump"):  # pydantic Metric
        return _to_jsonable(obj.model_dump())
    if hasattr(obj, "_asdict"):  # namedtuple
        return _to_jsonable(obj._asdict())
    if hasattr(obj, "__dict__"):  # plain object
        return _to_jsonable(vars(obj))
    return str(obj)


def _get_property(worklet: Worklet, name: str, default: Any = None) -> Any:
    for prop in getattr(worklet, "properties", []) or []:
        prop_name = getattr(prop, "property_name", getattr(prop, "propertyName", None))
        if prop_name == name:
            return getattr(prop, "property_value", getattr(prop, "propertyValue", default))
    return default
