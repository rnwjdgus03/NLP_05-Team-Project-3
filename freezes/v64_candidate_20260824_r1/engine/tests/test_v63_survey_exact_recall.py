from run_kosis_coordinate_stage_a import metadata_recall_enabled


def test_survey_exact_accepts_explicit_survey_metadata():
    assert metadata_recall_enabled(
        {"source_survey": "경제활동인구조사", "metric_domain": "고용"},
        "survey_exact",
    )


def test_survey_exact_accepts_official_series_like_metric_domain():
    for domain in (
        "전문건설업통계조사",
        "도시계획현황",
        "공동주택실거래가격지수",
        "국세통계",
    ):
        assert metadata_recall_enabled({"metric_domain": domain}, "survey_exact")


def test_survey_exact_rejects_broad_domains():
    for domain in ("물가", "무역", "고용", "인구"):
        assert not metadata_recall_enabled({"metric_domain": domain}, "survey_exact")


def test_existing_metadata_policies_remain_unchanged():
    assert metadata_recall_enabled({}, "all")
    assert metadata_recall_enabled(
        {"measurement_indicator": "가구 자산"}, "household_asset"
    )
    assert not metadata_recall_enabled(
        {"measurement_indicator": "아파트 가격"}, "household_asset"
    )
