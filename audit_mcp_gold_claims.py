#!/usr/bin/env python3
"""팀원이 KOSIS MCP 로 만든 골드셋(200건)을 검수한다 (2026-08-06).

## 왜 필요한가

`mcp_full_gold_200.csv` 는 REFUTES 172 / SUPPORTS 28 (86% 불일치) 다.
오늘 하루 잰 어떤 실측치보다 훨씬 높다 — 첫50건 불일치는 0이었다.

`human_reviewed` 가 **200건 전부 'N'** 이다. MCP 응답을 사람 검수 없이 그대로
골드로 확정했다. 그 MCP 자체가 출력에 "생성형 AI 답변에는 오류가 있을 수 있으니
원자료를 확인하라"는 경고를 다는데, 그 경고를 검증 없이 넘긴 것이다.

REFUTES 172건을 직접 뜯어보고 네 가지 패턴을 찾았다. 이 스크립트는 그 네 가지를
자동으로 걸러 **의심**과 **신뢰 가능**으로 가른다. 이걸로 골드를 확정하지 않는다 —
사람이 의심 건을 봐서 판단해야 비로소 골드가 된다.

## 무엇을 거르는가

**① 좁은 품목코드 오매핑.** `전체 수출액 6838억달러` 같은 총액 주장 17건이
`다이오드트랜지스터 기타 이와 유사한 반도체 디바이스` 라는 좁은 HS코드에 매핑됐다.
반도체를 언급하지 않은 문장까지 그랬다. 오늘 우리가 만든 `INDICATOR_TABLE_MISMATCH`
와 같은 원리로 잡는다 — 주장 문장과 항목명이 문자 2-그램을 하나도 안 겹치면 무관이다.

**② 허용오차 없는 근접 판정.** `18% → 실제 17.57%` 처럼 0.4~2%p 차이가 REFUTES 로
찍혔다. 기사가 반올림한 걸 다 틀렸다고 센 것이다. 증감률류는 %p 절대차, 수준값은
상대오차로 재서 좁은 간격 안이면 의심으로 뺀다.

**③ 순별(旬).** `1월 1일~10일 수출입현황`. 어제 정확히 이 유형으로
`SUB_MONTHLY_PERIOD_UNSUPPORTED` 게이트를 만들었다 — 같은 판정 함수를 그대로 쓴다.
KOSIS 는 순별 자료가 없어서 월간과 비교하면 원리적으로 못 맞는다.

**④ 가정법·전망.** `1월 수출이 감소할 경우...` 는 사실 주장이 아니라 가설이다.
검증 대상이 아닌데 확정 판정을 받았다.

## 자동으로 반대로 뒤집지 않는다

**의심 = 사람이 볼 대상이지, 오답이 확정된 것이 아니다.** ①은 실제로 반도체
얘기일 수도 있고(그러면 정당), ②는 허용오차를 얼마로 잡느냐에 따라 갈린다.
이 스크립트가 하는 일은 **어디를 먼저 볼지 좁히는 것**까지다.

## 쓰는 법

    python audit_mcp_gold_claims.py --input mcp_full_gold_200.csv \\
      --suspect-output mcp_gold_suspect.csv \\
      --trustworthy-output mcp_gold_trustworthy.csv
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from kosis_claim_shape import sub_monthly_claim  # noqa: E402
from kosis_indicator_table_match import bigrams  # noqa: E402
from kosis_meta_coordinates import AGGREGATE_OBJ_NAMES  # noqa: E402

_HYPOTHETICAL = re.compile(r"것이라면|한다면|할\s*경우|될\s*경우|한\s*경우|될\s*전망|될\s*것으로")

# %p 차이(증감률류) 또는 상대오차(%, 수준값류) 허용 폭.
# 실측 근접 사례(0.43~4.84)가 전부 이 안에 들어오도록 잡았다 — 그 위는 진짜 큰 차이다.
CHANGE_TOLERANCE_PP = 5.0
LEVEL_TOLERANCE_PCT = 5.0


def nz(value) -> str:
    return str(value or "").strip()


def to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


_AGGREGATE_CATEGORY_NAMES = frozenset(AGGREGATE_OBJ_NAMES)


def narrow_item_mismatch(claim_text, category_name) -> str:
    """주장 문장과 골드가 고른 품목명이 무관해 보이는가.

    `kosis_indicator_table_match.indicator_table_mismatch` 와 같은 원리다 —
    문자 2-그램이 하나도 안 겹치면 무관하다. 다만 여기서는 표가 아니라
    **품목(category)** 을 본다. 실측에서 좁은 반도체 HS코드가 총액 주장에
    조직적으로 붙었던 것을 잡기 위해서다.

    **집계 이름은 예외다.** `총액`·`전국`·`총지수` 같은 이름은 그게 맞는
    좌표라도 뉴스 문장에 글자 그대로 나오는 일이 거의 없다('전체 수출액'은
    '총액' 이라는 글자를 안 담는다). 1차 구현이 이걸 놓쳐 120건 중
    90건(총지수·총액·전국)이 헛불이었다 — `kosis_meta_coordinates`
    의 정식 목록(`AGGREGATE_OBJ_NAMES`)을 그대로 가져와 뺀다.
    """
    category = nz(category_name)
    text = nz(claim_text)
    if not category or not text:
        return ""
    if category in _AGGREGATE_CATEGORY_NAMES:
        return ""
    want = bigrams(category)
    if not want:
        return ""
    if want & bigrams(text):
        return ""
    return f"주장 문장이 품목명 '{category[:28]}' 과 어휘를 하나도 공유하지 않는다"


def close_call_without_tolerance(row) -> str:
    """REFUTES 인데 허용오차 안에 들어오는가."""
    if nz(row.get("gold_label")) != "REFUTES":
        return ""
    claim_value = to_float(row.get("claim_value"))
    actual_value = to_float(row.get("gold_actual_value"))
    if claim_value is None or actual_value is None:
        return ""
    diff = abs(claim_value - actual_value)
    claim_type = nz(row.get("claim_type"))
    if claim_type in {"CHANGE_RATE", "CHANGE_POINT"}:
        if diff < CHANGE_TOLERANCE_PP:
            return f"증감률 차이 {diff:.2f}%p — 허용폭({CHANGE_TOLERANCE_PP}%p) 안"
        return ""
    if actual_value == 0:
        return ""
    relative = diff / abs(actual_value) * 100
    if relative < LEVEL_TOLERANCE_PCT:
        return f"상대오차 {relative:.1f}% — 허용폭({LEVEL_TOLERANCE_PCT}%) 안"
    return ""


def sub_monthly(row) -> str:
    """순별(旬) 주장인가. `kosis_claim_shape` 의 판정 함수를 그대로 쓴다.

    가드가 두 벌이면 반드시 어긋난다 — 오늘 이미 세 번 겪었다.
    """
    if sub_monthly_claim(row.get("claim_text")):
        return "순별(1~10일 등) 주장 — KOSIS 는 월간 이하로 쪼갠 자료가 없다"
    return ""


def hypothetical(row) -> str:
    if _HYPOTHETICAL.search(nz(row.get("claim_text"))):
        return "가정법·전망 표현 — 사실 주장이 아니라 검증 대상이 아니다"
    return ""


CHECKS = [
    ("NARROW_ITEM_MISMATCH", lambda r: narrow_item_mismatch(
        r.get("claim_text"), r.get("gold_category_name"))),
    ("CLOSE_CALL_NO_TOLERANCE", close_call_without_tolerance),
    ("SUB_MONTHLY", sub_monthly),
    ("HYPOTHETICAL", hypothetical),
]


def audit(row) -> list[tuple[str, str]]:
    """이 행이 걸리는 (코드, 사유) 목록. 여러 개 걸릴 수 있다."""
    hits = []
    for code, check in CHECKS:
        reason = check(row)
        if reason:
            hits.append((code, reason))
    return hits


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--suspect-output", required=True, type=Path)
    parser.add_argument("--trustworthy-output", required=True, type=Path)
    args = parser.parse_args()

    with args.input.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    fields = list(rows[0].keys()) + ["audit_codes", "audit_reasons"]

    suspect, trustworthy = [], []
    from collections import Counter
    code_counts: Counter = Counter()
    for row in rows:
        hits = audit(row)
        if hits:
            for code, _ in hits:
                code_counts[code] += 1
            suspect.append({**row,
                            "audit_codes": "|".join(c for c, _ in hits),
                            "audit_reasons": " ; ".join(r for _, r in hits)})
        else:
            trustworthy.append({**row, "audit_codes": "", "audit_reasons": ""})

    for path, data in [(args.suspect_output, suspect), (args.trustworthy_output, trustworthy)]:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(data)

    total = len(rows)
    print(f"=== 총 {total}건 ===")
    print(f"  의심      {len(suspect):3d}  ({len(suspect) / total * 100:.0f}%)  → {args.suspect_output}")
    print(f"  신뢰 가능 {len(trustworthy):3d}  ({len(trustworthy) / total * 100:.0f}%)  → {args.trustworthy_output}")
    print()
    print("패턴별 (한 행이 여러 패턴에 걸릴 수 있어 합이 의심 건수보다 클 수 있다):")
    for code, number in code_counts.most_common():
        print(f"  {code:26s} {number}")
    print()
    print("**'신뢰 가능'도 골드로 확정된 것이 아니다.** 이 스크립트가 아는 네 가지")
    print("패턴에 안 걸렸을 뿐이다. human_reviewed 가 이 파일 전체에서 'N' 이었다는")
    print("사실은 바뀌지 않는다 — 사람이 최소한 '의심' 은 반드시 봐야 한다.")


if __name__ == "__main__":
    main()
