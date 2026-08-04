#!/usr/bin/env python3
"""커버리지를 정직하게 센다 — '확정 못 함'을 '실패'와 '확인 불가'로 가른다.

지금은 "103건 중 12건 확정(11.7%)"으로 보고된다. 이 숫자는 두 가지를 섞고 있다.

  · 시스템이 못 한 것          — 좌표를 못 찾음, 단위를 확인 못 함
  · 애초에 확인할 수 없는 것    — 기사 시점에 미발표, KOSIS 에 통계 없음

팩트체커에게 "확인할 수 없다"는 실패가 아니라 **결론**이다.
둘을 섞으면 시스템이 실제보다 못해 보이고, 어디를 고쳐야 하는지도 흐려진다.

**분모를 몰래 줄이지 않는다.** 전체 기준과 확인 가능한 것 기준을 **둘 다** 낸다.
하나만 내면 유리한 쪽을 고른 것처럼 보이고, 실제로 그렇게 되기 쉽다.

사용법:
  python report_coverage.py \
    --validated ..._chroma_validated.csv \
    --evaluation-set evaluation_set_v3.csv \
    --output coverage_report.csv
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

from diagnose_empty_response import FUTURE, classify, parse_article_date, period_end
from kosis_meta_coordinates import read_csv_rows

STATUS_ORDER = ["READY", "PROVISIONAL", "NEEDS_CONFIRMATION", "MAPPING_FAILED", "API_ERROR"]

CONFIRMED = "확정"
UNVERIFIABLE = "확인 불가"
SYSTEM_GAP = "시스템 한계"

# (버킷, 설명). 순서가 보고서 출력 순서다.
BUCKETS = {
    "CONFIRMED": (CONFIRMED, "READY 또는 PROVISIONAL"),
    "PERIOD_AFTER_ARTICLE": (UNVERIFIABLE, "요청 기간이 기사일 이후 — 그 시점에 존재할 수 없음"),
    "NO_DATA_AT_COORDINATE": (UNVERIFIABLE, "좌표는 유효한데 그 기간에 값이 없음"),
    "PERIOD_MISSING": (UNVERIFIABLE, "기간을 특정할 수 없음"),
    "COORDINATE_RETURNS_NOTHING": (SYSTEM_GAP, "어느 기간에도 값이 없음 — 좌표가 틀림"),
    "CLAIM_ITEM_UNGROUNDED": (SYSTEM_GAP, "주장 대상이 그 문장에 없음 — 상류 추출 오류"),
    "CLAIM_ITEM_MISMATCH": (SYSTEM_GAP, "주장 대상과 좌표가 어긋남"),
    "UNIT_UNVERIFIABLE": (SYSTEM_GAP, "단위 정합을 확인하지 못함"),
    "CANDIDATE_NOT_DECISIVE": (SYSTEM_GAP, "후보가 결정적이지 않음"),
    "COORDINATE_NOT_FOUND": (SYSTEM_GAP, "유효한 좌표 조합을 못 찾음"),
    "API_ERROR": (SYSTEM_GAP, "KOSIS 조회 실패"),
    "OTHER": (SYSTEM_GAP, "분류되지 않음"),
}


def text(value) -> str:
    value = str(value or "").strip()
    return "" if value.lower() in {"nan", "none"} else value


def best_row(rows):
    rank = {status: index for index, status in enumerate(STATUS_ORDER)}
    return min(rows, key=lambda r: rank.get(text(r.get("mapping_status")), 9))


def bucket_of(row, claim) -> str:
    """왜 확정되지 않았는가. **사실만 쓰고 원인을 추정하지 않는다.**

    'LIKELY_UNPUBLISHED'(공표 시차 추정)는 일부러 버킷으로 쓰지 않는다.
    실측에서 그렇게 분류된 55건 중 11건이 실제로는 READY 였다 — 20% 이상 오탐이다.
    반면 '기간이 기사일 이후'는 READY 가 0건이라 사실로 다뤄도 된다.
    """
    status = text(row.get("mapping_status"))
    if status in {"READY", "PROVISIONAL"}:
        return "CONFIRMED"
    if status == "API_ERROR":
        return "API_ERROR"

    reason = text(row.get("mapping_reason"))
    # 2026-08-02 추가. 이 둘은 '틀린 답을 막은' 사유라 실패와 성격이 다르다 —
    # 확정을 잃는 대신 거짓 불일치를 없앤 것이다.
    if "UNGROUNDED_CLAIM_ITEM" in reason:
        return "CLAIM_ITEM_UNGROUNDED"
    if "CLAIM_ITEM_MISMATCH" in reason:
        return "CLAIM_ITEM_MISMATCH"
    if "PERIOD_MISSING" in reason:
        return "PERIOD_MISSING"
    if "UNIT_MISMATCH" in reason:
        return "UNIT_UNVERIFIABLE"
    if "not decisive" in reason:
        return "CANDIDATE_NOT_DECISIVE"
    if "EMPTY_RESPONSE" in reason:
        prd_se = text(row.get("prd_se")) or text(claim.get("prd_se"))
        period = text(row.get("period")) or text(claim.get("period"))
        article = parse_article_date(claim.get("date") or row.get("date"))
        cause, _ = classify(article, period_end(period, prd_se), prd_se)
        return "PERIOD_AFTER_ARTICLE" if cause == FUTURE else "NO_DATA_AT_COORDINATE"
    if "INVALID_COMBINATION" in reason or status == "MAPPING_FAILED":
        return "COORDINATE_NOT_FOUND"
    return "OTHER"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--validated", required=True)
    ap.add_argument("--evaluation-set", required=True)
    ap.add_argument("--article-source", default="",
                    help="date 컬럼이 평가 집합에 없을 때 가져올 파일")
    ap.add_argument("--probe", default="",
                    help="probe_empty_coordinates.py 출력. 빈 응답 좌표를 "
                         "'좌표는 맞고 기간만 없음'과 '좌표가 틀림'으로 가른다. "
                         "없으면 전부 확인 불가로 세므로 커버리지가 부풀려진다.")
    ap.add_argument("--output", default="")
    args = ap.parse_args()

    # 재조회 결과: 어느 기간에도 값이 없으면 좌표가 틀린 것 → 시스템 한계
    coordinate_wrong: set[str] = set()
    if args.probe:
        for row in read_csv_rows(args.probe):
            try:
                found = int(float(text(row.get("values_found")) or "-1"))
            except ValueError:
                found = -1
            if found == 0:
                coordinate_wrong.add(text(row.get("claim_measurement_id")))

    claims = {text(r.get("claim_measurement_id")): dict(r)
              for r in read_csv_rows(args.evaluation_set)}
    if args.article_source:
        for row in read_csv_rows(args.article_source):
            mid = text(row.get("claim_measurement_id"))
            if mid in claims and not text(claims[mid].get("date")):
                claims[mid]["date"] = text(row.get("date"))

    grouped: dict[str, list] = {}
    for row in read_csv_rows(args.validated):
        mid = text(row.get("claim_measurement_id"))
        if mid in claims:
            grouped.setdefault(mid, []).append(row)

    counts: Counter = Counter()
    detail = []
    for mid, claim in claims.items():
        rows = grouped.get(mid)
        bucket = bucket_of(best_row(rows), claim) if rows else "COORDINATE_NOT_FOUND"
        if bucket == "NO_DATA_AT_COORDINATE" and mid in coordinate_wrong:
            bucket = "COORDINATE_RETURNS_NOTHING"
        counts[bucket] += 1
        detail.append({"claim_measurement_id": mid, "bucket": bucket,
                       "group": BUCKETS[bucket][0],
                       "claim_text": text(claim.get("claim_text"))[:100]})

    # 2026-08-02: 같은 입력으로 두 번 돌렸더니 API_ERROR 48행(measurement 8개) → 0 이었고
    # 확정이 11 → 12 로 바뀌었다. 재시도·백오프가 있는데도 한 실행에서 실패가 남는다.
    # 이 상태의 숫자를 기록하면 노이즈를 성능으로 착각한다.
    api_errors = {mid for mid, rows in grouped.items()
                  if any(text(r.get("mapping_status")) == "API_ERROR" for r in rows)}

    total = len(claims)
    by_group = Counter()
    for bucket, n in counts.items():
        by_group[BUCKETS[bucket][0]] += n

    print(f"=== 평가 집합 {total}건 ===\n")
    for bucket, (group, description) in BUCKETS.items():
        n = counts.get(bucket, 0)
        if n:
            print(f"  [{group:<6}] {description:<38} {n:>4}  ({n/total:.0%})")

    confirmed = by_group[CONFIRMED]
    unverifiable = by_group[UNVERIFIABLE]
    verifiable = total - unverifiable

    print(f"\n{'-' * 62}")
    print(f"  전체 기준 확정률          {confirmed}/{total} = {confirmed/total:.1%}")
    if verifiable:
        print(f"  확인 가능한 것 기준       {confirmed}/{verifiable} = {confirmed/verifiable:.1%}")
    print(f"{'-' * 62}")
    print("\n두 숫자를 함께 읽어야 한다.")
    print("  전체 기준  — 사용자가 기사를 넣었을 때 실제로 답을 받을 확률")
    print("  가능 기준  — 답할 수 있는 문제에서 시스템이 얼마나 하는가")
    print("어느 하나만 쓰면 유리한 쪽을 고른 것이 된다.")
    print(f"\n고칠 여지가 있는 것(시스템 한계): {by_group[SYSTEM_GAP]}건")
    if api_errors:
        print(f"\n[경고] KOSIS 조회에 실패한 measurement 가 {len(api_errors)}건 있다.")
        print("       이 숫자를 기록하지 말 것 — 같은 입력으로 다시 돌리면 달라진다.")
        print("       실측: API_ERROR 48행 -> 0, 확정 11 -> 12 (재시도·백오프가 있는데도 그렇다).")
        print("       validate 를 한 번 더 돌린 뒤 다시 집계할 것.")
    if not args.probe:
        print("\n[주의] --probe 를 주지 않았다. 빈 응답 좌표를 전부 '확인 불가'로 세고 있어")
        print("       확인 가능 기준 확정률이 부풀려진다. 실측에서 그런 24건 중")
        print("       절반(12건)은 좌표가 틀린 것이었다.")

    if args.output and detail:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(detail[0].keys()))
            writer.writeheader()
            writer.writerows(detail)
        print(f"\n저장: {args.output}")


if __name__ == "__main__":
    main()
