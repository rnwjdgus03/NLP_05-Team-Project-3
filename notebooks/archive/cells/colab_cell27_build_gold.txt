# [31] 기존 근거를 골드 좌표로 굳히기 → recall 첫 실측
#
# 새 판단은 하지 않는다. 실버 값 재현 + 검증기 판정이라는 이미 있는 근거를 모으기만 한다.
!python build_gold_from_evidence.py \
  --silver {OUT}/silver_coordinates.csv \
  --verified {OUT}/05_hcx_measurements_kosis_verified_released.csv \
  --evaluation-set {OUT}/evaluation_set_v2.csv \
  --output {OUT}/gold_coordinates_v1.csv \
  --manifest {OUT}/gold_coordinates_v1_manifest.json

# 확정 등급(값까지 확인)만 평가에 쓴다. COORD_PLAUSIBLE 은 좌표 추정일 뿐이라 제외.
import pandas as pd

g = pd.read_csv(f'{OUT}/gold_coordinates_v1.csv', dtype=str, keep_default_na=False)
confirmed = g[g['gold_confirmed'] == 'Y']
confirmed.to_csv(f'{OUT}/gold_confirmed_v1.csv', index=False, encoding='utf-8-sig')
print(f"\n확정 골드 {len(confirmed)}건 / 전체 골드 {len(g)}건")
print(g['gold_grade'].value_counts().to_string())

GOLD = f'{OUT}/gold_confirmed_v1.csv'

!python evaluate_chroma_hybrid_mapping.py --label A_baseline_gold \
  --measurements {OUT}/evaluation_set_v2.csv \
  --candidates {RUN}/05_hcx_measurements_kosis_candidates_with_meta.csv \
  --validated {RUN}/05_hcx_measurements_kosis_validated_mappings.csv \
  --gold {GOLD} --output {OUT}/eval_A_gold.json

!python evaluate_chroma_hybrid_mapping.py --label C_chroma_hybrid_gold \
  --measurements {OUT}/evaluation_set_v2.csv \
  --candidates {OUT}/05_hcx_measurements_kosis_chroma_candidates.csv \
  --validated {OUT}/05_hcx_measurements_kosis_chroma_validated.csv \
  --gold {GOLD} --output {OUT}/eval_C_gold.json

import json


def pct(v):
    return f"{v * 100:.1f}%" if isinstance(v, (int, float)) else str(v)[:10]


print("\n" + "=" * 66)
print(f"{'':<22}{'table@1':>10}{'table@3':>10}{'table@5':>10}{'item@1':>10}{'obj@1':>10}")
for path, name in ((f'{OUT}/eval_A_gold.json', 'A_baseline'),
                   (f'{OUT}/eval_C_gold.json', 'C_chroma_hybrid')):
    d = json.load(open(path, encoding='utf-8'))
    t, i, o = d['table_recall'], d['item_recall'], d['obj_recall']
    print(f"  {name:<20}{pct(t.get('recall@1')):>10}{pct(t.get('recall@3')):>10}"
          f"{pct(t.get('recall@5')):>10}{pct(i.get('recall@1')):>10}{pct(o.get('recall@1')):>10}")
    print(f"  {'':<20}분모 {t.get('labeled')}건")

print("\n※ 이 골드는 '기사 숫자가 KOSIS와 맞은' 건에서 나왔다 → 참인 주장 쪽으로 편향.")
print("   타 팀(59건, keyword top-1 69.5%)과 직접 비교 금지 — 표 풀·입도·표본이 전부 다르다.")
