"""Build a fully populated KOSIS MCP auto-gold dataset (v3).

Every gold_* field is populated.  Directly verified rows contain KOSIS
coordinates and observed values; unsupported rows contain the literal "N/A"
plus a concrete exclusion reason so that blank cells are never ambiguous.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "gold" / "mcp_auto_gold_v2.csv"
SEARCH_EVIDENCE = ROOT / "data" / "gold" / "mcp_auto_positive_search_v3.json"
NEWS_METADATA = ROOT / "outputs" / "runs" / "is_claim_news_10000_true.csv"
OUTPUT = ROOT / "data" / "gold" / "mcp_auto_gold_v3.csv"
MANIFEST = ROOT / "data" / "gold" / "mcp_auto_gold_v3_manifest.json"
NA = "N/A"


def kosis_url(org_id: str, tbl_id: str) -> str:
    return (
        "https://kosis.kr/statHtml/statHtml.do?"
        f"orgId={org_id}&tblId={tbl_id}&vw_cd=MT_ZTITLE"
    )


def rel_error(actual: float, claim: float) -> float:
    return abs(actual - claim) / abs(claim) * 100 if claim else 0.0


def direct(
    *, org: str, table: str, table_name: str, item: str, item_name: str,
    obj: str, obj_name: str, prd: str, period: str, source_unit: str,
    source_value: float, actual: float, claim: float, tolerance: str,
    reason: str, previous_period: str = NA, previous_value: float | str = NA,
    value_type: str = "수준값", derivation: str = "DIRECT",
) -> dict[str, object]:
    return {
        "gold_org_id": org,
        "gold_tbl_id": table,
        "gold_tbl_name": table_name,
        "gold_itm_id": item,
        "gold_itm_name": item_name,
        "gold_obj_l1": obj,
        "gold_obj_l1_name": obj_name,
        "gold_prd_se": prd,
        "gold_period": period,
        "gold_previous_period": previous_period,
        "gold_value_type": value_type,
        "gold_derivation_method": derivation,
        "gold_source_unit": source_unit,
        "gold_source_value": source_value,
        "gold_source_previous_value": previous_value,
        "gold_actual_value": actual,
        "gold_claim_signed_value": claim,
        "gold_abs_error": abs(actual - claim),
        "gold_relative_error_pct": rel_error(actual, claim),
        "gold_tolerance": tolerance,
        "gold_verdict": "일치",
        "gold_coordinate_status": "UNIQUE",
        "gold_confidence": "HIGH",
        "gold_reason": reason,
        "gold_evidence_url": kosis_url(org, table),
    }


retail_actual = (105.1 / 107.5 - 1) * 100
china_growth = (133_011_386 / 124_817_682 - 1) * 100
grain_growth = (64.4 / 64.6 - 1) * 100
farm_aged = 332_688 + 274_716 + 224_454 + 286_086
farm_share = farm_aged / 2_003_520 * 100


NEW_FULL: dict[str, dict[str, object]] = {
    "A0023-C026-m1": direct(
        org="101", table="DT_1K41012",
        table_name="재별 및 상품군별 소매판매액지수(2020=100.0)",
        item="T2", item_name="불변지수", obj="G0", obj_name="총지수",
        prd="M", period="202411", previous_period="202311",
        source_unit="지수", source_value=105.1, previous_value=107.5,
        actual=retail_actual, claim=-1.9,
        value_type="증감률", derivation="YOY_FROM_INDEX",
        tolerance="absolute_error<=0.5%p",
        reason="기사의 '11월'을 2024년 11월로 보정하고 소매판매 불변지수의 전년 동월비를 계산함.",
    ),
    "A0070-C004-m1": direct(
        org="360", table="DT_1R11006_FRM101", table_name="국가별 수출입",
        item="13103103829T1", item_name="수출금액",
        obj="13102103829E.CN", obj_name="중국",
        prd="Y", period="2024", source_unit="천달러",
        source_value=133_011_386, actual=133_011_386_000,
        claim=133_026_000_000, tolerance="relative_error<=0.5%",
        reason="중국 국가코드의 2024년 수출금액을 천달러에서 달러로 환산함.",
    ),
    "A0070-C004-m2": direct(
        org="360", table="DT_1R11006_FRM101", table_name="국가별 수출입",
        item="13103103829T1", item_name="수출금액",
        obj="13102103829E.CN", obj_name="중국",
        prd="Y", period="2024", previous_period="2023",
        source_unit="천달러", source_value=133_011_386,
        previous_value=124_817_682, actual=china_growth, claim=6.6,
        value_type="증감률", derivation="YOY_FROM_LEVEL",
        tolerance="absolute_error<=0.5%p",
        reason="중국 수출금액의 2023년 대비 2024년 증감률을 계산함.",
    ),
    "A0307-C011-m1": direct(
        org="101", table="DT_1ED0001", table_name="1인당 연간 양곡소비량",
        item="T10", item_name="전가구", obj="00; objL2=00",
        obj_name="양곡계; 계", prd="Y", period="2024",
        previous_period="2023", source_unit="kg", source_value=64.4,
        previous_value=64.6, actual=grain_growth, claim=-0.3,
        value_type="증감률", derivation="YOY_FROM_LEVEL",
        tolerance="absolute_error<=0.5%p",
        reason="전체 양곡 1인당 소비량의 2023년 대비 2024년 증감률을 계산함.",
    ),
    "A0739-C010-m1": direct(
        org="101", table="DT_1B8000G",
        table_name="월·분기·연간 인구동향(출생,사망,혼인,이혼)",
        item="T1", item_name="수치", obj="00; objL2=20",
        obj_name="전국; 혼인건수", prd="M", period="201912",
        source_unit="건", source_value=24_945, actual=24_945,
        claim=24_945, tolerance="exact",
        reason="기사의 비교 기준인 2019년 12월 전국 혼인건수를 직접 조회함.",
    ),
    "A0748-C007-m1": direct(
        org="101", table="DT_1B8000H", table_name="인구동태건수 및 동태율 추이",
        item="T12", item_name="합계출산율", obj="00", obj_name="전국",
        prd="Y", period="2015", source_unit="명", source_value=1.239,
        actual=1.239, claim=1.24, tolerance="absolute_error<=0.01",
        reason="2015년 전국 합계출산율을 직접 조회함.",
    ),
    "A1191-C011-m2": direct(
        org="101", table="DT_1DA7001S", table_name="성별 경제활동인구 총괄",
        item="T30", item_name="취업자", obj="0", obj_name="계",
        prd="Y", period="2023", previous_period="2022",
        source_unit="천명", source_value=28_416.3, previous_value=28_089.1,
        actual=327_200, claim=327_000, value_type="증감량",
        derivation="DIFF_FROM_LEVEL", tolerance="relative_error<=0.5%",
        reason="2022년과 2023년 전체 취업자 차이를 천명에서 명으로 환산함.",
    ),
    "A1383-C003-m1": direct(
        org="101", table="DT_1EA1040", table_name="연령 및 성별 농가인구",
        item="T00", item_name="농가인구", obj="000; objL2=E14,E15,E16,E17",
        obj_name="전국; 65~69세,70~74세,75~79세,80세 이상",
        prd="Y", period="2024", source_unit="명", source_value=farm_aged,
        actual=farm_share, claim=55.8, value_type="구성비",
        derivation="SUM_AGE_GROUPS_DIV_TOTAL",
        tolerance="absolute_error<=0.1%p",
        reason="65세 이상 네 연령대 농가인구 합계를 전체 농가인구 2,003,520명으로 나눔.",
    ),
    "A1922-C001-m1": direct(
        org="101", table="DT_1B8000G",
        table_name="월·분기·연간 인구동향(출생,사망,혼인,이혼)",
        item="T1", item_name="수치", obj="00; objL2=12",
        obj_name="전국; 합계출산율", prd="Q", period="202501",
        source_unit="명", source_value=0.83, actual=0.83, claim=0.8,
        tolerance="range_match:[0.8,0.9)",
        reason="KOSIS 분기코드 202501의 합계출산율 0.83은 기사 표현 '0.8명대'에 포함됨.",
    ),
}


EXCLUSION_REASONS: dict[str, str] = {
    "A0012-C009-m2": "검색된 산업기술인력 표는 지역축만 제공해 전국 조선업 외국인 수를 직접 고정할 수 없음.",
    "A0067-C010-m1": "기사는 수입차 판매 집계이고 KOSIS 자동차등록 통계와 모집단이 달라 직접 대조할 수 없음.",
    "A0067-C010-m2": "기사는 수입차 판매 비중이고 KOSIS 자동차등록 통계와 모집단이 달라 직접 대조할 수 없음.",
    "A0067-C010-m3": "기사는 수입차 판매 비중이고 KOSIS 자동차등록 통계와 모집단이 달라 직접 대조할 수 없음.",
    "A0067-C010-m4": "기사는 수입차 판매 비중이고 KOSIS 자동차등록 통계와 모집단이 달라 직접 대조할 수 없음.",
    "A0096-C003-m2": "순자금 운용액의 직전 분기 차이는 기사 내 파생값으로 동일 정의의 직접 KOSIS 좌표를 확정하지 못함.",
    "A0766-C010-m1": "서학개미 투자 증가율에 대응하는 KOSIS 공식 통계표를 찾지 못함.",
    "A0837-C010-m1": "1인당 PGDI는 한국은행 국민계정 계열로 로컬 KOSIS 카탈로그에서 직접 좌표를 찾지 못함.",
    "A0837-C010-m2": "1인당 PGDI는 한국은행 국민계정 계열로 로컬 KOSIS 카탈로그에서 직접 좌표를 찾지 못함.",
    "A0837-C010-m3": "원화 PGDI는 달러값에 환율을 적용한 기사 환산치라 단일 KOSIS 원자료가 아님.",
    "A0837-C012-m1": "GNI 대비 PGDI 비율은 한국은행 국민계정 파생지표로 로컬 KOSIS 좌표를 확정하지 못함.",
    "A0871-C010-m1": "'2021년 이후 한 번도 음수가 아님'은 다기간 조건 주장으로 단일 측정값 0%와 동일하지 않음.",
    "A0882-C023-m1": "중소벤처기업연구원 분석값이며 동일 정의의 KOSIS 직접 통계표를 찾지 못함.",
    "A1122-C024-m1": "생활인구 중 관광 목적 단기 숙박객 비율은 맞춤형 결합지표로 KOSIS 직접 좌표가 아님.",
    "A1122-C024-m2": "생활인구 중 관광 목적 단기 숙박객 비율은 맞춤형 결합지표로 KOSIS 직접 좌표가 아님.",
    "A1123-C005-m1": "1975~1976년생 남성의 학력 비율은 출생코호트 재집계값으로 단일 KOSIS 좌표가 아님.",
    "A1183-C016-m1": "2025년 경제성장률 1.5%는 전망치여서 확정 실적 KOSIS 골드로 사용할 수 없음.",
    "A1191-C011-m1": "외국인과 노인 일자리 참여자 증가 규모는 복수 집단을 재구성한 기사 파생값임.",
    "A1218-C001-m1": "국내 유입 외국인직접투자 분기 증감률에 대응하는 KOSIS 좌표를 찾지 못함.",
    "A1246-C009-m2": "자동차보험 부문 손익은 금융감독 자료로 동일 정의의 KOSIS 통계표를 찾지 못함.",
    "A1436-C005-m1": "'4개 분기 연속'은 시계열 조건의 횟수이며 단일 통계 측정값이 아님.",
    "A1436-C005-m2": "0.2%는 당시 한국은행 전망치로 확정 실적 KOSIS 골드가 아님.",
    "A1478-C003-m2": "'4개 분기'는 연속 조건을 세어 만든 문맥값으로 직접 통계 측정값이 아님.",
    "A1798-C006-m1": "브라질산 닭고기 비중은 국가×품목 결합 집계가 필요해 단일 KOSIS 좌표를 확정하지 못함.",
    "A1922-C001-m2": "추출값 1명은 합계출산율의 정의 문구 '여성 1명이'에서 나온 값으로 측정치가 아님.",
    "A2109-C017-m2": "65세 단일 연령 비정규직 비율은 공개 KOSIS 연령구간과 일치하지 않아 직접 조회할 수 없음.",
    "A2109-C017-m4": "70세 단일 연령 비정규직 비율은 후보 표에서 해당 기간 데이터가 조회되지 않음.",
    "A2568-C004-m1": "가구 수는 가계순자산 산출에 사용한 기사 분모로 국민계정 기준과 동일한 KOSIS 좌표를 확정하지 못함.",
    "A2568-C004-m2": "가구당 가계순자산 증감률은 국민대차대조표와 가구 수를 결합한 파생값임.",
    "A2568-C004-m3": "가구당 가계순자산은 국민대차대조표와 가구 수를 결합한 파생값임.",
    "A2568-C004-m4": "인구는 1인당 가계순자산 산출용 기사 분모로 기준인구 정의를 단일 좌표로 확정하지 못함.",
    "A2568-C004-m5": "1인당 가계순자산 증감률은 국민대차대조표와 인구를 결합한 파생값임.",
    "A2568-C004-m6": "1인당 가계순자산은 국민대차대조표와 인구를 결합한 파생값임.",
    "A2696-C058-m1": "검색된 추가 자녀 계획 표에서 기사 기준연도 2005년 값이 조회되지 않음.",
}


MEASUREMENT_ERRORS = {
    "A1436-C005-m1", "A1478-C003-m2", "A1922-C001-m2",
}


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fill_na(row: dict[str, object], gold_fields: list[str]) -> None:
    for field in gold_fields:
        if row.get(field, "") in ("", None):
            row[field] = NA


def main() -> None:
    fields, rows = read_rows(SOURCE)
    _, news_rows = read_rows(NEWS_METADATA)
    gold_fields = [field for field in fields if field.startswith("gold_")]
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    news_by_claim_text: dict[tuple[str, str], dict[str, str]] = {}
    for news_row in news_rows:
        key = (news_row["claim_id"], news_row["claim_text"])
        existing = news_by_claim_text.get(key)
        if existing and any(
            existing.get(field, "") != news_row.get(field, "")
            for field in ("article_id", "title", "date", "url")
        ):
            raise ValueError(f"conflicting news metadata for {key}")
        news_by_claim_text[key] = news_row

    v2_positive_ids = {
        row["claim_measurement_id"]
        for row in rows if row["gold_label_tier"] == "AUTO_POSITIVE"
    }
    covered = set(NEW_FULL) | set(EXCLUSION_REASONS)
    if v2_positive_ids != covered:
        raise ValueError(
            f"AUTO_POSITIVE coverage mismatch: missing={sorted(v2_positive_ids-covered)}, "
            f"extra={sorted(covered-v2_positive_ids)}"
        )

    for row in rows:
        measurement_id = row["claim_measurement_id"]
        if not row.get("title") or not row.get("url") or not row.get("article_id"):
            metadata = news_by_claim_text.get((row["claim_id"], row["claim_text"]))
            if not metadata:
                raise ValueError(f"news metadata not found for {measurement_id}")
            for field in ("article_id", "title", "date", "url"):
                row[field] = metadata[field]
        if measurement_id in NEW_FULL:
            row.update(NEW_FULL[measurement_id])
            row.update(
                gold_verifiable="Y",
                gold_measurement_correct="Y",
                gold_ready="Y",
                gold_label_tier="FULL_KOSIS",
                gold_retrieved_at=now,
                gold_label_source="KOSIS_MCP_AUTO_V3",
                human_reviewed="N",
            )
        elif measurement_id in EXCLUSION_REASONS:
            is_error = measurement_id in MEASUREMENT_ERRORS
            row.update(
                gold_verifiable="N",
                gold_measurement_correct="N" if is_error else row["gold_measurement_correct"],
                gold_ready="N",
                gold_label_tier="MEASUREMENT_ERROR" if is_error else "MCP_NOT_VERIFIABLE",
                gold_verdict="판단불가",
                gold_coordinate_status="NOT_APPLICABLE",
                gold_confidence="HIGH",
                gold_reason=EXCLUSION_REASONS[measurement_id],
                gold_retrieved_at=now,
                gold_label_source="KOSIS_MCP_AUTO_V3",
                human_reviewed="N",
            )
            for field in gold_fields:
                if field not in {
                    "gold_verifiable", "gold_measurement_correct", "gold_ready",
                    "gold_label_tier", "gold_verdict", "gold_coordinate_status",
                    "gold_confidence", "gold_reason", "gold_retrieved_at",
                    "gold_label_source",
                }:
                    row[field] = NA
        elif row["gold_label_tier"] == "AUTO_NEGATIVE":
            original_correct = row["gold_measurement_correct"]
            row.update(
                gold_verifiable="N",
                gold_ready="N",
                gold_label_tier="MEASUREMENT_ERROR" if original_correct == "N" else "MCP_NOT_VERIFIABLE",
                gold_verdict="판단불가",
                gold_coordinate_status="NOT_APPLICABLE",
                gold_confidence="MEDIUM",
                gold_reason=(
                    "기존 자동 측정 규칙에서 측정값 추출 오류로 분류되어 KOSIS 골드 좌표를 부여하지 않음."
                    if original_correct == "N" else
                    "기존 자동 범위 판정에서 KOSIS 직접 검증 대상이 아닌 것으로 분류됨."
                ),
                gold_retrieved_at=now,
                gold_label_source="KOSIS_MCP_AUTO_V3",
                human_reviewed="N",
            )
            for field in gold_fields:
                if field not in {
                    "gold_verifiable", "gold_measurement_correct", "gold_ready",
                    "gold_label_tier", "gold_verdict", "gold_coordinate_status",
                    "gold_confidence", "gold_reason", "gold_retrieved_at",
                    "gold_label_source",
                }:
                    row[field] = NA

        fill_na(row, gold_fields)
        if not row.get("human_reviewed"):
            row["human_reviewed"] = "N"

    rows.sort(key=lambda row: row["claim_measurement_id"])
    if len(rows) != 112 or len({row["claim_measurement_id"] for row in rows}) != 112:
        raise ValueError("row count or measurement ID uniqueness check failed")
    blanks = [
        (row["claim_measurement_id"], field)
        for row in rows for field in gold_fields
        if row.get(field, "") in ("", None)
    ]
    if blanks:
        raise ValueError(f"blank gold fields remain: {blanks[:20]}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    tier_counts: dict[str, int] = {}
    for row in rows:
        tier = row["gold_label_tier"]
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    manifest = {
        "dataset": "mcp_auto_gold_v3",
        "created_at": now,
        "row_count": len(rows),
        "unique_measurement_count": len({r["claim_measurement_id"] for r in rows}),
        "tier_counts": tier_counts,
        "gold_verifiable_counts": {
            "Y": sum(r["gold_verifiable"] == "Y" for r in rows),
            "N": sum(r["gold_verifiable"] == "N" for r in rows),
        },
        "blank_gold_field_count": 0,
        "human_reviewed": False,
        "sources": {
            str(SOURCE.relative_to(ROOT)).replace("\\", "/"): sha256(SOURCE),
            str(SEARCH_EVIDENCE.relative_to(ROOT)).replace("\\", "/"): sha256(SEARCH_EVIDENCE),
            str(NEWS_METADATA.relative_to(ROOT)).replace("\\", "/"): sha256(NEWS_METADATA),
        },
        "output": str(OUTPUT.relative_to(ROOT)).replace("\\", "/"),
        "output_sha256": sha256(OUTPUT),
        "tier_meaning": {
            "FULL_KOSIS": "KOSIS 표·좌표·기간·원자료·실제값을 확정한 자동 골드",
            "MCP_NOT_VERIFIABLE": "KOSIS 직접 좌표를 확정할 수 없어 N/A와 사유를 기록",
            "MEASUREMENT_ERROR": "기사 문맥값 또는 정의 문구를 측정값으로 잘못 추출",
        },
    }
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
