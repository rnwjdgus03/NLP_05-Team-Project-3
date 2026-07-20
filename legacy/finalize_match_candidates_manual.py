"""Finalize the semantic review of the 33 KOSIS numeric match candidates."""

from collections import Counter
import csv
from pathlib import Path


BASE = Path("outputs/bteam_review")
INPUT = BASE / "submission_match_candidates.csv"
MASTER_INPUT = BASE / "final_verified_filled_2001_audited_v4.csv"
REVIEWED_OUTPUT = BASE / "submission_match_candidates_manual_reviewed.csv"
CONFIRMED_OUTPUT = BASE / "submission_confirmed_matches.csv"
RECHECK_OUTPUT = BASE / "submission_match_candidates_recheck.csv"
UNVERIFIABLE_OUTPUT = BASE / "submission_match_candidates_unverifiable.csv"
MASTER_OUTPUT = BASE / "final_verified_filled_2001_manual_v5.csv"
REPORT_OUTPUT = BASE / "submission_match_candidates_manual_report.md"


CONFIRMED = {
    "C00090": (
        "품목별 수출액 수입액/총액/수출액/천달러, 월별 시점이 주장과 일치",
        "202312 57,573,193 -> 202412 61,359,250천달러, 전년동월비 6.576%로 주장 6.6%와 일치",
    ),
    "C00381": (
        "소비자물가지수(2020=100)/전국/총지수, 연간 시점이 주장과 일치",
        "2023 111.59 -> 2024 114.18, 상승률 2.321%로 주장 2.3%와 일치",
    ),
    "C00765": (
        "가구당 월평균 가계수지/소득/전체가구/원, 분기 시점이 주장과 일치",
        "2024년 2분기 4,961,283.732원 -> 3분기 5,255,452.363원, 5.929% 증가로 주장 5.9%와 일치",
    ),
    "C02892": (
        "연령별 경제활동인구 총괄/15~29세/고용률/%와 2021년 5월 시점이 일치",
        "202105 청년 고용률 44.4%로 주장 44.4%와 일치",
    ),
    "C02893": (
        "연령별 경제활동인구 총괄/15~29세/고용률/%와 2020년 12월 시점이 일치",
        "202012 청년 고용률 41.3%로 주장 41.3%와 일치",
    ),
    "C03497": (
        "재별 및 상품군별 소매판매액지수/총지수/불변지수, 연간 시점이 주장과 일치",
        "2002 62.5 -> 2003 60.5, 감소율 -3.2%로 주장 -3.2%와 일치",
    ),
    "C04394": (
        "품목별 수출액 수입액/총액/수출액/천달러, 연간 시점이 주장과 일치",
        "2023 632,225,824 -> 2024 683,609,488천달러, 8.127% 증가로 주장 8.2%와 일치",
    ),
    "C05780": (
        "출생아수 합계출산율 자연증가 등/출생아수(명), 연간 시점이 주장과 일치",
        "2023 230,028명 -> 2024 238,317명, 3.603% 증가로 주장 3.6%와 일치",
    ),
    "C06679": (
        "월별 소비자물가 등락률/생활물가지수/전년동월비(%), 월별 시점이 주장과 일치",
        "202410 생활물가지수 전년동월비 1.2%로 주장 1.2%와 일치",
    ),
    "C09952": (
        "성별 경제활동인구 총괄/계/실업률/%, 월별 시점이 주장과 일치",
        "202503 전체 실업률 3.1%로 주장 3.1%와 일치",
    ),
    "C15976": (
        "성별 경제활동인구 총괄/계/고용률/%, 전년동월 비교로 시점을 교정",
        "202405 63.5% -> 202505 63.8%, 전년동월 대비 0.3%p 상승으로 주장과 일치",
    ),
    "C15980": (
        "성별 경제활동인구 총괄/계/실업률/%, 연간에서 월간으로 주기를 교정",
        "202505 전체 실업률 2.8%로 주장 2.8%와 일치",
    ),
    "C16083": (
        "성별 경제활동인구 총괄/계/고용률/%, 전년동월 비교로 시점을 교정",
        "202405 63.5% -> 202505 63.8%, 전년동월 대비 0.3%p 상승으로 주장과 일치",
    ),
    "C18109": (
        "월별 소비자물가 등락률/생활물가지수/전년동월비(%), 두 월의 등락률 차이를 비교",
        "202505 2.3% -> 202506 2.5%, 상승폭 0.2%p로 주장과 일치",
    ),
    "C20300": (
        "월별 소비자물가 등락률/총지수/전년동월비(%), 월별 시점이 주장과 일치",
        "202407 총지수 전년동월비 2.6%로 주장 2.6%와 일치",
    ),
}


RECHECK = {
    "C06797": "주장 숫자 -3.8%는 동남아 수출인데 미국 코드가 선택됐고 연간 시점도 기사 속 1월 실적과 다름",
    "C12150": "한 문장에 1~4월 수치가 함께 있어 검증 대상 숫자와 목표 월을 먼저 확정해야 함",
    "C15304": "석유류 물가 -2.3% 주장에 전국 소비자물가 총지수 연간값이 연결됨. 석유류 세부항목과 2025년 5월로 재매핑 필요",
    "C18098": "석유류 물가 0.3% 주장에 소비자물가 총지수가 연결됨. 석유류 세부항목으로 재매핑 필요",
    "C18208": "외식 물가 3.1% 주장에 소비자물가 총지수와 미래 연간시점이 연결됨. 외식 세부항목과 해당 월로 재매핑 필요",
    "C19960": "20대 고용률 주장에 전 연령 성별 총괄표가 연결됐고 전년동월 비교도 아닌 전월 비교가 적용됨",
    "C20235": "15~29세 3분기 실업률 주장에 전 연령 월별 실업률과 2024년 9월/8월이 연결됨",
    "C20290": "가공식품의 물가 기여도 0.30%p 주장에 소비자물가 총지수 변동폭이 연결됨. 가공식품 기여도 자료로 재매핑 필요",
}


UNVERIFIABLE = {
    "C01303": "관세청의 1월 1~10일 국가별 수출 증감 주장으로, 현재 연결된 KOSIS 연간 국가별 수출표의 범위와 주기가 다름",
    "C04595": "미국 10년물 국채금리 변동으로 국내 KOSIS 소비자물가 통계의 직접 검증 대상이 아님",
    "C05531": "미국 미시간대 장기 기대인플레이션으로 국내 KOSIS 소비자물가 통계의 직접 검증 대상이 아님",
    "C09409": "미국 10년물 국채금리 수준으로 국내 KOSIS 수출 통계의 직접 검증 대상이 아님",
    "C10227": "미국 미시간대 장기 기대인플레이션으로 국내 KOSIS 소비자물가 통계의 직접 검증 대상이 아님",
    "C12852": "중국 소비자물가로 국내 KOSIS 소비자물가지수의 직접 검증 대상이 아님",
    "C14623": "향후 연간 합계출산율이 0.8명을 넘을 수 있다는 전망 문장으로 현재 실적값과 비교할 수 없음",
    "C18693": "세계산업지수 충격과 국내 물가의 관계를 추정한 모형 결과로 KOSIS 원자료 단일값으로 직접 검증할 수 없음",
    "C18694": "국제 원자재 가격 충격과 국내 물가의 관계를 추정한 모형 결과로 KOSIS 원자료 단일값으로 직접 검증할 수 없음",
    "C18696": "기준금리 충격과 물가의 관계를 추정한 모형 결과로 KOSIS 원자료 단일값으로 직접 검증할 수 없음",
}


CORRECTIONS = {
    "C15976": {
        "actual_value": "63.8",
        "actual_period": "202505",
        "actual_prev_value": "63.5",
        "actual_prev_period": "202405",
        "actual_change_point": "0.3",
        "actual_number": "0.3",
    },
    "C15980": {
        "prd_se": "M",
        "actual_value": "2.8",
        "actual_period": "202505",
        "actual_prev_value": "",
        "actual_prev_period": "",
        "actual_change_pct": "",
        "actual_change_point": "",
        "actual_number": "2.8",
    },
    "C16083": {
        "actual_value": "63.8",
        "actual_period": "202505",
        "actual_prev_value": "63.5",
        "actual_prev_period": "202405",
        "actual_change_point": "0.3",
        "actual_number": "0.3",
    },
}


MANUAL_FIELDS = [
    "manual_decision",
    "manual_final_status",
    "manual_mapping_reason",
    "manual_kosis_evidence",
    "manual_checked_at",
]

CORRECTION_FIELDS = sorted({field for values in CORRECTIONS.values() for field in values})


def read_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return list(reader), list(reader.fieldnames or [])


def write_rows(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def decision_for(claim_id):
    if claim_id in CONFIRMED:
        reason, evidence = CONFIRMED[claim_id]
        return "확정일치", "검증완료_수동확정일치", reason, evidence
    if claim_id in RECHECK:
        return "재매핑필요", "재검토필요_재매핑", RECHECK[claim_id], ""
    if claim_id in UNVERIFIABLE:
        return "직접검증불가", "판단불가_KOSIS직접검증불가", UNVERIFIABLE[claim_id], ""
    raise KeyError(f"수동 판정이 없는 claim_id: {claim_id}")


def apply_decision(row):
    updated = dict(row)
    claim_id = updated["claim_id"]
    decision, status, reason, evidence = decision_for(claim_id)
    updated.update(CORRECTIONS.get(claim_id, {}))
    updated.update({
        "manual_decision": decision,
        "manual_final_status": status,
        "manual_mapping_reason": reason,
        "manual_kosis_evidence": evidence,
        "manual_checked_at": "2026-07-14",
    })
    if decision == "확정일치":
        updated["verdict"] = "일치"
        if "final_status" in updated:
            updated["final_status"] = status
    return updated


def markdown_cell(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def write_report(rows, master_counts):
    counts = Counter(row["manual_decision"] for row in rows)
    lines = [
        "# KOSIS 일치 후보 33건 수동 확정 보고서",
        "",
        "## 결론",
        "",
        f"- 수동 확정 일치: {counts['확정일치']}건",
        f"- 표/항목/시점 재매핑 필요: {counts['재매핑필요']}건",
        f"- KOSIS 직접검증 불가: {counts['직접검증불가']}건",
        "- 수치만 우연히 맞은 해외지표·전망·모형결과는 확정 일치에서 제외했다.",
        "- 고용률 2건은 전월 비교를 전년동월 비교로, 실업률 1건은 연간 주기를 월간으로 교정해 확정했다.",
        "",
        "## 2,001건 전체 최신 상태",
        "",
        "| 상태 | 건수 |",
        "| --- | ---: |",
        *[f"| {markdown_cell(status)} | {count} |" for status, count in master_counts.most_common()],
        "",
        "## 33건 상세 판정",
        "",
        "| claim_id | 주장 원문 | 수동 판정 | 표/항목/단위/시점 확인 결과 | KOSIS 근거 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {claim_id} | {claim_text} | {decision} | {reason} | {evidence} |".format(
                claim_id=markdown_cell(row["claim_id"]),
                claim_text=markdown_cell(row["claim_text"]),
                decision=markdown_cell(row["manual_decision"]),
                reason=markdown_cell(row["manual_mapping_reason"]),
                evidence=markdown_cell(row["manual_kosis_evidence"]),
            )
        )
    REPORT_OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    rows, fields = read_rows(INPUT)
    expected = set(CONFIRMED) | set(RECHECK) | set(UNVERIFIABLE)
    actual = {row["claim_id"] for row in rows}
    if len(rows) != 33 or actual != expected:
        raise RuntimeError(
            f"33건 판정 집합 불일치: rows={len(rows)}, missing={sorted(actual - expected)}, extra={sorted(expected - actual)}"
        )

    reviewed = [apply_decision(row) for row in rows]
    added_fields = CORRECTION_FIELDS + MANUAL_FIELDS
    output_fields = fields + [field for field in added_fields if field not in fields]
    write_rows(REVIEWED_OUTPUT, reviewed, output_fields)
    write_rows(CONFIRMED_OUTPUT, [r for r in reviewed if r["manual_decision"] == "확정일치"], output_fields)
    write_rows(RECHECK_OUTPUT, [r for r in reviewed if r["manual_decision"] == "재매핑필요"], output_fields)
    write_rows(UNVERIFIABLE_OUTPUT, [r for r in reviewed if r["manual_decision"] == "직접검증불가"], output_fields)

    master_rows, master_fields = read_rows(MASTER_INPUT)
    reviewed_by_id = {row["claim_id"]: row for row in reviewed}
    master_output = []
    for row in master_rows:
        updated = dict(row)
        reviewed_row = reviewed_by_id.get(row.get("claim_id"))
        if reviewed_row:
            updated.update(CORRECTIONS.get(row["claim_id"], {}))
            updated.update({field: reviewed_row[field] for field in MANUAL_FIELDS})
            updated["audit_status"] = reviewed_row["manual_final_status"]
        else:
            updated.update({field: "" for field in MANUAL_FIELDS})
        master_output.append(updated)

    master_output_fields = master_fields + [field for field in MANUAL_FIELDS if field not in master_fields]
    write_rows(MASTER_OUTPUT, master_output, master_output_fields)
    master_counts = Counter(row.get("audit_status", "") for row in master_output)
    write_report(reviewed, master_counts)

    print(f"수동 검토 완료: {dict(Counter(row['manual_decision'] for row in reviewed))}")
    print(f"2,001건 최신 상태: {dict(master_counts)}")
    print(f"보고서: {REPORT_OUTPUT}")


if __name__ == "__main__":
    main()
