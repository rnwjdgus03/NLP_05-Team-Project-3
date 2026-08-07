# 25. 두 가지 확정: (a) 검증기가 실제로 쓴 기간, (b) 무역수지 항목 존재 여부
#
# 확인 3 에서 202409 실제 전월비는 -0.61% 인데 우리 시스템은 +0.61% 로 계산했다.
# 크기는 맞고 부호만 뒤집혔다 → 기간 정렬 또는 증감 방향 계산 버그가 의심된다.
# 추측하지 말고 검증기가 남긴 컬럼을 그대로 본다.
import pandas as pd

from kosis_api_test import get_meta

verified = pd.read_csv(f'{OUT}/05_hcx_measurements_kosis_verified_released.csv',
                       dtype=str, keep_default_na=False)

cols = ['claim_measurement_id', 'value', 'claim_value_numeric', 'period',
        'comparison_period', 'mapping_type',
        'kosis_period_used', 'kosis_previous_period_used',
        'kosis_actual_raw', 'kosis_actual_value', 'value_diff', 'verdict']
have = [c for c in cols if c in verified.columns]

print("=" * 78)
print("(a) 산업활동동향 2건 — 검증기가 실제로 쓴 기간과 값")
print("=" * 78)
target = verified[verified['tbl_id'] == 'DT_1JH20202'] if 'tbl_id' in verified.columns \
         else verified[verified['claim_measurement_id'].str.startswith('A0023-SPE3405D9C32')]
for _, r in target.iterrows():
    print()
    for c in have:
        print(f"  {c:<28} {r[c]}")

print("\n실제 계절조정지수 (확인 3 결과): 202408=114.3  202409=113.6  202410=114.9")
print("  올바른 202409 전월비 = (113.6-114.3)/114.3 = -0.61%")
print("  부호가 반대로 나왔다면 → 증감 계산에서 기준/대상 시점이 뒤바뀐 것")

# ── (b) 무역수지 항목이 있는가 — org_id 를 데이터에서 가져온다 ────────────
print("\n" + "=" * 78)
print("(b) DT_1R11001_FRM101 의 항목 목록 (org_id 를 실제 데이터에서 조회)")
print("=" * 78)
trade = verified[verified['tbl_id'] == 'DT_1R11001_FRM101'] if 'tbl_id' in verified.columns \
        else pd.DataFrame()
org = trade['org_id'].iloc[0] if len(trade) and 'org_id' in trade.columns else '134'
print(f"org_id = {org}")
try:
    meta = get_meta(org, "DT_1R11001_FRM101", "ITM")
    items = [r for r in meta if r.get("OBJ_ID") == "ITEM"]
    print(f"항목 {len(items)}개:")
    for r in items:
        print(f"  {str(r.get('ITM_ID')):<24} {r.get('ITM_NM')}  [{r.get('UNIT_NM','')}]")
    hit = [r for r in items if any(k in str(r.get("ITM_NM", ""))
                                   for k in ("수지", "흑자", "적자"))]
    print(f"\n→ '수지/흑자' 항목 {len(hit)}개")
    print("   1개 이상 → 무역흑자를 수입액에 붙인 것은 명백한 오매핑 (좌표 선택 문제)")
    print("   0개      → 이 표엔 무역수지가 없다 → 다른 표를 찾았어야 함 (표 선택 문제)")
except Exception as exc:
    print("메타 조회 실패:", exc)
    print("→ verified CSV 의 org_id 컬럼을 확인해 직접 넣어야 한다")
