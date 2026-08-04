import csv
from pathlib import Path

from build_holdout_measurement_labeling import (
    build_clean_articles,
    build_coverage_review,
    build_gold_labeling,
    remove_leading_article_number,
    reshape_claims,
)


def read_rows(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def test_remove_leading_article_number_only_at_start():
    assert remove_leading_article_number("48 기사 내용 2025년 1월 수치") == "기사 내용 2025년 1월 수치"
    assert remove_leading_article_number("기사 중간 48 숫자는 보존") == "기사 중간 48 숫자는 보존"


def test_clean_articles_preserves_50_ids_and_search_label(tmp_path):
    input_path = tmp_path / "articles.csv"
    output_path = tmp_path / "clean.csv"
    with input_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["기사제목", "작성일", "URL", "기사 본문(정제)", "검색 구분 레이블"],
        )
        writer.writeheader()
        for index in range(50):
            writer.writerow(
                {
                    "기사제목": f"기사 {index}",
                    "작성일": "2025-01-04",
                    "URL": f"https://example.com/{index}",
                    "기사 본문(정제)": f"{index} 본문 시작. 중간 숫자 2025는 보존.",
                    "검색 구분 레이블": "원본레이블",
                }
            )

    rows = build_clean_articles(input_path, output_path, 51)

    assert len(rows) == 50
    assert rows[0]["article_id"] == "HOLDOUT-A051"
    assert rows[-1]["article_id"] == "HOLDOUT-A100"
    assert len({row["article_id"] for row in rows}) == 50
    assert rows[0]["article_text_raw"].startswith("0 ")
    assert rows[0]["article_text_clean"].startswith("본문 시작")
    assert "2025" in rows[0]["article_text_clean"]
    assert rows[0]["search_label_original"] == "원본레이블"


def test_claim_and_gold_files_keep_model_columns_separate(tmp_path):
    is_claim = tmp_path / "is_claim.csv"
    claims_out = tmp_path / "claims.csv"
    with is_claim.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "article_id", "claim_id", "date", "title", "url", "claim_text",
                "prev_sentence", "next_sentence", "is_claim", "is_claim_reason",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "article_id": "HOLDOUT-A051", "claim_id": "HOLDOUT-A051-C001",
            "date": "2025-01-04", "title": "제목", "url": "https://e",
            "claim_text": "물가는 1% 올랐다.", "prev_sentence": "",
            "next_sentence": "", "is_claim": "True", "is_claim_reason": "수치 주장",
        })
        writer.writerow({
            "article_id": "HOLDOUT-A051", "claim_id": "HOLDOUT-A051-C002",
            "date": "2025-01-04", "title": "제목", "url": "https://e",
            "claim_text": "배경 문장", "prev_sentence": "",
            "next_sentence": "", "is_claim": "False", "is_claim_reason": "배경",
        })

    claims = reshape_claims(is_claim, claims_out)
    assert [row["claim_id"] for row in claims] == ["HOLDOUT-A051-C001"]

    measurements = tmp_path / "measurements.csv"
    gold_out = tmp_path / "gold.csv"
    with measurements.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "claim_id", "claim_measurement_id", "article_id", "title", "date",
                "url", "claim_text", "prev_sentence", "next_sentence",
                "measurement_indicator", "measurement_period", "measurement_prd_se",
                "measurement_role", "value", "unit", "value_approximate",
                "measurement_observation_type", "source_scope", "hcx_raw_response",
                "hcx_parse_success", "hcx_error",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "claim_id": "HOLDOUT-A051-C001",
            "claim_measurement_id": "HOLDOUT-A051-C001-m1",
            "article_id": "HOLDOUT-A051", "title": "제목", "date": "2025-01-04",
            "url": "https://e", "claim_text": "물가는 1% 올랐다.",
            "prev_sentence": "", "next_sentence": "",
            "measurement_indicator": "물가 상승률", "measurement_period": "2025",
            "measurement_prd_se": "Y", "measurement_role": "현재값",
            "value": "1", "unit": "%", "value_approximate": "N",
            "measurement_observation_type": "OBSERVED",
            "source_scope": "DOMESTIC_OFFICIAL",
            "hcx_raw_response": "{\"measurements\":[]}",
            "hcx_parse_success": "Y", "hcx_error": "",
        })

    gold_rows = build_gold_labeling(measurements, gold_out)
    assert gold_rows[0]["measurement_value"] == "1"
    assert gold_rows[0]["measurement_unit"] == "%"
    assert gold_rows[0]["gold_measurement_exists"] == ""
    assert gold_rows[0]["gold_tbl_id"] == ""
    assert gold_rows[0]["hcx_raw_response"] == "{\"measurements\":[]}"


def test_coverage_file_marks_claims_without_measurements(tmp_path):
    claims = tmp_path / "claims.csv"
    measurements = tmp_path / "measurements.csv"
    output = tmp_path / "coverage.csv"
    with claims.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["article_id", "claim_id", "claim_text", "prev_sentence", "next_sentence"],
        )
        writer.writeheader()
        writer.writerow({"article_id": "A1", "claim_id": "C1", "claim_text": "x", "prev_sentence": "", "next_sentence": ""})
        writer.writerow({"article_id": "A1", "claim_id": "C2", "claim_text": "y", "prev_sentence": "", "next_sentence": ""})
    with measurements.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["claim_id", "claim_measurement_id", "hcx_parse_success", "hcx_error"],
        )
        writer.writeheader()
        writer.writerow({"claim_id": "C1", "claim_measurement_id": "C1-m1", "hcx_parse_success": "Y", "hcx_error": ""})

    rows = build_coverage_review(claims, measurements, output)
    by_id = {row["claim_id"]: row for row in rows}
    assert by_id["C1"]["hcx_measurement_count"] == "1"
    assert by_id["C2"]["hcx_measurement_count"] == "0"
    assert by_id["C2"]["gold_should_have_measurement"] == ""
