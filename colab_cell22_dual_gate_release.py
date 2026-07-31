# 22. 이중 게이트 해제 → 확정 집합에서 READY 재집계 (KOSIS API 호출 0회)
#
# 강등은 '검증 이후'에 일어나므로, 기존 validated.csv 에 판정 근거가 이미 다 들어 있다.
# 따라서 파이프라인을 다시 돌릴 필요 없이 규칙만 재적용하면 된다.
!python recover_downstream_validated.py \
  --validated {RUN}/05_hcx_measurements_kosis_validated_mappings.csv \
  --output {OUT}/05_hcx_measurements_kosis_validated_recovered.csv

# --- 확정 집합(134) 기준으로 해제 전/후 비교 ---
!python evaluate_chroma_hybrid_mapping.py --label A_baseline_v2_gate_released \
  --measurements {OUT}/evaluation_set_v2.csv \
  --candidates {RUN}/05_hcx_measurements_kosis_candidates_with_meta.csv \
  --validated {OUT}/05_hcx_measurements_kosis_validated_recovered.csv \
  --output {OUT}/eval_A_v2_released.json

import json
before = json.load(open(f'{OUT}/eval_A_v2.json', encoding='utf-8'))
after = json.load(open(f'{OUT}/eval_A_v2_released.json', encoding='utf-8'))
print("\n" + "=" * 56)
print(f"{'상태':<22}{'해제 전':>10}{'해제 후':>10}")
for key in ("READY", "PROVISIONAL", "NEEDS_CONFIRMATION", "MAPPING_FAILED"):
    print(f"  {key:<20}{before['mapping_status'][key]:>10}{after['mapping_status'][key]:>10}")
print(f"  {'API-valid':<20}{before['api_valid_measurements']:>10}"
      f"{after['api_valid_measurements']:>10}")

# --- 회수된 건이 정말 쓸 만한지: 실버 tier 로 교차 확인 ---
import pandas as pd
rec = pd.read_csv(f'{OUT}/05_hcx_measurements_kosis_validated_recovered.csv',
                  dtype=str, keep_default_na=False)
evalset = pd.read_csv(f'{OUT}/evaluation_set_v2.csv', dtype=str, keep_default_na=False)
silver = pd.read_csv(f'{OUT}/silver_coordinates.csv', dtype=str, keep_default_na=False)
tier = dict(zip(silver['claim_measurement_id'], silver['tier']))

ready = rec[(rec['mapping_status'] == 'READY') &
            (rec['claim_measurement_id'].isin(set(evalset['claim_measurement_id'])))]
ready = ready.drop_duplicates('claim_measurement_id')
print(f"\n확정 집합 내 READY: {len(ready)}건")
if len(ready):
    print("실버 tier 분포:")
    for t, n in ready['claim_measurement_id'].map(lambda m: tier.get(m, '(없음)')) \
                                             .value_counts().items():
        print(f"  {t}: {n}")
    print("\nREADY 목록:")
    for _, r in ready.iterrows():
        mark = tier.get(r['claim_measurement_id'], '(없음)')
        print(f"  [{mark:<16}] {r['tbl_id']:<22} {str(r.get('claim_text',''))[:70]}")

ready.to_csv(f'{OUT}/verify_input_released.csv', index=False, encoding='utf-8-sig')
print(f"\n검증 대상 저장: {OUT}/verify_input_released.csv")
