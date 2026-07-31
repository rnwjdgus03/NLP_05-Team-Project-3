#!/usr/bin/env python3
"""상류(추출) 품질이 검색 실패의 원인인지 측정한다.

지금까지의 진단은 **주장 쪽이 옳다고 가정**하고 검색만 채점했다.
그런데 주장 텍스트가 잘려 있거나, 한 문장에서 measurement 를 여러 개 쪼개 냈거나,
애초에 KOSIS 에 없는 대상(개별 브랜드 상품가 등)이면 **어떤 검색기도 성공할 수 없다.**

그래서 기계적으로 확인 가능한 품질 신호를 뽑아 검색 결과와 교차한다.
실패가 저품질 추출에 몰려 있으면 병목은 검색이 아니라 상류다.

기계로 못 보는 것(지표 의미가 맞는가, KOSIS 범위인가)은 판정하지 않고
`needs_human_check` 로 표시만 한다 — 추측으로 결론내지 않기 위해서다.

사용법:
  python diagnose_claim_quality.py \
    --measurements 05_hcx_measurements_kosis_ready.csv \
    --retrieval why_chroma_missed.csv \
    --output claim_quality_diagnosis.csv
"""
from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

from kosis_meta_coordinates import read_csv_rows

# 문장이 정상 종료됐는지 (한국어 종결 + 문장부호)
SENTENCE_END = re.compile(r"(다|요|음|함|됨|짐|밝혔다|말했다|전했다)[.\"'”’)\]]*\s*$|[.!?][\"'”’)\]]*\s*$")
# 앞에 숫자 파편이 붙어 시작하는 경우: "7 2023년 국적기로…"
# (앞 문장 끝의 숫자가 딸려 들어온 형태. 뒤에 한글이든 연도든 올 수 있다.)
LEADING_FRAGMENT = re.compile(r"^\s*\d{1,3}\s+(?=[가-힣\d])")
# 괄호가 열린 채 끝나는 경우: "…화장품 수출("
UNBALANCED_OPEN = re.compile(r"\([^)]*$")


def text(value) -> str:
    value = str(value or "").strip()
    return "" if value.lower() in {"nan", "none"} else value


def digits(value: str) -> str:
    return re.sub(r"[^\d]", "", value)


def value_in_text(value: str, claim_text: str) -> bool:
    """추출한 수치가 원문에 실제로 있는가 (콤마·공백 무시)."""
    target = digits(value)
    if not target:
        return False
    return target in digits(claim_text)


def unit_in_text(unit: str, claim_text: str) -> bool:
    unit = text(unit)
    if not unit:
        return False
    if unit in claim_text:
        return True
    aliases = {"%": ["%", "퍼센트", "포인트"], "명": ["명", "여 명"],
               "원": ["원"], "달러": ["달러", "弗"], "대": ["대"], "건": ["건"]}
    return any(token in claim_text for token in aliases.get(unit, []))


def period_in_text(period: str, claim_text: str) -> bool:
    """시점이 문장 안에 명시돼 있는가. 없으면 문맥에서 상속된 것."""
    period = digits(period)
    if not period:
        return False
    year = period[:4]
    if year and year in claim_text:
        return True
    # '작년'/'지난해'/'올해' 같은 상대 표현은 문장 안 근거로 인정
    return any(word in claim_text for word in ("작년", "지난해", "올해", "전년", "지난달", "이달"))


def token_overlap(indicator: str, claim_text: str) -> bool:
    indicator = text(indicator)
    if not indicator:
        return False
    tokens = [t for t in re.split(r"[\s·,/()]+", indicator) if len(t) >= 2]
    return any(t in claim_text for t in tokens)


def quality_flags(claim: dict, siblings: int) -> dict:
    claim_text = text(claim.get("claim_text"))
    flags = {
        "text_len": len(claim_text),
        # 원문 대조 — 추출값이 문장에 실제로 있는가
        "value_in_text": value_in_text(text(claim.get("value")), claim_text),
        "unit_in_text": unit_in_text(claim.get("unit"), claim_text),
        "period_in_text": period_in_text(
            text(claim.get("measurement_period")) or text(claim.get("period")), claim_text),
        "indicator_in_text": token_overlap(
            text(claim.get("measurement_indicator")) or text(claim.get("indicator")), claim_text),
        # 문장 경계 품질
        "truncated": not bool(SENTENCE_END.search(claim_text)) if claim_text else True,
        "leading_fragment": bool(LEADING_FRAGMENT.search(claim_text)),
        "unbalanced_paren": bool(UNBALANCED_OPEN.search(claim_text)),
        # 한 문장에서 measurement 를 몇 개나 쪼갰나
        "measurements_from_same_text": siblings,
        "crowded_sentence": siblings >= 3,
        # 스키마 결측
        "mapping_type_missing": not text(claim.get("mapping_type")),
        "period_missing": not (text(claim.get("measurement_period")) or text(claim.get("period"))),
        "unit_missing": not text(claim.get("unit")),
    }
    problems = [name for name in
                ("truncated", "leading_fragment", "unbalanced_paren", "crowded_sentence",
                 "period_missing", "unit_missing")
                if flags[name]]
    problems += [name for name in ("value_in_text", "indicator_in_text") if not flags[name]]
    flags["problem_count"] = len(problems)
    flags["problems"] = ";".join(problems)
    # 의미 판단(지표가 맞는가 / KOSIS 범위인가)은 기계가 못 한다 → 표시만
    flags["needs_human_check"] = flags["problem_count"] == 0
    return flags


def diagnose(claims, retrieval_rows):
    outcome = {text(r.get("claim_measurement_id")): text(r.get("failure_class"))
               for r in retrieval_rows}
    by_text = defaultdict(int)
    for claim in claims:
        by_text[text(claim.get("claim_text"))] += 1

    rows = []
    for claim in claims:
        mid = text(claim.get("claim_measurement_id"))
        claim_text = text(claim.get("claim_text"))
        flags = quality_flags(claim, by_text[claim_text])
        rows.append({
            "claim_measurement_id": mid,
            "retrieval_outcome": outcome.get(mid, "(평가대상아님)"),
            "claim_text": claim_text[:160],
            "value": text(claim.get("value")),
            "unit": text(claim.get("unit")),
            "period": text(claim.get("measurement_period")) or text(claim.get("period")),
            "indicator": text(claim.get("measurement_indicator")) or text(claim.get("indicator")),
            **flags,
        })
    return rows


def report(rows) -> None:
    total = len(rows)
    print(f"measurement {total}건\n")

    print("=== 품질 신호별 해당 건수 ===")
    for name in ("truncated", "leading_fragment", "unbalanced_paren", "crowded_sentence",
                 "period_missing", "unit_missing", "mapping_type_missing"):
        n = sum(1 for r in rows if r[name])
        print(f"  {name}: {n} ({n/max(total,1):.1%})")
    for name in ("value_in_text", "indicator_in_text", "unit_in_text", "period_in_text"):
        n = sum(1 for r in rows if not r[name])
        print(f"  NOT {name}: {n} ({n/max(total,1):.1%})")

    print("\n=== 검색 결과 × 상류 문제 개수 (핵심 표) ===")
    grid = defaultdict(Counter)
    for r in rows:
        bucket = "문제 0개" if r["problem_count"] == 0 else \
                 "문제 1개" if r["problem_count"] == 1 else "문제 2개+"
        grid[r["retrieval_outcome"]][bucket] += 1
    buckets = ("문제 0개", "문제 1개", "문제 2개+")
    print(f"  {'검색결과':<24}" + "".join(f"{b:>10}" for b in buckets) + f"{'합계':>8}")
    for outcome in sorted(grid):
        counts = grid[outcome]
        line = f"  {outcome:<24}" + "".join(f"{counts.get(b,0):>10}" for b in buckets)
        print(line + f"{sum(counts.values()):>8}")

    ok = [r for r in rows if r["retrieval_outcome"] == "COORD_IN_TOPK"]
    bad = [r for r in rows if r["retrieval_outcome"] in
           {"TABLE_MISS", "TABLE_OK_COORD_MISS", "NO_CANDIDATE"}]
    if ok and bad:
        ok_rate = sum(r["problem_count"] for r in ok) / len(ok)
        bad_rate = sum(r["problem_count"] for r in bad) / len(bad)
        print(f"\n  검색 성공군 평균 문제 수: {ok_rate:.2f} (n={len(ok)})")
        print(f"  검색 실패군 평균 문제 수: {bad_rate:.2f} (n={len(bad)})")
        print("  → 실패군이 뚜렷이 높으면 병목은 검색이 아니라 상류다.")
        print("  → 차이가 없으면 상류 품질은 원인이 아니다(검색 문제로 확정).")

    print("\n=== 문제 많은 주장 표본 (사람이 읽고 KOSIS 범위인지 판단할 것) ===")
    for r in sorted(rows, key=lambda x: -x["problem_count"])[:15]:
        print(f"  [{r['problem_count']}] {r['retrieval_outcome']:<20} {r['problems']}")
        print(f"      {r['claim_text'][:110]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--measurements", required=True)
    ap.add_argument("--retrieval", default="", help="why_chroma_missed.csv")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    claims = read_csv_rows(args.measurements)
    retrieval = read_csv_rows(args.retrieval) if args.retrieval else []
    rows = diagnose(claims, retrieval)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    report(rows)
    print(f"\n저장: {args.output}")


if __name__ == "__main__":
    main()
