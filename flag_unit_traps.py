"""추출된 measurement의 단위 함정을 규칙으로 한 번 더 걸러 플래그한다 (자동 수정 안 함, 검토 표시만).

멘토 조언(단위 인식): 완전 정규화는 불가하니, 발견된 함정 패턴을 규칙으로 잡아 검토 대상으로 남긴다.
값을 바꾸지 않고 unit_trap_flag / unit_trap_reason 컬럼만 추가해, 사람이 확인 후 판단하게 한다.
(현재 51/100 표본엔 함정이 거의 없어 예방용이며, 큰 표본 확장 시 안전망이 된다.)

플래그 규칙 (보수적, 명백한 것만):
- unit=='개'인데 measurement_text에 '개월' 포함  -> 기간(개월)을 개수로 오인 의심
- unit in {만, 억, 천, 조}                        -> 배수를 단위로 오인 (만/억은 단위가 아님)
- unit=='세'인데 measurement_text에 '세대'/'세기' -> 나이(세)와 세대·세기 혼동 의심

사용법:
  python flag_unit_traps.py --input hcx_v15.csv --output hcx_v15_flagged.csv
"""
import argparse
import csv

csv.field_size_limit(2 ** 31 - 1)

MULTIPLIER_UNITS = {"만", "억", "천", "조"}


def flag(row):
    unit = str(row.get("unit") or "").strip()
    text = str(row.get("measurement_text") or "")
    if unit == "개" and "개월" in text:
        return "기간(개월)을 개수(개)로 오인 의심"
    if unit in MULTIPLIER_UNITS:
        return f"배수('{unit}')를 단위로 오인 — 실제 단위/배율 확인 필요"
    if unit == "세" and ("세대" in text or "세기" in text):
        return "나이(세)와 세대/세기 혼동 의심"
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    a = ap.parse_args()

    with open(a.input, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0].keys())
    for c in ("unit_trap_flag", "unit_trap_reason"):
        if c not in fields:
            fields.append(c)

    n = 0
    for r in rows:
        reason = flag(r)
        r["unit_trap_flag"] = "Y" if reason else "N"
        r["unit_trap_reason"] = reason
        if reason:
            n += 1
            print(f"  [{r.get('claim_measurement_id')}] value={r.get('value')} unit={r.get('unit')} text='{r.get('measurement_text')}' -> {reason}")

    with open(a.output, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"\n함정 플래그 {n}건 / 전체 {len(rows)}행 -> {a.output}")


if __name__ == "__main__":
    main()
