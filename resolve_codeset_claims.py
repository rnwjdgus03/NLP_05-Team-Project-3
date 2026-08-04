"""승인된 OBJ 코드셋을 다중 KOSIS 조회·합산해 CODESET_REQUIRED를 재판정하는 애드온.

verify는 후보가 READY가 아니면 조회 없이 CODESET_REQUIRED로 튕긴다. 이 스크립트는
사람이 검토해 obj_codes(합산 대상 코드)와 aggregation을 채운 행만 골라, 각 코드를
개별 조회한 뒤 데이터가 있는 코드만 합산해 잠정 판정(PROVISIONAL_*)을 낸다.

- obj_codes 표기: 'A02|A03' (파이프/세미콜론/쉼표 구분) 또는 'A01-A24' (범위 자동 확장)
- 수준값(수출액·여객수 등): 대상 시점 멤버 DT 합산 → claim과 비교
- 증감률(rate_from_level): 현재·비교 시점 멤버 합산 후 (현재-이전)/이전*100
- 일부 멤버 데이터 없으면 있는 것만 합산하고 결측 수를 기록(잠정)
- kosis_itm_name을 결과에 남겨 '교역액 vs 수출액' 같은 의미 불일치를 검토자가 잡게 함

사용법:
  python resolve_codeset_claims.py --input hcx_v15_kosis_final_review.csv \
    --output outputs/runs/hcx_v15_codeset_resolved.csv

주의: KOSIS API 접속 가능한 로컬에서 실행(.env의 KOSIS_API_KEY). verify를 대체하지 않고,
CODESET_REQUIRED 행만 갱신한다.
"""
import argparse
import csv
import re
import time
from pathlib import Path

from kosis_api_test import get_stat_data
from kosis_verify_claim_values import (
    parse_number, parse_period, normalize_prd_se, period_range,
    unit_factor, clean_data_rows, judge,
)

csv.field_size_limit(2 ** 31 - 1)

RANGE_RE = re.compile(r"^([A-Za-z_]+)(\d+)-([A-Za-z_]+)?(\d+)$")


def nz(v):
    s = str(v or "").strip()
    return "" if s in ("", "nan", "None", "-") else s


def expand_codes(spec):
    """'A02|A03' -> [A02,A03];  'A01-A24' -> [A01..A24] (자리수 보존)."""
    spec = nz(spec)
    if not spec:
        return []
    codes = []
    for part in re.split(r"[|;,]", spec):
        part = part.strip()
        if not part:
            continue
        m = RANGE_RE.match(part)
        if m:
            prefix, start, prefix2, end = m.groups()
            width = len(start)
            for n in range(int(start), int(end) + 1):
                codes.append(f"{prefix}{n:0{width}d}")
        else:
            codes.append(part)
    # 중복 제거(순서 유지)
    seen, out = set(), []
    for c in codes:
        if c not in seen:
            seen.add(c); out.append(c)
    return out


def dt_by_period(org, tbl, code, itm, prd_se, prd_params, delay):
    """단일 코드 조회 → {PRD_DE: DT_float}."""
    cnt = 60 if prd_se == "M" else (12 if prd_se in {"Q", "H"} else 10)
    try:
        data = get_stat_data(org_id=org, tbl_id=tbl, obj_l1=code, itm_id=itm,
                             prd_se=prd_se, new_est_prd_cnt=cnt, **prd_params)
        time.sleep(delay)
    except Exception as exc:
        return {}, f"{code}:API오류({exc})"
    out = {}
    for r in clean_data_rows(data):
        v = parse_number(r.get("DT"))
        if v is not None:
            out[str(r.get("PRD_DE", ""))] = v
    return out, ""


def summed_level(members, period_key):
    """멤버별 {PRD_DE:DT} dict 목록에서 특정 시점 합산. (합, 있는 멤버, 없는 멤버)."""
    total, have, miss = 0.0, [], []
    for code, dmap in members:
        if period_key in dmap:
            total += dmap[period_key]; have.append(code)
        else:
            miss.append(code)
    return total, have, miss


def resolve_row(row, delay):
    out = dict(row)
    codes = expand_codes(row.get("obj_codes"))
    if not codes:
        return out, False  # 코드셋 없음(반도체 등) → 그대로 둠
    org, tbl = nz(row.get("org_id")), nz(row.get("tbl_id"))
    itm = nz(row.get("selected_itm_id"))
    claim_value = parse_number(row.get("value"))
    prd_se = normalize_prd_se(row.get("prd_se"), row.get("period"))
    target = parse_period(row.get("period"))
    mapping_type = nz(row.get("mapping_type")) or "direct"
    comparison = nz(row.get("comparison_period"))
    prd_params, _ = period_range(row.get("period"), prd_se,
                                 comparison if mapping_type == "rate_from_level" else "")

    # 멤버별 시계열 수집
    members, errs = [], []
    for c in codes:
        dmap, err = dt_by_period(org, tbl, c, itm, prd_se, prd_params, delay)
        members.append((c, dmap))
        if err:
            errs.append(err)

    cur, have, miss = summed_level(members, target)
    if not have:
        out.update({"verdict": "판단불가", "verdict_code": "PROVISIONAL_NO_DATA",
                    "verdict_reason": f"멤버 {len(codes)}개 모두 대상시점 데이터 없음 / itm={row.get('selected_itm_name')}"})
        return out, True

    itm_name = nz(row.get("selected_itm_name"))
    if mapping_type == "rate_from_level":
        prev_key = parse_period(comparison)
        prev, phave, _ = summed_level(members, prev_key)
        if not phave or prev == 0:
            out.update({"verdict": "판단불가", "verdict_code": "PROVISIONAL_NO_BASE",
                        "verdict_reason": f"비교시점({prev_key}) 합산 불가 / itm={itm_name}"})
            return out, True
        actual = (cur - prev) / prev * 100.0
        factor_note = f"증감률=합산수준값 기준 ({prev_key}->{target})"
    else:
        factor, fnote = unit_factor(itm_name and row.get("kosis_unit") or "", row.get("unit"))
        factor = factor if factor is not None else 1.0
        actual = cur * factor
        factor_note = fnote

    verdict, reason = judge(claim_value, actual, tolerance_abs=0.5, tolerance_pct=1.0)
    code = "PROVISIONAL_MATCH" if verdict == "일치" else (
        "PROVISIONAL_MISMATCH" if verdict == "불일치" else "PROVISIONAL_COMPARISON_FAILED")
    miss_note = f", 결측멤버 {len(miss)}/{len(codes)}" if miss else ""
    out.update({
        "kosis_actual_value": actual,
        "kosis_period_used": target,
        "kosis_rows_used": len(have),
        "value_diff": (actual - claim_value) if claim_value is not None else "",
        "verdict": "일치" if verdict == "일치" else ("불일치" if verdict == "불일치" else "판단불가"),
        "verdict_code": code,
        "verdict_stage": "codeset_sum",
        "verdict_reason": f"합산 actual={actual:.4g} vs claim={claim_value} / {reason} / "
                          f"itm={itm_name} / 합산멤버={'+'.join(have)}{miss_note} / {factor_note}",
    })
    return out, True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", default="outputs/runs/codeset_resolved.csv")
    ap.add_argument("--delay", type=float, default=0.12)
    a = ap.parse_args()

    with open(a.input, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0].keys())

    n_res = 0
    out_rows = []
    for r in rows:
        if nz(r.get("verdict_code")) == "CODESET_REQUIRED" or nz(r.get("obj_codes")):
            new, resolved = resolve_row(r, a.delay)
            if resolved:
                n_res += 1
                print(f"[{new.get('claim_measurement_id')}] {new.get('verdict')} "
                      f"({new.get('verdict_code')}) {new.get('verdict_reason','')[:90]}")
            out_rows.append(new)
        else:
            out_rows.append(r)

    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    with open(a.output, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader(); w.writerows(out_rows)
    print(f"\n재판정 {n_res}건 → {a.output}")


if __name__ == "__main__":
    main()
