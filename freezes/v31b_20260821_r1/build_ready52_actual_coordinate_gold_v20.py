from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
READY_PATH = ROOT / "outputs/user_v16_hybrid_results_20260819/06_in_ready_all_latest_prepared_all.csv"
OLD_GOLD_PATH = ROOT / "gold-v1-lock-work/data/gold/mcp_auto_gold_250.csv"
OUT_DIR = ROOT / "data/gold"
OUT_CSV = OUT_DIR / "ready52_actual_coordinate_gold_v20.csv"
OUT_MANIFEST = OUT_DIR / "ready52_actual_coordinate_gold_v20_manifest.json"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def norm(value: object) -> str:
    return " ".join(str(value or "").split()).lower()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def yoy(current: float, previous: float) -> float:
    return (current / previous - 1.0) * 100.0


def exact_old_gold_matches(
    claim: dict[str, str], old_gold: list[dict[str, str]],
) -> list[dict[str, str]]:
    return [
        row for row in old_gold
        if norm(row.get("article_id")) == norm(claim.get("article_id"))
        and norm(row.get("claim_text")) == norm(claim.get("claim_text"))
        and (
            norm(row.get("measurement_text")) == norm(claim.get("measurement_text"))
            or (
                norm(row.get("value")) == norm(claim.get("value"))
                and norm(row.get("unit")) == norm(claim.get("unit"))
            )
        )
    ]


def has_full_coordinate(row: dict[str, str]) -> bool:
    return row.get("gold_ready") == "Y" and all(
        norm(row.get(key)) not in {"", "n/a"}
        for key in (
            "gold_org_id", "gold_tbl_id", "gold_itm_id",
            "gold_obj_l1", "gold_prd_se", "gold_period",
        )
    )


TABLES = {
    "trade": {
        "gold_org_id": "360",
        "gold_tbl_id": "DT_1R11001_FRM101",
        "gold_tbl_name": "품목별 수출액 수입액",
        "gold_obj_l1": "13102112831A.A",
        "gold_obj_l1_name": "총액",
        "gold_evidence_url": "https://kosis.kr/statHtml/statHtml.do?orgId=360&tblId=DT_1R11001_FRM101&vw_cd=MT_ZTITLE",
        "gold_survey_name": "SITC에의한무역통계",
    },
    "semiconductor_y": {
        "gold_org_id": "127",
        "gold_tbl_id": "DT_127005_005",
        "gold_tbl_name": "수출 및 수입액",
        "gold_itm_id": "T001",
        "gold_itm_name": "수출액",
        "gold_obj_l1": "A020101",
        "gold_obj_l1_name": "반도체",
        "gold_evidence_url": "https://kosis.kr/statHtml/statHtml.do?orgId=127&tblId=DT_127005_005&vw_cd=MT_ZTITLE",
        "gold_survey_name": "ICT실태조사",
    },
    "semiconductor_m": {
        "gold_org_id": "127",
        "gold_tbl_id": "DT_092_115_2009_S023",
        "gold_tbl_name": "IT산업별/월별 수출 현황",
        "gold_itm_id": "13103131003T1",
        "gold_itm_name": "IT산업별/월별 수출 현황",
        "gold_obj_l1": "13102131003A.AF11100000",
        "gold_obj_l1_name": "반도체",
        "gold_evidence_url": "https://kosis.kr/statHtml/statHtml.do?orgId=127&tblId=DT_092_115_2009_S023&vw_cd=MT_ZTITLE",
        "gold_survey_name": "ICT수출입통계",
    },
    "workforce": {
        "gold_org_id": "115",
        "gold_tbl_id": "DT_115_2012_AA001",
        "gold_tbl_name": "산업별(중분류) 현재인원(성별 고용형태별 등)",
        "gold_itm_id": "00",
        "gold_itm_name": "산업별(중분류) 현재인원(성별 고용형태별 등)",
        "gold_obj_l1": "AAA.OZ6",
        "gold_obj_l1_name": "조선",
        "gold_evidence_url": "https://kosis.kr/statHtml/statHtml.do?orgId=115&tblId=DT_115_2012_AA001&vw_cd=MT_ZTITLE",
        "gold_survey_name": "산업기술인력수급실태조사",
    },
    "cpi": {
        "gold_org_id": "101",
        "gold_tbl_id": "DT_1J22041",
        "gold_tbl_name": "연도별 소비자물가 등락률",
        "gold_itm_id": "T",
        "gold_itm_name": "전년비",
        "gold_obj_l1": "0",
        "gold_obj_l1_name": "총지수",
        "gold_evidence_url": "https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1J22041&vw_cd=MT_ZTITLE",
        "gold_survey_name": "소비자물가조사",
    },
}


def manual_spec(
    table: str, *, itm_id: str | None = None, itm_name: str | None = None,
    obj_l2: str = "", obj_l2_name: str = "", prd_se: str,
    period: str, previous_period: str = "", derivation: str,
    source_unit: str, source_value: float, previous_value: float | None = None,
    actual_value: float | None = None, denominator_obj_l2: str = "",
    denominator_obj_l2_name: str = "", reason: str,
) -> dict[str, str]:
    row = dict(TABLES[table])
    if itm_id:
        row["gold_itm_id"] = itm_id
    if itm_name:
        row["gold_itm_name"] = itm_name
    row.update({
        "gold_obj_l2": obj_l2,
        "gold_obj_l2_name": obj_l2_name,
        "gold_prd_se": prd_se,
        "gold_period": period,
        "gold_previous_period": previous_period,
        "gold_derivation_method": derivation,
        "gold_source_unit": source_unit,
        "gold_source_value": str(source_value),
        "gold_source_previous_value": "" if previous_value is None else str(previous_value),
        "gold_actual_value": str(source_value if actual_value is None else actual_value),
        "gold_denominator_obj_l2": denominator_obj_l2,
        "gold_denominator_obj_l2_name": denominator_obj_l2_name,
        "gold_coordinate_status": "UNIQUE",
        "gold_confidence": "HIGH",
        "gold_reason": reason,
        "gold_ready": "Y",
        "gold_verifiable": "Y",
        "gold_measurement_correct": "Y",
        "gold_label_tier": "FULL_KOSIS_MCP_V20",
        "gold_label_source": "KOSIS_MCP_ACTUAL_QUERY_20260819",
        "human_reviewed": "N",
    })
    return row


TRADE_EXPORT = {2022: 683_584_760, 2023: 632_225_824, 2024: 683_609_488}
TRADE_IMPORT = {2022: 731_369_657, 2023: 642_572_126, 2024: 631_767_209}
SEMICONDUCTOR_Y = {2022: 130_865, 2023: 99_704, 2024: 142_086}
WORKFORCE = {2014: 69_766, 2022: 58_042, 2023: 58_528}
FOREIGN = {2022: 877, 2023: 2_563}


MANUAL: dict[str, dict[str, str]] = {
    "A0006-SPBCB2234D20-m1": manual_spec(
        "trade", itm_id="13103112831T2", itm_name="수입액", prd_se="Y",
        period="2024", previous_period="2023", derivation="YOY_FROM_LEVEL",
        source_unit="천달러", source_value=TRADE_IMPORT[2024],
        previous_value=TRADE_IMPORT[2023],
        actual_value=yoy(TRADE_IMPORT[2024], TRADE_IMPORT[2023]),
        reason="MCP로 총액·수입액·연 주기와 2023~2024 실제 값을 확인",
    ),
    "A0006-SP9461F3F4FE-m1": manual_spec(
        "trade", itm_id="13103112831T1", itm_name="수출액", prd_se="M",
        period="202412", derivation="DIRECT", source_unit="천달러",
        source_value=61_359_250,
        reason="기사의 '12월'을 202412로 보존하고 MCP 월 자료를 확인",
    ),
    "A0018-SP32C9008706-m3": manual_spec(
        "trade", itm_id="13103112831T1", itm_name="수출액", prd_se="Y",
        period="2024", previous_period="2023", derivation="YOY_FROM_LEVEL",
        source_unit="천달러", source_value=TRADE_EXPORT[2024],
        previous_value=TRADE_EXPORT[2023],
        actual_value=yoy(TRADE_EXPORT[2024], TRADE_EXPORT[2023]),
        reason="MCP로 총액·수출액·연 주기와 비교기간을 확인",
    ),
    "A0018-SPBAED6BB4CA-m2": manual_spec(
        "trade", itm_id="13103112831T1", itm_name="수출액", prd_se="Y",
        period="2024", previous_period="2022", derivation="DIFF_FROM_LEVEL",
        source_unit="천달러", source_value=TRADE_EXPORT[2024],
        previous_value=TRADE_EXPORT[2022],
        actual_value=TRADE_EXPORT[2024] - TRADE_EXPORT[2022],
        reason="MCP로 2024년과 2022년의 같은 공식 좌표를 확인",
    ),
    "A0018-SP33EC69A061-m1": manual_spec(
        "trade", itm_id="13103112831T2", itm_name="수입액", prd_se="Y",
        period="2024", previous_period="2023", derivation="YOY_FROM_LEVEL",
        source_unit="천달러", source_value=TRADE_IMPORT[2024],
        previous_value=TRADE_IMPORT[2023],
        actual_value=yoy(TRADE_IMPORT[2024], TRADE_IMPORT[2023]),
        reason="MCP로 총액·수입액·연 주기와 비교기간을 확인",
    ),
    "A0006-SP9282109973-m1": manual_spec(
        "semiconductor_y", prd_se="Y", period="2024", previous_period="2023",
        derivation="YOY_FROM_LEVEL", source_unit="백만US$",
        source_value=SEMICONDUCTOR_Y[2024], previous_value=SEMICONDUCTOR_Y[2023],
        actual_value=yoy(SEMICONDUCTOR_Y[2024], SEMICONDUCTOR_Y[2023]),
        reason="MCP로 반도체·수출액 분류와 2023~2024 실제 값을 확인",
    ),
    "A0018-SP8114050F3A-m1": manual_spec(
        "trade", itm_id="13103112831T1", itm_name="수출액", prd_se="M",
        period="202408", previous_period="202308", derivation="YOY_FROM_LEVEL",
        source_unit="천달러", source_value=57_642_924,
        previous_value=51_994_074, actual_value=yoy(57_642_924, 51_994_074),
        reason="기사 시점 기준 '작년 8월'을 202408로 복원하고 총수출 월 좌표를 MCP로 확인",
    ),
    "A0018-SP8114050F3A-m2": manual_spec(
        "semiconductor_m", prd_se="M", period="202412", previous_period="202312",
        derivation="YOY_FROM_LEVEL", source_unit="달러",
        source_value=14_511_028_387, previous_value=11_066_415_208,
        actual_value=yoy(14_511_028_387, 11_066_415_208),
        reason="MCP로 반도체 월 수출 좌표와 2023·2024년 12월 값을 확인",
    ),
    "A0031-SP041EDC0971-m1": manual_spec(
        "trade", itm_id="13103112831T1", itm_name="수출액", prd_se="Y",
        period="2024", previous_period="2023", derivation="YOY_FROM_LEVEL",
        source_unit="천달러", source_value=TRADE_EXPORT[2024],
        previous_value=TRADE_EXPORT[2023],
        actual_value=yoy(TRADE_EXPORT[2024], TRADE_EXPORT[2023]),
        reason="문장의 전망 대상인 전체 수출 증가율을 총액·수출액 좌표에 연결",
    ),
    "A0012-SPE7F554D64E-m1": manual_spec(
        "workforce", obj_l2="AA001", obj_l2_name="현재인원", prd_se="Y",
        period="2023", derivation="DIRECT", source_unit="명",
        source_value=WORKFORCE[2023],
        reason="MCP로 조선·현재인원·2023년 실제 값을 확인",
    ),
    "A0012-SPE7F554D64E-m2": manual_spec(
        "workforce", obj_l2="AA001", obj_l2_name="현재인원", prd_se="Y",
        period="2023", previous_period="2022", derivation="YOY_FROM_LEVEL",
        source_unit="명", source_value=WORKFORCE[2023], previous_value=WORKFORCE[2022],
        actual_value=yoy(WORKFORCE[2023], WORKFORCE[2022]),
        reason="MCP로 조선 현재인원의 동일 좌표·비교기간을 확인",
    ),
    "A0012-SP80940BC114-m2": manual_spec(
        "workforce", obj_l2="AA001", obj_l2_name="현재인원", prd_se="Y",
        period="2022", derivation="DIRECT", source_unit="명",
        source_value=WORKFORCE[2022],
        reason="MCP로 조선·현재인원·2022년 실제 값을 확인",
    ),
    "A0012-SP80940BC114-m3": manual_spec(
        "workforce", obj_l2="AA001", obj_l2_name="현재인원", prd_se="Y",
        period="2022", previous_period="2014", derivation="DIFF_FROM_LEVEL",
        source_unit="명", source_value=WORKFORCE[2022], previous_value=WORKFORCE[2014],
        actual_value=WORKFORCE[2022] - WORKFORCE[2014],
        reason="MCP로 2014년과 2022년의 같은 조선 현재인원 좌표를 확인",
    ),
    "A0012-SP80940BC114-m4": manual_spec(
        "workforce", obj_l2="AA001", obj_l2_name="현재인원", prd_se="Y",
        period="2023", previous_period="2022", derivation="DIFF_FROM_LEVEL",
        source_unit="명", source_value=WORKFORCE[2023], previous_value=WORKFORCE[2022],
        actual_value=WORKFORCE[2023] - WORKFORCE[2022],
        reason="MCP로 2022년과 2023년의 같은 조선 현재인원 좌표를 확인",
    ),
    "A0012-SP13E0E2E6EE-m2": manual_spec(
        "workforce", obj_l2="70", obj_l2_name="외국인인력", prd_se="Y",
        period="2022", derivation="DIRECT", source_unit="명", source_value=FOREIGN[2022],
        reason="MCP로 조선·외국인인력·2022년 실제 값을 확인",
    ),
    "A0012-SP13E0E2E6EE-m3": manual_spec(
        "workforce", obj_l2="70", obj_l2_name="외국인인력", prd_se="Y",
        period="2023", previous_period="2022", derivation="RATIO_FROM_LEVEL",
        source_unit="명", source_value=FOREIGN[2023], previous_value=FOREIGN[2022],
        actual_value=FOREIGN[2023] / FOREIGN[2022],
        reason="MCP로 2022년과 2023년 조선 외국인인력의 동일 좌표를 확인",
    ),
    "A0012-SPFEFB3037E3-m1": manual_spec(
        "workforce", obj_l2="70", obj_l2_name="외국인인력", prd_se="Y",
        period="2022", derivation="SHARE_FROM_LEVEL", source_unit="명",
        source_value=FOREIGN[2022], previous_value=WORKFORCE[2022],
        actual_value=FOREIGN[2022] / WORKFORCE[2022] * 100.0,
        denominator_obj_l2="AA001", denominator_obj_l2_name="현재인원",
        reason="MCP로 분자 외국인인력과 분모 현재인원의 공식 좌표를 확인",
    ),
    "A0012-SPFEFB3037E3-m2": manual_spec(
        "workforce", obj_l2="70", obj_l2_name="외국인인력", prd_se="Y",
        period="2023", derivation="SHARE_FROM_LEVEL", source_unit="명",
        source_value=FOREIGN[2023], previous_value=WORKFORCE[2023],
        actual_value=FOREIGN[2023] / WORKFORCE[2023] * 100.0,
        denominator_obj_l2="AA001", denominator_obj_l2_name="현재인원",
        reason="MCP로 분자 외국인인력과 분모 현재인원의 공식 좌표를 확인",
    ),
    "A0041-SP87530E5592-m3": manual_spec(
        "cpi", prd_se="Y", period="2024", derivation="DIRECT",
        source_unit="%", source_value=2.3,
        reason="MCP로 총지수·전년비·연 주기와 2024년 실제 값을 확인",
    ),
}


def main() -> None:
    ready_rows = [row for row in read_csv(READY_PATH) if row.get("mapping_gate") == "READY"]
    old_gold = read_csv(OLD_GOLD_PATH)
    output: list[dict[str, str]] = []
    inherited = 0

    for claim in ready_rows:
        claim_id = claim["claim_measurement_id"]
        full = [row for row in exact_old_gold_matches(claim, old_gold) if has_full_coordinate(row)]
        if full:
            source = dict(full[0])
            source["gold_inherited_claim_measurement_id"] = source.get("claim_measurement_id", "")
            source["claim_measurement_id"] = claim_id
            source["claim_id"] = claim.get("claim_id", claim_id.rsplit("-m", 1)[0])
            source["gold_label_source"] = "KOSIS_MCP_AUTO_V1_RELOCKED_V20"
            source["gold_relock_reason"] = "READY52 기사·주장·측정값 완전일치 후 기존 실제 좌표 재잠금"
            for key, value in claim.items():
                source.setdefault(key, value)
            output.append(source)
            inherited += 1
            continue
        if claim_id not in MANUAL:
            continue
        row = dict(claim)
        row.update(MANUAL[claim_id])
        row.update({
            "claim_id": claim.get("claim_id", claim_id.rsplit("-m", 1)[0]),
            "gold_retrieved_at": "2026-08-19T00:00:00+09:00",
            "gold_mcp_validation": "search_or_known_table->validate->table_info->get_data",
        })
        output.append(row)

    output.sort(key=lambda row: row["claim_measurement_id"])
    ids = [row["claim_measurement_id"] for row in output]
    if len(output) < 30:
        raise RuntimeError(f"actual coordinate gold is below target: {len(output)}")
    if len(ids) != len(set(ids)):
        raise RuntimeError("duplicate claim_measurement_id in coordinate gold")
    for row in output:
        for key in ("gold_org_id", "gold_tbl_id", "gold_itm_id", "gold_obj_l1", "gold_prd_se", "gold_period"):
            if norm(row.get(key)) in {"", "n/a"}:
                raise RuntimeError(f"missing {key}: {row['claim_measurement_id']}")

    fields: list[str] = []
    preferred = [
        "claim_id", "claim_measurement_id", "article_id", "title", "date", "url",
        "claim_text", "measurement_text", "measurement_indicator", "measurement_item",
        "value", "unit", "measurement_period", "measurement_prd_se",
    ]
    for key in preferred:
        if any(key in row for row in output) and key not in fields:
            fields.append(key)
    for row in output:
        for key in row:
            if key not in fields:
                fields.append(key)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(output)

    table_counts: dict[str, int] = {}
    for row in output:
        key = f"{row['gold_org_id']}/{row['gold_tbl_id']}"
        table_counts[key] = table_counts.get(key, 0) + 1
    manifest = {
        "schema_version": "ready52-actual-coordinate-gold-v20",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ready_source": str(READY_PATH),
        "ready_source_sha256": sha256(READY_PATH),
        "previous_gold_source": str(OLD_GOLD_PATH),
        "previous_gold_source_sha256": sha256(OLD_GOLD_PATH),
        "ready_total": len(ready_rows),
        "coordinate_gold_rows": len(output),
        "coverage_of_ready": len(output) / len(ready_rows),
        "inherited_actual_coordinates": inherited,
        "new_mcp_actual_coordinates": len(output) - inherited,
        "table_counts": table_counts,
        "excluded_policy": "공식 집계 좌표가 없거나 KOSIS 범위 밖인 READY는 골드로 만들지 않음",
        "mcp_procedure": "KOSIS search/known table -> validate -> table_info -> get_data",
        "output_sha256": sha256(OUT_CSV),
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
