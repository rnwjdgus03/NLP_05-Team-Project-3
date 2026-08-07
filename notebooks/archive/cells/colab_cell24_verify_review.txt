# 24. 검수 3가지 직접 확인 (KOSIS API 조회 — 사이트 탐색 불필요)
#
# 이건 판단이 아니라 '사실 조회'다. 메타에 뭐가 있는지, 실제 값이 얼마인지만 본다.
from kosis_api_test import get_meta, get_stat_data

def show(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)

# ── 확인 1: 무역수지(흑자) 항목이 따로 있는가 ────────────────────────────
show("확인 1. DT_1R11001_FRM101 에 '무역수지/수지' 항목이 있나")
meta = get_meta("101", "DT_1R11001_FRM101", "ITM")
items = [r for r in meta if r.get("OBJ_ID") == "ITEM"]
print(f"항목(ITEM) {len(items)}개:")
for r in items:
    print(f"  {r.get('ITM_ID'):<24} {r.get('ITM_NM')}   [{r.get('UNIT_NM','')}]")
hit = [r for r in items if any(k in str(r.get("ITM_NM", ""))
                               for k in ("수지", "흑자", "적자", "balance"))]
print(f"\n→ '수지/흑자' 관련 항목: {len(hit)}개")
for r in hit:
    print(f"   {r.get('ITM_ID')} {r.get('ITM_NM')}")
print("   (있으면 → 518억달러 흑자를 수입액에 붙인 것은 명백한 오매핑)")

# ── 확인 2: DT_1JH20202 의 objL1=1 은 무엇인가 ──────────────────────────
show("확인 2. DT_1JH20202 의 분류1 코드 '1' 의 이름")
meta2 = get_meta("101", "DT_1JH20202", "ITM")
objs = [r for r in meta2 if r.get("OBJ_ID") != "ITEM"]
print(f"분류축 코드 {len(objs)}개 (앞 20개):")
for r in objs[:20]:
    mark = "  ← 이것" if str(r.get("ITM_ID")) == "1" else ""
    print(f"  [{r.get('OBJ_ID')}] {r.get('ITM_ID'):<12} {r.get('ITM_NM')}{mark}")
print("\n항목(ITEM):")
for r in meta2:
    if r.get("OBJ_ID") == "ITEM":
        print(f"  {r.get('ITM_ID'):<12} {r.get('ITM_NM')}   [{r.get('UNIT_NM','')}]")

# ── 확인 3: 2024년 9·10월 전산업생산 전월비 실제 부호 ────────────────────
show("확인 3. 2024년 8~11월 계절조정지수 → 전월비 직접 계산")
rows = get_stat_data(
    org_id="101", tbl_id="DT_1JH20202",
    obj_l1="1", itm_id="T1", prd_se="M",
    new_est_prd_cnt=1, startPrdDe="202406", endPrdDe="202412")
series = {}
for r in rows:
    if r.get("DT") not in (None, ""):
        try:
            series[str(r.get("PRD_DE"))] = float(r["DT"])
        except ValueError:
            pass
print("조회된 시점:", ", ".join(f"{k}={v}" for k, v in sorted(series.items())))

print("\n전월 대비 증감률:")
months = sorted(series)
for prev, cur in zip(months, months[1:]):
    change = (series[cur] - series[prev]) / series[prev] * 100
    note = ""
    if cur == "202409":
        note = "   ← 기사 주장: -0.4%"
    if cur == "202410":
        note = "   ← 기사 주장: -0.2%"
    if cur == "202411":
        note = "   ← 기사 주장: -0.4%"
    print(f"  {cur}: {change:+.2f}%{note}")

print("\n판단 기준:")
print("  부호가 기사와 같으면  → 우리 기간 정렬이 틀린 것(고칠 수 있는 버그)")
print("  부호가 기사와 다르면  → 기사가 다른 지표를 말한 것(예: 원지수/광공업)")
