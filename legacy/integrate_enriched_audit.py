"""Merge the remote enriched 2,001 rows with the conservative local audit."""

from __future__ import annotations

import csv
from collections import Counter
from datetime import date
from pathlib import Path


REPO = Path(__file__).resolve().parent
BASE = REPO / "outputs/bteam_review"
REMOTE_INPUT = BASE / "final_verified_enriched.csv"
LOCAL_AUDIT = REPO / "outputs/bteam_gold/final_verified_filled_2001_codebook_v7.csv"

FINAL_OUTPUT = BASE / "final_verified_enriched_audited.csv"
VERIFIED_OUTPUT = BASE / "submission_integrated_verified_matches.csv"
RECHECK_OUTPUT = BASE / "submission_integrated_recheck_needed.csv"
UNVERIFIABLE_OUTPUT = BASE / "submission_integrated_unverifiable.csv"
AUTO_CANDIDATE_OUTPUT = BASE / "submission_enriched_auto_match_candidates_117.csv"
RECOVERED_OUTPUT = BASE / "submission_integrated_local_manual_recovered_4.csv"
SUMMARY_OUTPUT = BASE / "submission_integrated_summary.csv"
REPORT_OUTPUT = BASE / "submission_integrated_bteam_status_report.md"

REMOTE_MATCH_STATUS = "검증완료_일치"
MANUAL_MATCH = "확정일치"
MANUAL_UNVERIFIABLE = "직접검증불가"
CHECKED_AT = date.today().isoformat()


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def starts(value, prefix):
    return str(value or "").startswith(prefix)


def effective_mapping(remote, local):
    manual = local.get("manual_decision") == MANUAL_MATCH
    same_core = all(
        (remote.get(field) or "") == (local.get(field) or "")
        for field in ("org_id", "tbl_id", "obj_l1", "itm_id", "prd_se")
    )
    if manual:
        source = "로컬 수동확정 매핑"
        selected = local
        obj_l2 = local.get("obj_l2", "")
    else:
        source = "원격 enriched 매핑"
        selected = remote
        obj_l2 = local.get("obj_l2", "") if same_core else ""
        if obj_l2:
            source += " + 로컬 obj_l2"
    return {
        "integrated_org_id": selected.get("org_id", ""),
        "integrated_tbl_id": selected.get("tbl_id", ""),
        "integrated_obj_l1": selected.get("obj_l1", ""),
        "integrated_obj_l2": obj_l2,
        "integrated_itm_id": selected.get("itm_id", ""),
        "integrated_prd_se": selected.get("prd_se", ""),
        "integrated_mapping_source": source,
    }


def audit_row(remote, local):
    remote_auto_match = remote.get("refined_final_status") == REMOTE_MATCH_STATUS
    manual_decision = local.get("manual_decision", "")
    local_status = local.get("audit_status") or local.get("refined_final_status") or ""

    if manual_decision == MANUAL_MATCH:
        decision = "검증완료"
        final_status = local.get("manual_final_status") or "검증완료_수동확정일치"
        level = "수동확정"
        reason = local.get("manual_mapping_reason") or "로컬 수동 대조에서 표·항목·시점·값을 확정"
        evidence = local.get("manual_kosis_evidence", "")
    elif manual_decision == MANUAL_UNVERIFIABLE:
        decision = "판단불가"
        final_status = local.get("manual_final_status") or "판단불가_수동확정"
        level = "수동확정"
        reason = local.get("manual_mapping_reason") or "로컬 수동 대조에서 KOSIS 직접검증 불가로 확정"
        evidence = local.get("manual_kosis_evidence", "")
    elif remote_auto_match and starts(local_status, "판단불가"):
        decision = "판단불가"
        final_status = local_status
        level = "자동일치후보_재감사"
        reason = f"원격 자동 일치 후보이나 로컬 감사 상태가 {local_status}"
        evidence = local.get("expansion_evidence") or local.get("audit_reason") or local.get("api_error", "")
    elif remote_auto_match:
        decision = "재검토"
        final_status = "재검토필요_자동일치후보"
        level = "자동일치후보_재감사"
        reason = f"원격 수치 일치이나 수동 확정 근거 없음; 로컬 감사 상태={local_status or '미확정'}"
        evidence = local.get("expansion_evidence") or local.get("audit_reason") or local.get("reviewer_note", "")
    elif starts(remote.get("refined_final_status"), "판단불가"):
        decision = "판단불가"
        final_status = remote.get("refined_final_status", "판단불가")
        level = "원격 enriched 유지"
        reason = remote.get("refined_judge_note") or remote.get("api_error", "")
        evidence = ""
    else:
        decision = "재검토"
        final_status = remote.get("refined_final_status") or "재검토필요_미분류"
        level = "원격 enriched 유지"
        reason = remote.get("refined_judge_note") or remote.get("reviewer_note", "")
        evidence = ""

    out = dict(remote)
    out.update(effective_mapping(remote, local))
    out.update({
        "local_audit_status": local_status,
        "local_manual_decision": manual_decision,
        "local_manual_final_status": local.get("manual_final_status", ""),
        "local_expansion_decision": local.get("expansion_decision", ""),
        "local_expansion_verdict": local.get("expansion_verdict", ""),
        "local_expansion_final_status": local.get("expansion_final_status", ""),
        "remote_auto_match_candidate": "Y" if remote_auto_match else "N",
        "integrated_decision": decision,
        "integrated_final_status": final_status,
        "integrated_verification_level": level,
        "integrated_reason": reason,
        "integrated_kosis_evidence": evidence,
        "integrated_checked_at": CHECKED_AT,
    })
    return out


def compact(row):
    fields = [
        "claim_id", "article_id", "title", "date", "url", "claim_text", "metric",
        "target_number", "target_unit", "time_basis", "verifiable",
        "integrated_org_id", "integrated_tbl_id", "integrated_obj_l1", "integrated_obj_l2",
        "integrated_itm_id", "integrated_prd_se", "actual_period", "actual_prev_period",
        "refined_claim_type", "refined_claim_number", "refined_actual_number", "refined_verdict",
        "refined_final_status", "local_audit_status", "local_manual_decision",
        "remote_auto_match_candidate", "integrated_decision", "integrated_final_status",
        "integrated_verification_level", "integrated_mapping_source", "integrated_reason",
        "integrated_kosis_evidence", "reviewer_note", "integrated_checked_at",
    ]
    return {field: row.get(field, "") for field in fields}


def main():
    remote_rows = read_csv(REMOTE_INPUT)
    local_rows = read_csv(LOCAL_AUDIT)
    if len(remote_rows) != 2001 or len(local_rows) != 2001:
        raise RuntimeError(f"2,001건 기준 불일치: remote={len(remote_rows)}, local={len(local_rows)}")

    local_by_id = {row["claim_id"]: row for row in local_rows}
    remote_ids = {row["claim_id"] for row in remote_rows}
    if remote_ids != set(local_by_id):
        raise RuntimeError("원격 enriched와 로컬 audit의 claim_id 집합이 다름")

    audited = [audit_row(remote, local_by_id[remote["claim_id"]]) for remote in remote_rows]
    decision_counts = Counter(row["integrated_decision"] for row in audited)
    expected = {"검증완료": 21, "재검토": 1462, "판단불가": 518}
    if dict(decision_counts) != expected:
        raise RuntimeError(f"통합 결과 예상 불일치: actual={dict(decision_counts)}, expected={expected}")

    auto_candidates = [row for row in audited if row["remote_auto_match_candidate"] == "Y"]
    candidate_counts = Counter(row["integrated_decision"] for row in auto_candidates)
    expected_candidates = {"검증완료": 17, "재검토": 83, "판단불가": 17}
    if dict(candidate_counts) != expected_candidates:
        raise RuntimeError(
            f"117건 재감사 예상 불일치: actual={dict(candidate_counts)}, expected={expected_candidates}"
        )

    recovered = [
        row for row in audited
        if row["integrated_decision"] == "검증완료" and row["remote_auto_match_candidate"] == "N"
    ]
    if len(recovered) != 4:
        raise RuntimeError(f"원격 누락 수동확정은 4건이어야 함: {len(recovered)}")

    full_fields = list(audited[0].keys())
    compact_rows = [compact(row) for row in audited]
    compact_fields = list(compact_rows[0].keys())
    write_csv(FINAL_OUTPUT, audited, full_fields)
    write_csv(
        VERIFIED_OUTPUT,
        [row for row in compact_rows if row["integrated_decision"] == "검증완료"],
        compact_fields,
    )
    write_csv(
        RECHECK_OUTPUT,
        [row for row in compact_rows if row["integrated_decision"] == "재검토"],
        compact_fields,
    )
    write_csv(
        UNVERIFIABLE_OUTPUT,
        [row for row in compact_rows if row["integrated_decision"] == "판단불가"],
        compact_fields,
    )
    write_csv(AUTO_CANDIDATE_OUTPUT, [compact(row) for row in auto_candidates], compact_fields)
    write_csv(RECOVERED_OUTPUT, [compact(row) for row in recovered], compact_fields)

    summary = [
        {"section": "source", "label": "원격 enriched 전체", "count": 2001, "note": "새 기준 입력"},
        {"section": "remote_candidate_audit", "label": "원격 자동 일치 후보", "count": 117, "note": "확정 일치가 아님"},
        {"section": "remote_candidate_audit", "label": "수동 확정", "count": 17, "note": "로컬 수동 근거와 중복"},
        {"section": "remote_candidate_audit", "label": "재검토", "count": 83, "note": "수동 확정 근거 없음"},
        {"section": "remote_candidate_audit", "label": "판단불가", "count": 17, "note": "해외·정보부족·API/매핑 문제"},
        {"section": "manual_recovery", "label": "원격에서 빠진 로컬 수동 확정", "count": 4, "note": "근거 재확인 후 복원"},
        {"section": "integrated_final", "label": "검증완료", "count": 21, "note": "수동 확정만 포함"},
        {"section": "integrated_final", "label": "재검토", "count": 1462, "note": "자동 일치 후보 포함"},
        {"section": "integrated_final", "label": "판단불가", "count": 518, "note": "원격 491 + 로컬 수동/후보 감사 반영"},
    ]
    write_csv(SUMMARY_OUTPUT, summary, ["section", "label", "count", "note"])

    recovered_ids = ", ".join(row["claim_id"] for row in recovered)
    report = [
        "# B팀 KOSIS enriched 통합 감사 보고",
        "",
        "## 결론",
        "",
        "- 원격 `final_verified_enriched.csv` 2,001건을 새 기준 입력으로 채택했다.",
        "- 원격의 `검증완료_일치` 117건은 자동 수치 일치 후보로 낮추고 로컬 감사 근거와 다시 대조했다.",
        "- 재감사 결과는 수동 확정 17건, 재검토 83건, 판단불가 17건이다.",
        f"- 원격 후보에서 빠진 로컬 수동 확정 4건({recovered_ids})은 근거를 재확인해 복원했다.",
        "- 최종 제출용 검증완료는 수동 확정 21건만 포함한다.",
        "- 코드북 일치 28건은 독립 홀드아웃 80% 게이트 실패 때문에 확정하지 않고 재검토에 유지한다.",
        "",
        "## 통합 결과",
        "",
        "| 구분 | 건수 | 의미 |",
        "| --- | ---: | --- |",
        "| 검증완료 | 21 | 표·항목·단위·시점·KOSIS 값 수동 확정 |",
        "| 재검토 | 1,462 | 자동 일치 후보 및 표·항목·시점 추가 확인 대상 |",
        "| 판단불가 | 518 | KOSIS 미제공, 정보 부족, 해외 통계, API/파라미터 문제 |",
        "| 합계 | 2,001 | 원격 enriched claim_id 전체와 동일 |",
        "",
        "## 원격 자동 일치 후보 117건 재감사",
        "",
        "| 재감사 결과 | 건수 | 처리 |",
        "| --- | ---: | --- |",
        "| 수동 확정과 일치 | 17 | 최종 검증완료 |",
        "| 수동 근거 부족 | 83 | 재검토 |",
        "| 로컬 감사상 판단불가 | 17 | 판단불가 |",
        "",
        "## 원격에서 빠진 수동 확정 4건",
        "",
        "- `C00381`: 연간 CPI 2023→2024 상승률 2.321%, 주장 2.3%와 일치",
        "- `C02892`: 2021년 5월 15~29세 고용률 44.4%와 일치",
        "- `C15304`: 석유류 `obj_l2=B05`, 2024년 5월→2025년 5월 -2.325%, 주장 -2.3%와 일치",
        "- `C20235`: 15~29세 분기 경제활동인구·실업자 합산 계산으로 4.9%→5.1%, +0.2%p와 일치",
        "",
        "## 품질 기준",
        "",
        "- `outputs/bteam_gold/`의 개발용 골드 100건과 코드북 결과를 유지한다.",
        "- `outputs/bteam_holdout/`의 독립 홀드아웃 100건 최초 평가를 유지한다.",
        "- 독립 항목·시점 엄격 정확도는 18.2%로 80% 게이트를 통과하지 못했다.",
        "- 따라서 자동 일치 후보와 코드북 일치 후보는 새 독립 평가 통과 전까지 최종 확정하지 않는다.",
        "",
        "## 핵심 파일",
        "",
        "- `final_verified_enriched_audited.csv`: 원격 enriched + 로컬 감사 전체 2,001건",
        "- `submission_integrated_verified_matches.csv`: 수동 확정 21건",
        "- `submission_integrated_recheck_needed.csv`: 재검토 1,462건",
        "- `submission_integrated_unverifiable.csv`: 판단불가 518건",
        "- `submission_enriched_auto_match_candidates_117.csv`: 원격 117건 재감사 전체",
        "- `submission_integrated_local_manual_recovered_4.csv`: 원격 누락 수동 확정 4건",
        "",
        "## Archive",
        "",
        "- 초기 197건 PoC와 기존 표본 검증·제출 파일은 `outputs/archive/bteam_poc_20260714/`에 보존한다.",
    ]
    REPORT_OUTPUT.write_text("\n".join(report) + "\n", encoding="utf-8")

    print(f"원격 자동 일치 후보 재감사={dict(candidate_counts)}")
    print(f"통합 최종={dict(decision_counts)}")
    print(f"원격 누락 수동확정={recovered_ids}")
    print(FINAL_OUTPUT.resolve())


if __name__ == "__main__":
    main()

