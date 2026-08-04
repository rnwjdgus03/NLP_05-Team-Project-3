#!/usr/bin/env python3
"""EMPTY_RESPONSE 를 '데이터가 아직 없다' 와 '좌표가 틀렸다' 로 가른다.

배경: 잠근 125건에서 확정 못 한 112건 중 EMPTY_RESPONSE 가 55건(49%)으로 가장 크다.
      좌표는 KOSIS 에 실재하는데 요청한 기간에 값이 없어 빈 응답이 온 경우다.

원인이 둘로 갈리고 처방이 완전히 다르다.

  (a) 기사 시점에 그 통계가 아직 안 나왔다
      → 버그가 아니다. '아직 발표 안 됨' 이라는 **판정 카테고리**가 필요하다.
        팩트체커 관점에서 이건 정직한 답이지 실패가 아니다.
  (b) 시차가 충분한데도 값이 없다
      → 좌표나 주기 선택이 틀렸다. 고칠 대상이다.

**발표 시차는 가정이다.** KOSIS 통계마다 실제 공표 일정이 다르므로,
아래 임계값은 '대략 이 정도면 아직 안 나왔을 것' 이라는 보수적 추정일 뿐이다.
확정하려면 통계별 공표주기 메타를 봐야 한다. 여기서는 규모만 가늠한다.

사용법:
  python diagnose_empty_response.py \
    --validated ..._chroma_validated.csv \
    --evaluation-set evaluation_set_v2.csv \
    --output empty_response_diagnosis.csv
"""
from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from datetime import date
from pathlib import Path

from kosis_meta_coordinates import read_csv_rows

# 주기별 '이 정도 지나야 나왔을 것' (개월). 보수적 추정치이며 사실이 아니다.
PUBLICATION_LAG_MONTHS = {"Y": 12, "H": 8, "Q": 4, "M": 2, "D": 1}
DEFAULT_LAG_MONTHS = 6

FUTURE = "FUTURE_PERIOD"
UNPUBLISHED = "LIKELY_UNPUBLISHED"
SHOULD_EXIST = "SHOULD_EXIST"
UNKNOWN = "UNPARSEABLE"


def text(value) -> str:
    value = str(value or "").strip()
    return "" if value.lower() in {"nan", "none"} else value


def parse_article_date(value) -> date | None:
    match = re.match(r"(\d{4})[-/.]?(\d{2})[-/.]?(\d{2})", text(value))
    if not match:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def period_end(period: str, prd_se: str) -> date | None:
    """기간 문자열이 가리키는 구간의 **마지막 날**.

    통계는 구간이 끝나야 집계되므로, 시차는 구간 끝을 기준으로 재야 한다.
    """
    period = text(period)
    prd_se = text(prd_se).upper() or "Y"
    if not period.isdigit():
        match = re.match(r"(\d{4})\s*[Qq]\s*([1-4])", period)
        if not match:
            return None
        year, quarter = int(match.group(1)), int(match.group(2))
        return _month_end(year, quarter * 3)
    if len(period) == 4:
        return date(int(period), 12, 31)
    if len(period) == 6:
        year, tail = int(period[:4]), int(period[4:])
        if prd_se == "Q" and 1 <= tail <= 4:
            return _month_end(year, tail * 3)
        if prd_se == "H" and 1 <= tail <= 2:
            return _month_end(year, tail * 6)
        if 1 <= tail <= 12:
            return _month_end(year, tail)
        return None
    if len(period) == 8:
        try:
            return date(int(period[:4]), int(period[4:6]), int(period[6:]))
        except ValueError:
            return None
    if len(period) == 5 and prd_se == "Q":
        year, quarter = int(period[:4]), int(period[4])
        return _month_end(year, quarter * 3) if 1 <= quarter <= 4 else None
    return None


def _month_end(year: int, month: int) -> date:
    if month >= 12:
        return date(year, 12, 31)
    return date.fromordinal(date(year, month + 1, 1).toordinal() - 1)


def months_between(later: date, earlier: date) -> float:
    return (later.year - earlier.year) * 12 + (later.month - earlier.month) + \
        (later.day - earlier.day) / 30.0


def classify(article: date | None, ends: date | None, prd_se: str) -> tuple[str, str]:
    if article is None or ends is None:
        return UNKNOWN, "기사일 또는 기간을 해석할 수 없음"
    if ends > article:
        return FUTURE, f"기간이 기사일({article})보다 미래({ends})"
    lag = months_between(article, ends)
    need = PUBLICATION_LAG_MONTHS.get(text(prd_se).upper(), DEFAULT_LAG_MONTHS)
    if lag < need:
        return UNPUBLISHED, f"구간 종료 후 {lag:.1f}개월 — 통상 공표 시차({need}개월) 미만"
    return SHOULD_EXIST, f"구간 종료 후 {lag:.1f}개월 — 나왔어야 함"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--validated", required=True)
    ap.add_argument("--evaluation-set", required=True)
    ap.add_argument("--reason", default="EMPTY_RESPONSE")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    keys = {text(r.get("claim_measurement_id")): r
            for r in read_csv_rows(args.evaluation_set)}

    seen: dict[str, dict] = {}
    for row in read_csv_rows(args.validated):
        mid = text(row.get("claim_measurement_id"))
        if mid not in keys or args.reason not in text(row.get("mapping_reason")):
            continue
        seen.setdefault(mid, row)

    causes: Counter = Counter()
    detail: list[dict] = []
    for mid, row in seen.items():
        claim = keys[mid]
        prd_se = text(row.get("prd_se")) or text(claim.get("prd_se")) \
            or text(claim.get("measurement_prd_se"))
        period = text(row.get("period")) or text(claim.get("period"))
        article = parse_article_date(claim.get("date") or row.get("date"))
        ends = period_end(period, prd_se)
        cause, why = classify(article, ends, prd_se)
        causes[cause] += 1
        detail.append({
            "claim_measurement_id": mid, "cause": cause, "why": why,
            "article_date": article.isoformat() if article else "",
            "prd_se": prd_se, "period": period,
            "period_end": ends.isoformat() if ends else "",
            "tbl_id": text(row.get("tbl_id")),
            "tbl_name": text(row.get("tbl_name"))[:50],
            "claim_text": text(claim.get("claim_text"))[:100],
        })

    total = sum(causes.values())
    print(f"=== {args.reason} {total}건 ===\n")
    labels = {
        FUTURE: "기간이 기사일보다 미래 (데이터 존재 불가)",
        UNPUBLISHED: "공표 시차 미달 (아직 발표 전으로 추정)",
        SHOULD_EXIST: "나왔어야 하는데 없음 (좌표·주기 문제)",
        UNKNOWN: "기간 해석 불가",
    }
    for cause, n in causes.most_common():
        print(f"  {labels.get(cause, cause):<40} {n:>4}  ({n/total:.0%})" if total else "")

    fixable = causes[SHOULD_EXIST] + causes[UNKNOWN]
    not_our_bug = causes[FUTURE] + causes[UNPUBLISHED]
    print("\n판단:")
    if not_our_bug > fixable:
        print(f"  발표 전/미래 {not_our_bug}건 > 좌표 문제 {fixable}건")
        print("  → 고칠 버그가 아니다. '아직 발표 안 됨' 판정 카테고리를 만들 것")
        print("     (매핑 실패로 세면 커버리지를 과소평가하고, 원인도 오해하게 된다)")
    else:
        print(f"  좌표 문제 {fixable}건 >= 발표 전/미래 {not_our_bug}건")
        print("  → 좌표·주기 선택을 봐야 한다")
    print("\n※ 공표 시차는 가정이다. 통계별 실제 공표 일정은 다르다.")
    print("   규모를 가늠하는 용도이지, 건별 확정 근거로 쓰지 말 것.")

    if detail:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(detail[0].keys()))
            writer.writeheader()
            writer.writerows(detail)
        print(f"\n저장: {args.output}")

        print("\n--- 나왔어야 하는데 없는 건 (좌표를 의심할 대상) ---")
        for row in [d for d in detail if d["cause"] == SHOULD_EXIST][:12]:
            print(f"  {row['prd_se']} {row['period']} | {row['tbl_name']}")
            print(f"    {row['claim_text'][:80]}")


if __name__ == "__main__":
    main()
