"""Resolve the eight manual remapping cases with KOSIS metadata and values."""

from collections import Counter
import csv
from pathlib import Path


BASE = Path("outputs/bteam_review")
INPUT = BASE / "submission_match_candidates_recheck.csv"
MANUAL_33_INPUT = BASE / "submission_match_candidates_manual_reviewed.csv"
MASTER_INPUT = BASE / "final_verified_filled_2001_manual_v5.csv"

RESOLVED_OUTPUT = BASE / "submission_recheck_8_resolved.csv"
CONFIRMED_6_OUTPUT = BASE / "submission_recheck_8_confirmed.csv"
UNVERIFIABLE_2_OUTPUT = BASE / "submission_recheck_8_unverifiable.csv"
FINAL_33_OUTPUT = BASE / "submission_match_candidates_final_33_v6.csv"
CONFIRMED_21_OUTPUT = BASE / "submission_confirmed_matches_v6.csv"
MASTER_OUTPUT = BASE / "final_verified_filled_2001_remapped_v6.csv"
REPORT_OUTPUT = BASE / "submission_recheck_8_report.md"


RESOLUTIONS = {
    "C06797": {
        "decision": "직접검증불가",
        "status": "판단불가_KOSIS지역집계없음",
        "reason": "주장 대상은 2025년 1월 동남아 수출 -3.8%이지만 KOSIS 국가별 수출표에는 동남아 집계 분류코드가 없음",
        "evidence": "DT_1R11006_FRM101 메타데이터의 국가별 분류 전체를 확인했으나 동남아·아세안 집계코드가 없어 임의 국가 합산을 하지 않음",
        "method": "KOSIS 메타데이터 분류코드 확인",
        "updates": {
            "org_id": "360",
            "tbl_id": "DT_1R11006_FRM101",
            "obj_l1": "",
            "obj_l2": "",
            "itm_id": "13103103829T1",
            "prd_se": "M",
            "claim_type": "CHANGE_RATE",
            "claim_number": "-3.8",
            "actual_value": "",
            "actual_period": "202501",
            "actual_prev_value": "",
            "actual_prev_period": "202401",
            "actual_change_pct": "",
            "actual_change_point": "",
            "actual_number": "",
            "aggregation_rule": "동남아 국가범위 미확정",
        },
    },
    "C12150": {
        "decision": "확정일치",
        "status": "검증완료_재매핑확정일치",
        "reason": "월별 소비자물가 등락률의 총지수·전년동월비로 2025년 1~4월을 모두 확인",
        "evidence": "202501 2.2%, 202502 2.0%, 202503 2.1%, 202504 2.1%로 문장의 네 달 연속 2%대 주장과 일치",
        "method": "KOSIS 월별 등락률 다중시점 직접 확인",
        "updates": {
            "org_id": "101",
            "tbl_id": "DT_1J22042",
            "obj_l1": "0",
            "obj_l2": "",
            "itm_id": "T03",
            "prd_se": "M",
            "claim_type": "LEVEL",
            "claim_number": "2.1",
            "actual_value": "2.1",
            "actual_period": "202504",
            "actual_prev_value": "",
            "actual_prev_period": "",
            "actual_change_pct": "",
            "actual_change_point": "",
            "actual_number": "2.1",
            "aggregation_rule": "2025년 1~4월 네 시점 수동 확인; 대표값은 4월",
        },
    },
    "C15304": {
        "decision": "확정일치",
        "status": "검증완료_재매핑확정일치",
        "reason": "품목별 소비자물가지수의 전국·석유류로 재매핑하고 전년동월비 계산",
        "evidence": "석유류 지수 202405 126.88 -> 202505 123.93, 전년동월비 -2.325%로 주장 -2.3%와 일치",
        "method": "KOSIS 지수 두 시점 전년동월비 계산",
        "updates": {
            "org_id": "101",
            "tbl_id": "DT_1J22112",
            "obj_l1": "T10",
            "obj_l2": "B05",
            "itm_id": "T",
            "prd_se": "M",
            "claim_type": "CHANGE_RATE",
            "claim_number": "-2.3",
            "actual_value": "123.93",
            "actual_period": "202505",
            "actual_prev_value": "126.88",
            "actual_prev_period": "202405",
            "actual_change_pct": "-2.325031525851189",
            "actual_change_point": "-2.95",
            "actual_number": "-2.325031525851189",
            "aggregation_rule": "전년동월비",
        },
    },
    "C18098": {
        "decision": "확정일치",
        "status": "검증완료_재매핑확정일치",
        "reason": "품목별 소비자물가지수의 전국·석유류로 재매핑하고 전년동월비 계산",
        "evidence": "석유류 지수 202406 123.18 -> 202506 123.49, 전년동월비 0.252%로 한 자리 반올림 시 주장 0.3%와 일치",
        "method": "KOSIS 지수 두 시점 전년동월비 계산",
        "updates": {
            "org_id": "101",
            "tbl_id": "DT_1J22112",
            "obj_l1": "T10",
            "obj_l2": "B05",
            "itm_id": "T",
            "prd_se": "M",
            "claim_type": "CHANGE_RATE",
            "claim_number": "0.3",
            "actual_value": "123.49",
            "actual_period": "202506",
            "actual_prev_value": "123.18",
            "actual_prev_period": "202406",
            "actual_change_pct": "0.251664231206355",
            "actual_change_point": "0.31",
            "actual_number": "0.251664231206355",
            "aggregation_rule": "전년동월비",
        },
    },
    "C18208": {
        "decision": "확정일치",
        "status": "검증완료_재매핑확정일치",
        "reason": "품목별 소비자물가지수의 전국·외식으로 재매핑하고 전년동월비 계산",
        "evidence": "외식 지수 202406 121.08 -> 202506 124.79, 전년동월비 3.064%로 한 자리 반올림 시 주장 3.1%와 일치",
        "method": "KOSIS 지수 두 시점 전년동월비 계산",
        "updates": {
            "org_id": "101",
            "tbl_id": "DT_1J22112",
            "obj_l1": "T10",
            "obj_l2": "F01",
            "itm_id": "T",
            "prd_se": "M",
            "claim_type": "CHANGE_RATE",
            "claim_number": "3.1",
            "actual_value": "124.79",
            "actual_period": "202506",
            "actual_prev_value": "121.08",
            "actual_prev_period": "202406",
            "actual_change_pct": "3.0640898579451665",
            "actual_change_point": "3.71",
            "actual_number": "3.0640898579451665",
            "aggregation_rule": "전년동월비",
        },
    },
    "C19960": {
        "decision": "확정일치",
        "status": "검증완료_재매핑확정일치",
        "reason": "연령별 경제활동인구 총괄의 20~29세·고용률로 재매핑하고 전년동월 비교",
        "evidence": "20대 고용률 202409 60.9% -> 202509 60.7%, 전년동월 대비 -0.2%p로 주장과 일치",
        "method": "KOSIS 고용률 두 시점 포인트 차이",
        "updates": {
            "org_id": "101",
            "tbl_id": "DT_1DA7002S",
            "obj_l1": "20",
            "obj_l2": "",
            "itm_id": "T90",
            "prd_se": "M",
            "claim_type": "POINT_CHANGE",
            "claim_number": "-0.2",
            "actual_value": "60.7",
            "actual_period": "202509",
            "actual_prev_value": "60.9",
            "actual_prev_period": "202409",
            "actual_change_pct": "-0.3284072249589491",
            "actual_change_point": "-0.2",
            "actual_number": "-0.2",
            "aggregation_rule": "전년동월 포인트 차이",
        },
    },
    "C20235": {
        "decision": "확정일치",
        "status": "검증완료_재매핑확정일치",
        "reason": "연령별 경제활동인구 총괄의 15~29세 경제활동인구와 실업자를 3개월 합산해 분기 실업률 계산",
        "evidence": "2024Q3 584.5/11,875.2=4.922%(4.9%), 2025Q3 573.6/11,340.9=5.058%(5.1%); 공표 반올림값 차이 0.2%p로 주장과 일치",
        "method": "KOSIS 월별 경제활동인구·실업자 3개월 합산 비율",
        "updates": {
            "org_id": "101",
            "tbl_id": "DT_1DA7002S",
            "obj_l1": "75",
            "obj_l2": "",
            "itm_id": "T20+T40",
            "prd_se": "Q",
            "claim_type": "POINT_CHANGE",
            "claim_number": "0.2",
            "actual_value": "5.057799645530778",
            "actual_period": "2025Q3",
            "actual_prev_value": "4.9220223659391",
            "actual_prev_period": "2024Q3",
            "actual_change_pct": "",
            "actual_change_point": "0.2",
            "actual_number": "0.2",
            "aggregation_rule": "분기 실업자 합계 / 분기 경제활동인구 합계 * 100; 공표 한 자리 반올림 후 차이",
        },
    },
    "C20290": {
        "decision": "직접검증불가",
        "status": "판단불가_KOSIS기여도미제공",
        "reason": "가공식품 물가상승률 3.5%는 확인되지만 주장 대상 0.30%p 기여도는 KOSIS 소비자물가 표에 제공되지 않음",
        "evidence": "가공식품 지수 202410 120.56 -> 202510 124.74, 전년동월비 3.467%(3.5%)는 일치. 소비자물가조사 15개 KOSIS 표 메타에서 기여도·가중치 항목은 확인되지 않음",
        "method": "KOSIS 가공식품 지수 부분확인 + 전체 CPI 메타데이터 조사",
        "updates": {
            "org_id": "101",
            "tbl_id": "DT_1J22112",
            "obj_l1": "T10",
            "obj_l2": "B01",
            "itm_id": "T",
            "prd_se": "M",
            "claim_type": "POINT_CHANGE",
            "claim_number": "0.3",
            "actual_value": "124.74",
            "actual_period": "202510",
            "actual_prev_value": "120.56",
            "actual_prev_period": "202410",
            "actual_change_pct": "3.4671532846715265",
            "actual_change_point": "",
            "actual_number": "",
            "aggregation_rule": "가공식품 전년동월비는 확인; 전체 물가 기여도 산출자료 없음",
        },
    },
}


REMAP_FIELDS = [
    "obj_l2",
    "remap_decision",
    "remap_final_status",
    "remap_reason",
    "remap_kosis_evidence",
    "verification_method",
    "aggregation_rule",
    "remap_checked_at",
]


def read_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return list(reader), list(reader.fieldnames or [])


def union_fields(base_fields, rows):
    fields = list(base_fields)
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    return fields


def write_rows(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def apply_resolution(row):
    claim_id = row["claim_id"]
    resolution = RESOLUTIONS[claim_id]
    updated = dict(row)
    updated.update(resolution["updates"])
    updated.update({
        "remap_decision": resolution["decision"],
        "remap_final_status": resolution["status"],
        "remap_reason": resolution["reason"],
        "remap_kosis_evidence": resolution["evidence"],
        "verification_method": resolution["method"],
        "aggregation_rule": resolution["updates"].get("aggregation_rule", ""),
        "remap_checked_at": "2026-07-14",
        "manual_decision": resolution["decision"],
        "manual_final_status": resolution["status"],
        "manual_mapping_reason": resolution["reason"],
        "manual_kosis_evidence": resolution["evidence"],
    })

    if resolution["decision"] == "확정일치":
        verdict = "일치"
    else:
        verdict = "판단불가"
    for field in ("verdict", "refined_verdict"):
        if field in updated:
            updated[field] = verdict
    for field in ("final_status", "refined_final_status", "audit_status"):
        if field in updated:
            updated[field] = resolution["status"]
    for field in ("judge_note", "refined_judge_note"):
        if field in updated:
            updated[field] = resolution["evidence"]
    for field in ("refined_claim_number",):
        if field in updated:
            updated[field] = resolution["updates"].get("claim_number", updated[field])
    for field in ("refined_actual_number",):
        if field in updated:
            updated[field] = resolution["updates"].get("actual_number", updated[field])
    return updated


def markdown_cell(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def write_report(resolved, master_counts):
    decision_counts = Counter(row["remap_decision"] for row in resolved)
    latest = {
        "확정 일치": sum(count for status, count in master_counts.items() if status.startswith("검증완료")),
        "재검토": sum(count for status, count in master_counts.items() if status.startswith("재검토")),
        "판단불가": sum(count for status, count in master_counts.items() if status.startswith("판단불가")),
    }
    lines = [
        "# 재매핑 필요 8건 처리 보고서",
        "",
        "## 결론",
        "",
        f"- 재매핑 후 확정 일치: {decision_counts['확정일치']}건",
        f"- KOSIS 직접검증 불가: {decision_counts['직접검증불가']}건",
        f"- 2,001건 최신 상태: 확정 일치 {latest['확정 일치']}건 / 재검토 {latest['재검토']}건 / 판단불가 {latest['판단불가']}건",
        "- C20290은 가공식품 상승률 3.5%까지는 확인했지만 목표값인 물가 기여도 0.30%p가 KOSIS에 없어 판단불가로 유지했다.",
        "",
        "## 8건 상세",
        "",
        "| claim_id | 주장 원문 | 최종 판정 | 새 매핑/계산 | KOSIS 근거 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in resolved:
        mapping = (
            f"{row.get('org_id')}/{row.get('tbl_id')} · objL1={row.get('obj_l1')}"
            f" · objL2={row.get('obj_l2')} · itm={row.get('itm_id')} · {row.get('prd_se')}"
            f" · {row.get('aggregation_rule')}"
        )
        lines.append(
            "| {claim_id} | {claim} | {decision} | {mapping} | {evidence} |".format(
                claim_id=markdown_cell(row["claim_id"]),
                claim=markdown_cell(row["claim_text"]),
                decision=markdown_cell(row["remap_decision"]),
                mapping=markdown_cell(mapping),
                evidence=markdown_cell(row["remap_kosis_evidence"]),
            )
        )
    REPORT_OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    input_rows, input_fields = read_rows(INPUT)
    expected_ids = set(RESOLUTIONS)
    actual_ids = {row["claim_id"] for row in input_rows}
    if len(input_rows) != 8 or actual_ids != expected_ids:
        raise RuntimeError(
            f"재매핑 대상 불일치: rows={len(input_rows)}, missing={sorted(expected_ids - actual_ids)}, extra={sorted(actual_ids - expected_ids)}"
        )

    resolved = [apply_resolution(row) for row in input_rows]
    resolved_fields = union_fields(input_fields + REMAP_FIELDS, resolved)
    write_rows(RESOLVED_OUTPUT, resolved, resolved_fields)
    write_rows(CONFIRMED_6_OUTPUT, [r for r in resolved if r["remap_decision"] == "확정일치"], resolved_fields)
    write_rows(UNVERIFIABLE_2_OUTPUT, [r for r in resolved if r["remap_decision"] == "직접검증불가"], resolved_fields)

    manual_rows, manual_fields = read_rows(MANUAL_33_INPUT)
    resolved_by_id = {row["claim_id"]: row for row in resolved}
    final_33 = []
    for row in manual_rows:
        if row["claim_id"] in resolved_by_id:
            final_33.append(resolved_by_id[row["claim_id"]])
        else:
            unchanged = dict(row)
            unchanged.update({field: "" for field in REMAP_FIELDS if field not in unchanged})
            final_33.append(unchanged)
    final_33_fields = union_fields(manual_fields + REMAP_FIELDS, final_33)
    write_rows(FINAL_33_OUTPUT, final_33, final_33_fields)
    confirmed_21 = [row for row in final_33 if row.get("manual_decision") == "확정일치"]
    write_rows(CONFIRMED_21_OUTPUT, confirmed_21, final_33_fields)

    master_rows, master_fields = read_rows(MASTER_INPUT)
    master_output = []
    for row in master_rows:
        if row["claim_id"] in RESOLUTIONS:
            updated = apply_resolution(row)
            updated["audit_status"] = updated["remap_final_status"]
            master_output.append(updated)
        else:
            unchanged = dict(row)
            unchanged.update({field: "" for field in REMAP_FIELDS if field not in unchanged})
            master_output.append(unchanged)
    master_output_fields = union_fields(master_fields + REMAP_FIELDS, master_output)
    write_rows(MASTER_OUTPUT, master_output, master_output_fields)

    master_counts = Counter(row.get("audit_status", "") for row in master_output)
    write_report(resolved, master_counts)

    confirmed_count = sum(status.startswith("검증완료") for row in master_output for status in [row.get("audit_status", "")])
    recheck_count = sum((row.get("audit_status") or "").startswith("재검토") for row in master_output)
    unverifiable_count = sum((row.get("audit_status") or "").startswith("판단불가") for row in master_output)
    print(f"8건 처리: {dict(Counter(row['remap_decision'] for row in resolved))}")
    print(f"33건 최종: {dict(Counter(row['manual_decision'] for row in final_33))}")
    print(f"2,001건 최신: 확정 {confirmed_count} / 재검토 {recheck_count} / 판단불가 {unverifiable_count}")
    print(f"보고서: {REPORT_OUTPUT}")


if __name__ == "__main__":
    main()
