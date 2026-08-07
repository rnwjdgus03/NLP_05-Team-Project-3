# 19. 새 범위 게이트를 기존 177건에 적용해보기 (파이프라인 재실행 없이 dry-run)
#
# 검증 방법: 게이트가 막은 건이 실버 NO_MATCH 에 몰려 있어야 한다.
#   - NO_MATCH 를 잘 막으면  → 게이트가 제 일을 한 것
#   - SILVER_UNIQUE 를 막으면 → 오탐. 규칙을 좁혀야 한다 (이쪽이 더 나쁘다)
from collections import Counter

import pandas as pd

from kosis_scope_gate import gate_decision

ready = pd.read_csv(f'{RUN}/05_hcx_measurements_kosis_ready.csv',
                    dtype=str, keep_default_na=False)
decisions = pd.DataFrame([gate_decision(r) for r in ready.to_dict('records')])
ready = pd.concat([ready.reset_index(drop=True), decisions], axis=1)
ready.to_csv(f'{OUT}/scope_gate_dryrun.csv', index=False, encoding='utf-8-sig')

blocked = ready[ready['scope_gate_blocked'] == 'Y']
review = ready[ready['scope_gate_severity'] == 'REVIEW']
print(f"1차 READY {len(ready)}건")
print(f"  새 게이트가 차단: {len(blocked)} ({len(blocked)/max(len(ready),1):.1%})")
print(f"  사람 확인 필요:   {len(review)}")
print(f"  남는 건:          {len(ready) - len(blocked)}")
print("\n차단 사유별:")
print(Counter(blocked['scope_gate_code']).most_common())

# --- 검증: 실버 tier 와 교차 ---
try:
    silver = pd.read_csv(f'{OUT}/silver_coordinates.csv', dtype=str, keep_default_na=False)
    merged = ready.merge(silver[['claim_measurement_id', 'tier']],
                         on='claim_measurement_id', how='left')
    print("\n=== 실버 tier × 새 게이트 (핵심 검증) ===")
    print(pd.crosstab(merged['tier'].fillna('(없음)'),
                      merged['scope_gate_blocked']).to_string())

    wrong = merged[(merged['scope_gate_blocked'] == 'Y') &
                   (merged['tier'] == 'SILVER_UNIQUE')]
    print(f"\n오탐(값이 재현됐는데 차단): {len(wrong)}건  ← 0이어야 한다")
    for _, r in wrong.iterrows():
        print(f"  {r['claim_measurement_id']} [{r['scope_gate_code']}]")
        print(f"    {str(r['claim_text'])[:110]}")

    nomatch = merged[merged['tier'] == 'NO_MATCH']
    caught = (nomatch['scope_gate_blocked'] == 'Y').sum()
    print(f"\nNO_MATCH {len(nomatch)}건 중 게이트가 잡은 것: {caught} "
          f"({caught/max(len(nomatch),1):.1%})")
except FileNotFoundError:
    print("\n(silver_coordinates.csv 없음 — 교차 검증 건너뜀)")

print("\n=== 차단된 주장 표본 ===")
for _, r in blocked.head(20).iterrows():
    print(f"  [{r['scope_gate_code']}] {str(r['claim_text'])[:100]}")
    print(f"      근거: {r['scope_gate_reason'][:90]}")

print(f"\n저장: {OUT}/scope_gate_dryrun.csv")
