# 23. 해제로 회수된 READY 에 대해 실제값 검증 (verdict 산출)
#
# 기사일(date) 이 있어야 REVISION_VINTAGE_RISK 정책이 동작한다.
import pandas as pd

verify_in = pd.read_csv(f'{OUT}/verify_input_released.csv', dtype=str, keep_default_na=False)
ready_src = pd.read_csv(f'{RUN}/05_hcx_measurements_kosis_ready.csv',
                        dtype=str, keep_default_na=False)
if 'date' not in verify_in.columns and 'date' in ready_src.columns:
    verify_in = verify_in.merge(ready_src[['claim_measurement_id', 'date']],
                                on='claim_measurement_id', how='left')
verify_in.to_csv(f'{OUT}/verify_input_released.csv', index=False, encoding='utf-8-sig')
print(f"검증 대상 {len(verify_in)}건")

!python kosis_verify_claim_values.py \
  --input {OUT}/verify_input_released.csv \
  --output {OUT}/05_hcx_measurements_kosis_verified_released.csv \
  --delay 0.12

verified = pd.read_csv(f'{OUT}/05_hcx_measurements_kosis_verified_released.csv',
                       dtype=str, keep_default_na=False)
print("\nverdict 분포:")
print(verified['verdict'].value_counts().to_string())
print("\nverdict_code 분포:")
print(verified['verdict_code'].value_counts().to_string())

silver = pd.read_csv(f'{OUT}/silver_coordinates.csv', dtype=str, keep_default_na=False)
tier = dict(zip(silver['claim_measurement_id'], silver['tier']))
print("\n=== 건별 (실버와 대조) ===")
for _, r in verified.iterrows():
    t = tier.get(r['claim_measurement_id'], '(없음)')
    print(f"  {r['verdict']:<6} [{r['verdict_code']:<24}] 실버={t:<16} "
          f"{str(r.get('claim_text', ''))[:60]}")
print("\n※ 실버 SILVER_UNIQUE 인데 '불일치'가 나오면 둘 중 하나가 틀린 것 → 사람 확인")
