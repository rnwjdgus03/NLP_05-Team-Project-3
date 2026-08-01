#!/usr/bin/env python3
"""NEAR_MISS 가 왜 정확히 안 맞았는지 산술로 분류한다 (판단 아님, API 0회).

배경: `NEAR_MISS` 는 "값이 오차밴드 안까지 갔는데 정확히는 안 맞았다" 는 뜻이라
**좌표는 맞을 가능성이 높다.** 실제로 산업활동동향 건은 좌표가 처음부터 맞았고
우리 쪽 부호 처리가 틀려서 차이가 1.01%p 로 부풀어 있었다(고친 뒤 0.21%p).

그런 계통적 원인이 더 있으면, 사람이 라벨하는 대신 **버그를 고쳐서 골드를 늘릴 수 있다.**
이 스크립트는 원인을 추정하지 않고 **산술로 분류만** 한다.

분류 (measurement 당 차이가 가장 작은 좌표 기준)
  SIGN_MISMATCH      부호만 다르고 크기는 비슷 → 방향 처리 문제. 고치면 승격 가능
  SCALE_MISMATCH     비율이 10의 거듭제곱 → 단위 배율 문제. 고치면 승격 가능
  DISPLAY_ROUNDING   차이가 기사 표시 자릿수 한 단위 이내 → 기사 반올림
  SMALL_GAP          상대오차가 작음 → 잠정치·개정으로 설명 가능
  LARGE_GAP          그 외 → 좌표가 틀렸을 가능성이 높다

사용법:
  python diagnose_near_miss.py \
    --silver silver_coordinates.csv \
    --review needs_human_review.csv \
    --output near_miss_diagnosis.csv
"""
from __future__ import annotations

import argparse
import csv
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from kosis_meta_coordinates import read_csv_rows

TARGET_TIERS = {"NEAR_MISS"}

# 부호가 다르면서 크기가 이 범위 안이면 '부호만 틀렸다' 로 본다.
SIGN_RATIO_LOW, SIGN_RATIO_HIGH = 0.7, 1.4
# 비율이 10^k 에 이만큼 이내로 붙으면 단위 배율 문제로 본다.
SCALE_TOLERANCE = 0.02
# 상대오차가 이 이내면 잠정치·개정으로 설명 가능한 수준으로 본다.
SMALL_GAP_PCT = 10.0

# 우리 쪽을 고치면 비교가 가능해지는 원인들(좌표 문제가 아니다).
# UNIT_CURRENCY_MISMATCH 는 환율이 필요해 우리가 못 고친다 → 게이트 대상.
# UNIT_DIMENSION_CONFLICT 는 좌표가 틀린 것이라 여기 넣지 않는다.
FIXABLE = {"SIGN_MISMATCH", "SCALE_MISMATCH",
           "UNIT_KOSIS_MISSING", "UNIT_UNCONVERTIBLE"}


def text(value) -> str:
    value = str(value or "").strip()
    return "" if value.lower() in {"nan", "none"} else value


def number(value):
    raw = text(value).replace(",", "")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


# 검증기는 방향어를 보고 부호를 붙인 뒤 비교하는데, 그 결과를 verdict_reason 에만 남긴다.
# review CSV 의 claim_value 는 **부호 적용 전** 원본이라 그대로 비교하면
# 정상 판정을 'SIGN_MISMATCH' 로 오분류한다(실측: 1.6 vs -1.68 을 부호 문제로 오판).
SIGNED_CLAIM = re.compile(r"방향부호 적용:\s*claim\s*=\s*(-?\d[\d,]*(?:\.\d+)?)")


def effective_claim_value(row):
    """검증기가 실제로 비교에 쓴 기사 값. 부호 적용 결과가 있으면 그것을 쓴다."""
    found = SIGNED_CLAIM.search(text(row.get("verdict_reason")))
    if found:
        return number(found.group(1)), found.group(1)
    raw = text(row.get("claim_value"))
    return number(raw), raw


def display_ulp(raw: str) -> float:
    """기사에 적힌 자릿수의 최소 단위. '1.6' → 0.1, '2' → 1."""
    raw = text(raw).replace(",", "").lstrip("-+")
    if "." in raw:
        return 10 ** -len(raw.split(".", 1)[1])
    return 1.0


# `unit_factor` 가 남기는 두 가지 실패 메시지. 원인이 달라 처방도 다르다.
UNIT_UNKNOWN_MSG = re.compile(r"단위 차원 미확정:\s*KOSIS=([^,]*),\s*claim=(.*?)(?:\)|$|/)")
UNIT_CONFLICT_MSG = re.compile(r"단위 불일치:\s*KOSIS=([^(]*)\(([^)]*)\),\s*claim=([^(]*)\(([^)]*)\)")


def unit_failure_cause(reason: str) -> tuple[str, str]:
    """단위 실패를 세 갈래로 가른다 — 처방이 전부 다르기 때문이다.

    UNIT_KOSIS_MISSING     KOSIS 쪽 단위가 비어 있다 → 메타 스냅샷 폴백으로 회수 가능
    UNIT_CURRENCY_MISMATCH 통화가 다르다(원 vs 달러) → 환율 없이는 불가. 게이트 대상
    UNIT_DIMENSION_CONFLICT 차원이 다르다(금액 vs 개수) → 좌표가 틀렸을 가능성
    """
    unknown = UNIT_UNKNOWN_MSG.search(reason)
    if unknown:
        kosis_unit, claim_unit = unknown.group(1).strip(), unknown.group(2).strip()
        if not kosis_unit or kosis_unit in {"-", "None"}:
            return ("UNIT_KOSIS_MISSING",
                    f"KOSIS 단위가 비어 변환 불가 (claim={claim_unit}) — 메타 폴백으로 회수 가능")
        return ("UNIT_CLAIM_MISSING",
                f"기사 단위를 해석 못 함 (KOSIS={kosis_unit}, claim={claim_unit})")

    conflict = UNIT_CONFLICT_MSG.search(reason)
    if conflict:
        k_unit, k_spec, c_unit, c_spec = (g.strip() for g in conflict.groups())
        k_family = k_spec.split("/")[-1]
        c_family = c_spec.split("/")[-1]
        k_dim = k_spec.split("/")[0]
        c_dim = c_spec.split("/")[0]
        if k_dim == c_dim and k_family != c_family:
            return ("UNIT_CURRENCY_MISMATCH",
                    f"통화가 다름 ({k_family} vs {c_family}) — 환율 없이는 비교 불가")
        return ("UNIT_DIMENSION_CONFLICT",
                f"단위 차원이 다름 ({k_dim} vs {c_dim}) — 좌표가 틀렸을 가능성")

    return "UNIT_UNCONVERTIBLE", "단위를 변환하지 못해 값 비교 자체가 불가"


def no_value_cause(row) -> tuple[str, str]:
    """KOSIS 값이 비어 비교 자체를 못 한 경우의 원인을 verdict 기록에서 읽는다.

    실측에서 NEAR_MISS 30건 중 20건이 여기였다. '좌표가 틀렸다' 가 아니라
    **단위를 못 맞춰 비교를 못 한 것**이 대부분이라, 좌표 문제와 섞어 세면 안 된다.
    """
    code = text(row.get("verdict_code"))
    reason = text(row.get("verdict_reason"))
    if code == "UNIT_UNCERTAIN" or "단위 비호환" in reason or "단위" in reason:
        return unit_failure_cause(reason)
    if "조회 데이터 없음" in reason or code == "ACTUAL_DERIVATION_FAILED":
        return "NO_DATA_IN_PERIOD", "해당 시점 데이터가 없음"
    return "NO_VALUE_OTHER", f"값 없음 ({code or '사유 미기록'})"


def classify_gap(claim_value, actual_value, claim_raw: str) -> tuple[str, str]:
    """두 값의 관계를 산술로만 분류한다."""
    if claim_value is None or actual_value is None:
        return "NO_VALUE", "값이 없어 비교 불가"
    if claim_value == 0:
        return "LARGE_GAP", "기사 값이 0 이라 비율 계산 불가"

    gap = abs(actual_value - claim_value)
    ratio = abs(actual_value) / abs(claim_value)

    if (actual_value < 0) != (claim_value < 0):
        if SIGN_RATIO_LOW <= ratio <= SIGN_RATIO_HIGH:
            return ("SIGN_MISMATCH",
                    f"부호만 다름 (크기 비율 {ratio:.2f}) — 방향 처리 문제")

    if ratio > 0:
        exponent = round(math.log10(ratio))
        if exponent != 0 and abs(ratio - 10 ** exponent) <= 10 ** exponent * SCALE_TOLERANCE:
            return ("SCALE_MISMATCH",
                    f"비율이 10^{exponent} 에 근접({ratio:.4g}) — 단위 배율 문제")

    ulp = display_ulp(claim_raw)
    if gap <= ulp:
        return ("DISPLAY_ROUNDING",
                f"차이 {gap:.4g} 가 기사 표시 단위({ulp:g}) 이내 — 반올림 수준")

    pct = gap / abs(claim_value) * 100
    if pct <= SMALL_GAP_PCT:
        return "SMALL_GAP", f"상대오차 {pct:.2f}% — 잠정치·개정으로 설명 가능"
    return "LARGE_GAP", f"상대오차 {pct:.2f}% — 좌표가 틀렸을 가능성"


def best_row(rows):
    """차이가 가장 작은 좌표 하나를 고른다(그 measurement 의 최선 후보).

    값이 있는 후보를 우선한다 — 단위 변환에 실패한 후보가 앞서면
    비교 가능한 좌표가 있는데도 'NO_VALUE' 로 집계된다.
    """
    scored = []
    for row in rows:
        claim, _ = effective_claim_value(row)
        actual = number(row.get("kosis_actual_value"))
        if claim is None or actual is None or claim == 0:
            continue
        scored.append((abs(actual - claim) / abs(claim), row))
    if not scored:
        return rows[0] if rows else None
    scored.sort(key=lambda pair: pair[0])
    return scored[0][1]


def diagnose(silver_rows, review_rows) -> list[dict]:
    tier_of = {text(r.get("claim_measurement_id")): text(r.get("tier")) for r in silver_rows}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in review_rows:
        mid = text(row.get("claim_measurement_id"))
        if tier_of.get(mid) in TARGET_TIERS and text(row.get("verdict")) == "판정보류":
            grouped[mid].append(row)

    out = []
    for mid in sorted(grouped):
        row = best_row(grouped[mid])
        if row is None:
            continue
        claim, claim_raw = effective_claim_value(row)
        actual = number(row.get("kosis_actual_value"))
        code, why = classify_gap(claim, actual, claim_raw)
        if code == "NO_VALUE":
            code, why = no_value_cause(row)
        out.append({
            "claim_measurement_id": mid,
            "cause": code,
            "fixable": "Y" if code in FIXABLE else "N",
            "why": why,
            "claim_value": claim_raw,
            "claim_value_raw": text(row.get("claim_value")),
            "kosis_actual_value": text(row.get("kosis_actual_value")),
            "tbl_id": text(row.get("tbl_id")),
            "tbl_name": text(row.get("tbl_name"))[:40],
            "selected_itm_name": text(row.get("selected_itm_name"))[:30],
            "selected_obj_l1": text(row.get("selected_obj_l1")),
            "mapping_type": text(row.get("mapping_type")),
            "candidates_examined": len(grouped[mid]),
            "claim_unit": text(row.get("unit")),
            "verdict_reason": text(row.get("verdict_reason"))[:160],
            "claim_text": text(row.get("claim_text"))[:110],
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--silver", required=True)
    ap.add_argument("--review", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    rows = diagnose(read_csv_rows(args.silver), read_csv_rows(args.review))
    if not rows:
        raise SystemExit("NEAR_MISS 가 없다. 입력을 확인할 것.")

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    causes = Counter(r["cause"] for r in rows)
    fixable = sum(1 for r in rows if r["fixable"] == "Y")
    print(f"NEAR_MISS {len(rows)}건 원인 분류\n")
    for cause, n in causes.most_common():
        print(f"  {cause:<18} {n:>3}")
    print(f"\n우리 쪽 수정으로 비교 가능해지는 건: {fixable}건")
    print("  (UNIT_UNCONVERTIBLE / SIGN_MISMATCH / SCALE_MISMATCH — 좌표 문제가 아님)")
    print("DISPLAY_ROUNDING 은 판정 허용오차를 재검토하면 승격 후보다.")

    for cause in ("UNIT_KOSIS_MISSING", "UNIT_CURRENCY_MISMATCH",
              "UNIT_DIMENSION_CONFLICT", "UNIT_CLAIM_MISSING",
              "UNIT_UNCONVERTIBLE", "SIGN_MISMATCH", "SCALE_MISMATCH",
              "DISPLAY_ROUNDING"):
        picked = [r for r in rows if r["cause"] == cause]
        if not picked:
            continue
        print(f"\n=== {cause} ({len(picked)}건) ===")
        for r in picked[:8]:
            print(f"  기사 {r['claim_value']:>14} vs KOSIS {r['kosis_actual_value'][:14]:>14}"
                  f"  [{r['tbl_id']}] {r['selected_itm_name']}")
            print(f"    {r['why']}")
            print(f"    {r['claim_text'][:90]}")

    large = [r for r in rows if r["cause"] == "LARGE_GAP"]
    if large:
        print(f"\n=== LARGE_GAP ({len(large)}건) — 좌표가 틀렸을 가능성 ===")
        for r in large[:8]:
            print(f"  {r['why']} | [{r['tbl_id']}] {r['selected_itm_name']}")
            print(f"    {r['claim_text'][:90]}")

    print(f"\n저장: {args.output}")


if __name__ == "__main__":
    main()
