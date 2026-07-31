#!/usr/bin/env python3
"""기존 validated_mappings에 '하류 실측 신뢰' 규칙을 재적용해 READY를 안전 회수한다 (API 0회).

배경: kosis_validate_mapping_candidates 는 상류(kosis_match)의 표 후보가
candidate_status=READY 인 rank-1 이 아니면 READY 를 NEEDS_CONFIRMATION 으로 강등한다.
그런데 validate 는 그 뒤에 공식 메타 코드·실제 API 응답·단위·기간을 직접 확인한다.
실측이 전부 통과한 rank-1 이라면 상류의 보수적 REVIEW 는 이미 해소된 것이다.

회수 조건(모두 필요 — 기준 완화가 아니라 중복 게이트 제거):
  1) mapping_status == NEEDS_CONFIRMATION 이고 사유가 'not decisive rank-1'
  2) candidate_rank == 1
  3) 상류 candidate_status != REJECT   (의미 실패는 존중)
  4) item/obj 메타 유효 + response_code_valid + unit_valid + period_valid 전부 True
  5) 상류 1·2위 점수차 >= max(5, 1%)   (동점 표는 사람 확인 유지)

사용법:
  python recover_downstream_validated.py \
    --validated <..._validated_mappings.csv> \
    --output <..._validated_recovered.csv>
"""
from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from pathlib import Path

TRIGGER_REASON = "upstream table candidate is not decisive rank-1 READY"
RECOVERED_REASON = "downstream metadata/API/unit/period validation passed for rank-1 candidate"


def _truthy(value) -> bool:
    return str(value).strip().lower() in {"true", "1", "y", "yes"}


def _meta_ok(row) -> bool:
    if str(row.get("metadata_valid", "")).strip():
        return _truthy(row.get("metadata_valid"))
    return _truthy(row.get("item_meta_valid")) and _truthy(row.get("obj_meta_valid"))


def _margin_ok(row) -> bool:
    try:
        score = float(str(row.get("candidate_score", "")))
        runner_up = float(str(row.get("candidate_runner_up_score", "")))
    except (TypeError, ValueError):
        return True
    return (score - runner_up) >= max(5.0, score * 0.01)


def _norm(value) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", str(value or "")).lower()


def item_semantics_ok(row) -> bool:
    """claim이 특정 품목·대상을 말하는데 선택된 OBJ가 그것과 무관하면 회수하지 않는다.

    실측 사례: '농수산식품 수출' → OBJ '건조기(농산물용의 것)',
              '반도체 수출' → OBJ '인산에스테르 및 그 염...' 처럼
    API 응답은 정상이지만 의미가 전혀 다른 좌표가 선택될 수 있다.
    기술 유효성(response_code_valid)만으로는 이를 막지 못하므로 별도 가드를 둔다.
    """
    item = _norm(row.get("industry_or_item") or row.get("measurement_item"))
    if not item or item in {"-", "전체", "총계", "합계"}:
        return True  # 품목 제약이 없는 claim은 총계 좌표가 정상
    selected = " ".join(str(row.get(key, "")) for key in (
        "kosis_obj_l1_name", "selected_obj_l1_name", "selected_obj_l2_name",
        "selected_obj_l3_name", "selected_itm_name", "tbl_name",
    ))
    selected_norm = _norm(selected)
    if not selected_norm:
        return True
    if item in selected_norm or selected_norm in item:
        return True
    # 부분 일치(2글자 이상 토큰 공유)도 허용 — '석유화학' vs '석유화학제품'
    return any(len(token) >= 2 and token in selected_norm
               for token in re.findall(r"[가-힣A-Za-z]{2,}", str(
                   row.get("industry_or_item") or row.get("measurement_item") or "")))


def can_recover(row) -> bool:
    if str(row.get("mapping_status", "")) != "NEEDS_CONFIRMATION":
        return False
    if TRIGGER_REASON not in str(row.get("mapping_reason", "")):
        return False
    if str(row.get("candidate_rank", "")).strip() != "1":
        return False
    if str(row.get("candidate_status", "")).strip().upper() == "REJECT":
        return False
    if not (_meta_ok(row) and _truthy(row.get("response_code_valid"))
            and _truthy(row.get("unit_valid")) and _truthy(row.get("period_valid"))):
        return False
    if not item_semantics_ok(row):
        return False
    return _margin_ok(row)


def recover(rows):
    out, n = [], 0
    for source in rows:
        row = dict(source)
        if can_recover(row):
            row["mapping_status"] = "READY"
            row["mapping_reason"] = RECOVERED_REASON
            row["recovered_by"] = "downstream_validation"
            n += 1
        out.append(row)
    return out, n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--validated", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    with open(args.validated, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    before = Counter(r.get("mapping_status") for r in rows)
    out, n = recover(rows)
    after = Counter(r.get("mapping_status") for r in out)

    fields = list(dict.fromkeys([k for r in out for k in r]))
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(out)

    print(f"recovered_rows={n} → {args.output}")
    print("before:", dict(before.most_common()))
    print("after :", dict(after.most_common()))


if __name__ == "__main__":
    main()
