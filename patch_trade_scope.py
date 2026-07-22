"""무역지표 scope 오분류 교정 (한국 수출/수입/무역수지가 '해외통계·정책'으로 새는 것).

골드 채점에서 게이트 재현율을 깎던 원인: HCX가 한국 수출액·무역수지·선박수출을
"수출=달러=해외"로 착각해 claim_domain_scope='해외통계·정책'으로 분류 → 게이트가
OUT_OF_KOSIS_SCOPE로 반려. 이는 관세청/무역통계로 검증 가능한 국내 공식통계다.

보수적 규칙(오탐 방지):
- 지표가 수출/수입/무역/교역 관련이고
- scope가 '해외통계·정책'이며
- 문장에 외국 국가명이 주체로 없으면
→ scope를 '국내공식통계'로 교정. (외국 수출 통계면 건드리지 않음)

사용법:
  python patch_trade_scope.py --input hcx_v15_monthfix.csv --output hcx_v15_scopefix.csv
"""
import argparse
import csv
import re

csv.field_size_limit(2 ** 31 - 1)

TRADE_RE = re.compile(r"수출|수입|무역수지|무역|교역")
FOREIGN = ("미국", "중국", "일본", "유럽", "EU", "독일", "프랑스", "영국", "인도",
           "베트남", "대만", "홍콩", "러시아", "캐나다", "호주", "멕시코", "브라질",
           "이탈리아", "스페인", "네덜란드", "싱가포르", "태국", "인도네시아", "필리핀",
           "아세안", "중동", "남미", "아프리카")


def has_foreign_subject(text):
    return any(c in text for c in FOREIGN)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    a = ap.parse_args()

    with open(a.input, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0].keys())

    fixed = 0
    for r in rows:
        ind = str(r.get("measurement_indicator") or r.get("indicator") or "")
        scope = str(r.get("claim_domain_scope") or "").strip()
        text = str(r.get("claim_text") or "")
        if TRADE_RE.search(ind) and scope == "해외통계·정책" and not has_foreign_subject(text):
            r["claim_domain_scope"] = "국내공식통계"
            fixed += 1
            print(f"  [{r.get('claim_measurement_id')}] {ind}={r.get('value')}{r.get('unit')} : 해외통계·정책 → 국내공식통계")

    with open(a.output, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"\nscope 교정 {fixed}건 → {a.output}")


if __name__ == "__main__":
    main()
