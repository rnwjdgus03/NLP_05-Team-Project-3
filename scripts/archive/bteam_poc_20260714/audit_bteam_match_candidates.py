"""Audit the 70 legacy automatic matches before treating them as verified."""

import argparse
from collections import Counter
import csv
from datetime import datetime
from pathlib import Path
import re


BASE = Path("outputs/bteam_review")
DEFAULT_INPUT = BASE / "final_verified_filled_2001_refined_v3.csv"
DEFAULT_OUTPUT = BASE / "final_verified_filled_2001_audited_v4.csv"
DEFAULT_AUDIT = BASE / "match_candidates_audit_70.csv"
DEFAULT_SUMMARY = BASE / "match_candidates_audit_summary.csv"
DEFAULT_RERUN_INPUT = Path("outputs/bteam_verification/bteam_kosis_match_candidates_rerun_input_70.csv")
DEFAULT_RERUN_VERIFIED = Path("outputs/bteam_verification/bteam_kosis_match_candidates_verified_exact.csv")

FORECAST_RE = re.compile(
    r"전망|예상|목표|가능성|계획|추정|예측|것으로\s*봤다|전망했다"
)
UNCONFIRMED_RE = re.compile(r"확인\s*필요|자동\s*후보|후보\s*선택|미확정")


def read_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return list(reader), list(reader.fieldnames or [])


def write_rows(path, rows, fieldnames):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_article_date(row):
    try:
        return datetime.strptime((row.get("date") or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def actual_period_is_future(row):
    article_date = parse_article_date(row)
    digits = re.sub(r"\D", "", row.get("actual_period") or "")
    if article_date is None or len(digits) < 4:
        return False

    year = int(digits[:4])
    prd_se = (row.get("prd_se") or "Y").upper()
    if prd_se == "Y" or len(digits) < 6:
        return year > article_date.year

    subperiod = int(digits[4:6])
    if prd_se == "Q" and 1 <= subperiod <= 4:
        month = subperiod * 3
    elif prd_se == "H" and 1 <= subperiod <= 2:
        month = subperiod * 6
    else:
        month = subperiod
    return (year, month) > (article_date.year, article_date.month)


def audit_legacy_match(row, rerun_row=None):
    text = row.get("claim_text") or ""
    note = row.get("reviewer_note") or ""
    future = actual_period_is_future(row)
    forecast = bool(FORECAST_RE.search(text))
    unconfirmed = bool(UNCONFIRMED_RE.search(note))

    if forecast:
        status = "판단불가_전망문장"
        reason = "전망·예상·목표 문장으로 현재 KOSIS 실적값 검증 대상이 아님"
    elif rerun_row and rerun_row.get("verdict") == "불일치":
        status = "재검토필요_정확시점불일치"
        reason = "정확한 목표 시점으로 재조회한 KOSIS 값과 주장 수치가 다름"
    elif rerun_row and rerun_row.get("verdict") == "판단불가":
        status = "판단불가_정확시점조회실패"
        reason = rerun_row.get("api_error") or "정확한 목표 시점의 KOSIS 값을 확보하지 못함"
    elif rerun_row and rerun_row.get("verdict") == "일치" and future:
        status = "수동확인필요_일치후보"
        reason = "기존 미래시점 선택을 정확한 과거 시점으로 교정해 수치가 일치했으나 매핑 수동 확정이 필요함"
    elif future and not rerun_row:
        status = "재검토필요_미래시점"
        reason = "기사 게재일보다 뒤의 KOSIS 시점을 사용한 자동 일치"
    else:
        status = "수동확인필요_일치후보"
        reason = "수치 오차는 허용범위 이내지만 표·항목·단위·의미 매핑 확정이 필요함"

    return {
        "audit_future_period": "Y" if future else "N",
        "audit_forecast_or_target": "Y" if forecast else "N",
        "audit_mapping_unconfirmed": "Y" if unconfirmed else "N",
        "rerun_actual_period": (rerun_row or {}).get("actual_period", ""),
        "rerun_actual_value": (rerun_row or {}).get("actual_value", ""),
        "rerun_verdict": (rerun_row or {}).get("verdict", ""),
        "rerun_api_error": (rerun_row or {}).get("api_error", ""),
        "audit_reason": reason,
        "audit_status": status,
    }


def main(input_path, output_path, audit_path, summary_path, rerun_input_path, rerun_verified_path):
    rows, fieldnames = read_rows(input_path)
    rerun_rows = {}
    if Path(rerun_verified_path).exists():
        verified, _ = read_rows(rerun_verified_path)
        rerun_rows = {row.get("claim_id"): row for row in verified}
    legacy_matches = []
    out_rows = []

    for row in rows:
        new_row = dict(row)
        if row.get("refined_final_status") == "검증완료_일치":
            audit = audit_legacy_match(row, rerun_rows.get(row.get("claim_id")))
            new_row.update(audit)
            legacy_matches.append(new_row)
        else:
            new_row.update({
                "audit_future_period": "N",
                "audit_forecast_or_target": "N",
                "audit_mapping_unconfirmed": "N",
                "rerun_actual_period": "",
                "rerun_actual_value": "",
                "rerun_verdict": "",
                "rerun_api_error": "",
                "audit_reason": "기존 재검토/판단불가 상태 유지",
                "audit_status": row.get("refined_final_status") or "판단불가_상태없음",
            })
        out_rows.append(new_row)

    if len(rows) != 2001:
        raise RuntimeError(f"예상한 2,001건이 아님: {len(rows)}")
    if not legacy_matches:
        raise RuntimeError("감사할 기존 자동 일치 건이 없음")

    audit_fields = [
        "audit_future_period", "audit_forecast_or_target",
        "audit_mapping_unconfirmed", "rerun_actual_period", "rerun_actual_value",
        "rerun_verdict", "rerun_api_error", "audit_reason", "audit_status",
    ]
    output_fields = fieldnames + [field for field in audit_fields if field not in fieldnames]
    write_rows(output_path, out_rows, output_fields)
    write_rows(rerun_input_path, legacy_matches, output_fields)

    compact_fields = [
        "claim_id", "date", "claim_text", "metric", "org_id", "tbl_id",
        "obj_l1", "itm_id", "prd_se", "actual_period", "actual_prev_period",
        "refined_claim_number", "refined_actual_number", "refined_diff",
        "reviewer_note", *audit_fields,
    ]
    write_rows(
        audit_path,
        [{field: row.get(field, "") for field in compact_fields} for row in legacy_matches],
        compact_fields,
    )

    counts = Counter(row["audit_status"] for row in legacy_matches)
    summary_rows = [
        {"구분": "기존 자동 일치", "항목": "전체", "건수": len(legacy_matches)},
        *({"구분": "재분류", "항목": key, "건수": value} for key, value in counts.most_common()),
        {"구분": "품질 플래그", "항목": "매핑 미확정 메모", "건수": sum(row["audit_mapping_unconfirmed"] == "Y" for row in legacy_matches)},
    ]
    write_rows(summary_path, summary_rows, ["구분", "항목", "건수"])

    print(f"완료 -> {output_path}")
    print(f"기존 자동 일치: {len(legacy_matches)}건")
    print(f"정확 시점 재실행 결과 연결: {len(rerun_rows)}건")
    print(f"재분류: {dict(counts)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--audit-output", default=str(DEFAULT_AUDIT))
    parser.add_argument("--summary-output", default=str(DEFAULT_SUMMARY))
    parser.add_argument("--rerun-input", default=str(DEFAULT_RERUN_INPUT))
    parser.add_argument("--rerun-verified", default=str(DEFAULT_RERUN_VERIFIED))
    args = parser.parse_args()
    main(
        args.input, args.output, args.audit_output, args.summary_output,
        args.rerun_input, args.rerun_verified,
    )
