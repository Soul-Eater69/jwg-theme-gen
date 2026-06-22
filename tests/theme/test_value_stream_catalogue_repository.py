"""The catalogue repository builds one active-only join (no DB; inspects the compiled SQL)."""

from jwg_app.infrastructure.repositories.value_stream_catalogue_repository import (
    ValueStreamCatalogueRepository,
)


def test_query_is_a_single_join_over_the_five_tables():
    sql = str(ValueStreamCatalogueRepository._query(["VSR1", "VSR2"]))
    # one statement, joining all five catalogue tables
    assert sql.count("SELECT") == 1
    for table in (
        "idp_sightline_value_stream",
        "idp_sightline_value_stream_capability",
        "idp_sightline_value_stream_stage",
        "idp_sightline_l3_capabilities",
        "idp_sightline_l2_capabilities",
    ):
        assert table in sql
    assert sql.count("JOIN") == 4  # vs -> mapping -> stage -> l3 -> l2


def test_query_filters_active_rows():
    sql = str(ValueStreamCatalogueRepository._query(["VSR1"]))
    assert "value_stream_active" in sql
    assert "value_stream_stage_active" in sql
    assert "capability_active" in sql
