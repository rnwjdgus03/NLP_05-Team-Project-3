"""이미 추출된 measurement CSV에 월 시점 복구를 소급 적용한다 (API 재호출 없음).

extract_hcx.py의 apply_local_explicit_months와 같은 로직을, 이미 뽑아둔 flat CSV에 적용한다.
월간(prd_se=M) 측정값이 연도만 갖고 있으면 claim_text에서 값 바로 앞의 'N월'을 찾아 YYYYMM으로 바인딩.
같은 문장에 여러 월값이 나열될 때 전부 같은 달로 뭉개지는 버그를 소급 교정한다.

사용법:
  python patch_month_periods.py --input hcx_v15.csv --output hcx_v15_monthfix.csv
"""
import argparse
import csv
import re
from collections import defaultdict

csv.field_size_limit(2 ** 31 - 1)


def nz(v):
    s = str(v or "").strip()
    return "" if s in ("", "nan", "None", "-") else s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    a = ap.parse_args()

    with open(a.input, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0].keys())

    # claim_id 별로 원문 내 탐색 위치를 이어가며(중복 값 대비) 월을 바인딩
    search_from = defaultdict(int)
    fixed = 0
    for r in rows:
        if nz(r.get("measurement_prd_se")) != "M":
            continue
        period = nz(r.get("measurement_period"))
        if not re.fullmatch(r"(?:19|20)\d{2}", period):
            continue
        year = period
        text = str(r.get("claim_text") or "")
        key = nz(r.get("measurement_text")) or nz(r.get("value"))
        if not key:
            continue
        cid = r.get("claim_id", "")
        idx = text.find(key, search_from[cid])
        if idx < 0:
            idx = text.find(key)
        if idx < 0:
            continue
        search_from[cid] = idx + len(key)
        local = text[max(0, idx - 12):idx]
        months = re.findall(r"(\d{1,2})\s*월", local)
        if not months:
            continue
        month = int(months[-1])
        if not 1 <= month <= 12:
            continue
        new_period = f"{year}{month:02d}"
        if new_period != period:
            r["measurement_period"] = new_period
            fixed += 1
            print(f"  [{r.get('claim_measurement_id')}] {key} : {period} -> {new_period}")

    with open(a.output, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"\n월 시점 복구 {fixed}건 -> {a.output}")


if __name__ == "__main__":
    main()
