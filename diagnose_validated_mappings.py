#!/usr/bin/env python3
"""validated_mappings 후보행(885)을 claim_measurement_id 단위(177)로 축약한 진단 CSV 생성.

notebooks/jinsung_contextual_second_ready_verdict_colab.ipynb 의 진단 셀 로직을
로컬 실행 가능한 스크립트로 재사용·보강했다:
- candidate_rank 비수치 가드 (노트북은 int() crash 가능)
- 사유를 mapping_reason 뿐 아니라 status_reason 까지 함께 판독
- task 6: 후보 전체를 훑어 안전 회수 가능성(recovery_class)을 별도 분류
  (READY 조건 완화가 아니라 "왜 막혔는지 + 어떤 수선으로 살릴 수 있는지" 구분)

사용법:
  python diagnose_validated_mappings.py \
    --validated <..._kosis_validated_mappings.csv> \
    --output <diagnosis_measurement_level.csv>
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

STATUS_PRIORITY = {
    "READY": 0,
    "NEEDS_CONFIRMATION": 1,
    "MAPPING_FAILED": 2,
    "API_ERROR": 3,
    "NOT_EVALUATED": 4,
}

RANKING_REASONS = (
    "upstream table candidate is not decisive rank-1 READY",
    "top candidates have small margin",
    "lower-ranked technical alternative",
    "multiple table/ITEM/OBJ mappings are technically valid",
    "LOW_PRIORITY_CANDIDATE",
)
ITEM_OBJ_REASONS = ("EMPTY_RESPONSE", "INVALID_COMBINATION", "RESPONSE_CODE_MISMATCH",
                    "ITEM_UNRESOLVED", "OBJ_UNRESOLVED", "INVALID_REQUEST")


def _rank(row) -> int:
    try:
        return int(float(str(row.get("candidate_rank") or "")))
    except (TypeError, ValueError):
        return 999


def _truthy(value) -> bool:
    return str(value).strip().lower() in {"true", "1", "y", "yes"}


def _reason(row) -> str:
    return str(row.get("mapping_reason") or row.get("status_reason") or "").strip()


def next_action(status: str, reason: str) -> str:
    if status == "READY":
        return "VERIFY_ACTUAL_VALUE"
    if any(reason.startswith(r) or r in reason for r in RANKING_REASONS):
        return "REVIEW_TABLE_RANKING"
    if "UNIT_MISMATCH" in reason:
        return "REVIEW_UNIT_OR_TABLE"
    if any(r in reason for r in ITEM_OBJ_REASONS):
        return "REVIEW_ITEM_OBJ_PERIOD"
    if "PERIOD_MISSING" in reason:
        return "ENRICH_PERIOD"
    return "MANUAL_REVIEW"


def meta_valid(row) -> bool:
    """좌표(ITEM/OBJ) 코드가 공식 메타에 존재하는가.

    validate 출력에 metadata_valid 통합 컬럼이 없을 수 있어 item/obj 개별 컬럼도 함께 본다.
    """
    if "metadata_valid" in row and str(row.get("metadata_valid")).strip() != "":
        return _truthy(row.get("metadata_valid"))
    return _truthy(row.get("item_meta_valid")) and _truthy(row.get("obj_meta_valid"))


def technically_sound(row) -> bool:
    """API 응답·코드·단위·기간이 모두 유효한 후보인가 (의미 점수와 무관한 기술 유효성)."""
    return (meta_valid(row) and _truthy(row.get("response_code_valid"))
            and _truthy(row.get("unit_valid")) and _truthy(row.get("period_valid")))


def recovery_class(candidates) -> str:
    """task 6: READY 완화 없이 안전하게 회수 가능한 유형 분류 (우선순위 순)."""
    sound = [c for c in candidates if technically_sound(c)]
    # 1) 기술적으로 완전 유효한데 순위 근거만 부족 → 재순위 확인만으로 회수 가능
    for c in sound:
        r = _reason(c)
        if c.get("mapping_status") == "NEEDS_CONFIRMATION" and any(x in r for x in RANKING_REASONS):
            if _rank(c) == 1:
                return "TOP1_GATE_ONLY"      # rank-1 확정 조건만 실패
            return "RANK_ONLY"                # 순위만 애매
    # 2) 좌표(메타)는 유효한데 응답이 비거나 코드 불일치 → ITEM/OBJ 조합 수정으로 회수 가능성
    evaluated = [c for c in candidates
                 if c.get("mapping_status") not in ("NOT_EVALUATED", None, "")]
    if evaluated and all(any(x in _reason(c) for x in ("EMPTY_RESPONSE", "RESPONSE_CODE_MISMATCH"))
                         for c in evaluated):
        # 평가된 후보가 전부 빈 응답/코드 불일치 → 조합·기간 파라미터 수정 여지
        # (미평가 저순위 후보가 남아 있으면 폴백으로도 회수 가능)
        return "ITEM_OBJ_FIXABLE"
    # 3) 단위만 실패 (좌표·응답·기간은 유효)
    #    - KOSIS 쪽 단위가 아예 없으면 '미상'이라 정규화로 못 고친다(메타 보강 필요).
    #    - 양쪽 단위가 있는데 안 맞으면 별칭·배율 정규화로 회수 가능.
    for c in candidates:
        if (meta_valid(c) and _truthy(c.get("response_code_valid"))
                and _truthy(c.get("period_valid")) and not _truthy(c.get("unit_valid"))):
            if _truthy(c.get("unit_unknown")) or "UNIT_UNKNOWN" in _reason(c):
                return "UNIT_UNKNOWN_META"
            return "UNIT_FIX_ONLY"
    # 4) 기간만 실패 → 기간 보강으로 회수
    for c in candidates:
        if (meta_valid(c) and _truthy(c.get("response_code_valid"))
                and not _truthy(c.get("period_valid"))):
            return "PERIOD_FIX_ONLY"
    # 5) 아직 평가되지 않은 저순위 후보가 남아 있다 → 폴백 평가로 회수 시도 가능
    if any(c.get("mapping_status") == "NOT_EVALUATED" for c in candidates):
        return "FALLBACK_UNTRIED"
    return ""


def diagnose(validated_rows):
    grouped: dict[str, list] = defaultdict(list)
    for row in validated_rows:
        key = str(row.get("claim_measurement_id") or row.get("claim_id") or "").strip()
        if key:
            grouped[key].append(row)

    out = []
    for key, candidates in grouped.items():
        best = min(candidates,
                   key=lambda r: (STATUS_PRIORITY.get(str(r.get("mapping_status") or ""), 9), _rank(r)))
        status = str(best.get("mapping_status") or "")
        reason = _reason(best)
        out.append({
            "claim_measurement_id": key,
            "claim_id": best.get("claim_id", ""),
            "claim_text": best.get("claim_text", ""),
            "indicator": best.get("indicator", "") or best.get("measurement_indicator", ""),
            "value": best.get("value", ""),
            "unit": best.get("unit", ""),
            "period": best.get("period", "") or best.get("measurement_period", ""),
            "best_tbl_id": best.get("tbl_id", ""),
            "best_tbl_name": best.get("tbl_name", ""),
            "best_candidate_rank": best.get("candidate_rank", ""),
            "measurement_mapping_status": status,
            "measurement_mapping_reason": reason,
            "next_action": next_action(status, reason),
            "recovery_class": recovery_class(candidates),
            "candidate_count": len(candidates),
        })
    return sorted(out, key=lambda r: r["claim_measurement_id"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--validated", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    with open(args.validated, encoding="utf-8-sig", newline="") as f:
        validated = list(csv.DictReader(f))
    rows = diagnose(validated)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"candidates={len(validated)} → measurements={len(rows)} → {args.output}")
    print("mapping_status:", dict(Counter(r["measurement_mapping_status"] for r in rows).most_common()))
    print("next_action:", dict(Counter(r["next_action"] for r in rows).most_common()))
    print("recovery_class:", dict(Counter(r["recovery_class"] or "(none)" for r in rows).most_common()))


if __name__ == "__main__":
    main()
