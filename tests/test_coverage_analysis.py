"""Tests for the Theme coverage-analysis adapter."""

from jwg_app.domain.services.coverage_analysis import CoverageAnalysisService


class _Prop:
    def __init__(self, name, value):
        self.property_name = name
        self.property_value = value


class _Worklet:
    def __init__(self, properties=None):
        self.properties = properties or []


class _FakeEvaluator:
    def __init__(self):
        self.dataset = None

    def evaluate(self, dataset):
        self.dataset = dataset
        return [{"coverage": 0.75}]


def _theme(description, business_needs):
    return _Worklet(
        [
            _Prop(CoverageAnalysisService.THEME_DESCRIPTION_PROPERTY, description),
            _Prop(CoverageAnalysisService.THEME_BUSINESS_NEEDS_PROPERTY, business_needs),
        ]
    )


def test_build_dataset_uses_existing_evaluator_property_names():
    service = CoverageAnalysisService()

    dataset = service.build_dataset(
        raw_text="raw ticket",
        themes=[_theme("theme description", "theme business needs")],
    )

    assert dataset["context"] == [
        {"propertyValue": "raw ticket", "propertyName": "acceptanceCriteria"}
    ]
    # title <- business needs, description <- the theme description
    assert dataset["generated_text"] == [
        [
            {"propertyValue": "theme business needs", "propertyName": "title"},
            {"propertyValue": "theme description", "propertyName": "description"},
        ]
    ]
    assert dataset["n"] == 1
    assert dataset["remove_stopwords"] is True
    assert dataset["coverage_color"] == "green"
    assert dataset["creativity_color"] == "orange"


def test_analyze_delegates_to_evaluator_with_dataset():
    evaluator = _FakeEvaluator()
    service = CoverageAnalysisService(evaluator=evaluator)

    result = service.analyze(
        raw_text="raw",
        themes=[_theme("desc", "needs")],
        n=2,
        remove_stopwords=False,
    )

    assert result == [{"coverage": 0.75}]
    assert evaluator.dataset["n"] == 2
    assert evaluator.dataset["remove_stopwords"] is False


def test_build_dataset_uses_all_generated_themes_in_one_call():
    service = CoverageAnalysisService()

    dataset = service.build_dataset(
        raw_text="raw",
        themes=[
            _theme("desc 1", "needs 1"),
            _theme("desc 2", "needs 2"),
        ],
    )

    assert dataset["generated_text"] == [
        [
            {"propertyValue": "needs 1", "propertyName": "title"},
            {"propertyValue": "desc 1", "propertyName": "description"},
        ],
        [
            {"propertyValue": "needs 2", "propertyName": "title"},
            {"propertyValue": "desc 2", "propertyName": "description"},
        ],
    ]


def test_analysis_property_wraps_result_for_api_contract():
    analysis = [{"metric_name": "Coverage", "metric_value": {"score": 0.78}}]

    assert CoverageAnalysisService().analysis_property(analysis) == {
        "propertyName": "analysis",
        "propertyValue": analysis,
    }


class _FakeMetric:
    """Stands in for the evaluator's Metric object (attribute-based -> serialized via __dict__)."""

    def __init__(self, metric_name, metric_value):
        self.metric_name = metric_name
        self.metric_value = metric_value


def test_analysis_property_serializes_metric_objects():
    metrics = [
        _FakeMetric("Coverage", {"score": 0.78, "highlighted_text": "<span>...</span>"}),
        _FakeMetric("Creativity", {"score": 0.42, "scores": [0.35, 0.50], "highlighted_text": [[]]}),
    ]

    prop = CoverageAnalysisService().analysis_property(metrics)

    assert prop == {
        "propertyName": "analysis",
        "propertyValue": [
            {"metric_name": "Coverage", "metric_value": {"score": 0.78, "highlighted_text": "<span>...</span>"}},
            {"metric_name": "Creativity", "metric_value": {"score": 0.42, "scores": [0.35, 0.50], "highlighted_text": [[]]}},
        ],
    }


