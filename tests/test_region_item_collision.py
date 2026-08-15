from kosis_meta_coordinates import claim_axis_targets, looks_like_administrative_region


def test_region_misfiled_as_measurement_item_is_not_also_a_product():
    targets = claim_axis_targets({
        "claim_text": "울릉군의 고용률은 83.5%였다.",
        "measurement_indicator": "고용률",
        "measurement_item": "울릉군",
    })
    assert "울릉군" in targets["region"]
    assert "product" not in targets


def test_generic_group_is_not_reclassified_as_a_region():
    assert not looks_like_administrative_region("상품군", "상품군별 판매액")
    targets = claim_axis_targets({
        "claim_text": "상품군별 판매액이 증가했다.",
        "measurement_indicator": "판매액",
        "measurement_item": "상품군",
    })
    assert "region" not in targets


def test_age_in_causal_explanation_is_not_a_coordinate_target():
    targets = claim_axis_targets({
        "claim_text": "실업률이 낮아진 현상의 상당 부분이 청년층의 구직 포기 때문이다.",
        "measurement_indicator": "실업률",
        "age_group": "청년",
    })
    assert "age" not in targets


def test_canonical_youth_age_still_uses_original_causal_alias():
    targets = claim_axis_targets({
        "claim_text": "실업률이 낮아진 현상의 상당 부분이 청년층의 구직 포기 때문이다.",
        "measurement_indicator": "실업률",
        "age_group": "15 - 29세",
    })
    assert "age" not in targets


def test_age_directly_bound_to_household_remains_a_coordinate_target():
    targets = claim_axis_targets({
        "claim_text": "가구주 연령대별 순자산은 60세 이상 가구가 가장 많았다.",
        "measurement_indicator": "순자산",
        "age_group": "60세 이상",
    })
    assert targets["age"] == ("60세이상",)
