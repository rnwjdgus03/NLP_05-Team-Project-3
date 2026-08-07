# 20. 평가 집합 확정(lock) → 그 위에서 A vs C 검색 재비교
#
# 1차 READY 177 건에는 KOSIS 로 검증 불가능한 주장이 섞여 있었다(실측).
# 범위 게이트가 REJECT 한 것만 빼고 집합을 잠근 뒤, 같은 후보/검증 결과를
# 새 집합으로 다시 집계한다. **파이프라인 재실행도 API 호출도 없다.**
!python lock_evaluation_set.py \
  --ready {RUN}/05_hcx_measurements_kosis_ready.csv \
  --output {OUT}/evaluation_set_v2.csv \
  --excluded-output {OUT}/evaluation_set_v2_excluded.csv \
  --manifest {OUT}/evaluation_set_v2_manifest.json \
  --silver {OUT}/silver_coordinates.csv

EVAL = f'{OUT}/evaluation_set_v2.csv'

# --- A/B/C 평가를 확정 집합으로 다시 ---
!python evaluate_chroma_hybrid_mapping.py --label A_baseline_v2 \
  --measurements {EVAL} \
  --candidates {RUN}/05_hcx_measurements_kosis_candidates_with_meta.csv \
  --validated {RUN}/05_hcx_measurements_kosis_validated_mappings.csv \
  --verified {RUN}/05_hcx_measurements_kosis_verified.csv \
  --output {OUT}/eval_A_v2.json

!python evaluate_chroma_hybrid_mapping.py --label C_chroma_hybrid_v2 \
  --measurements {EVAL} \
  --candidates {OUT}/05_hcx_measurements_kosis_chroma_candidates.csv \
  --validated {OUT}/05_hcx_measurements_kosis_chroma_validated.csv \
  --stats {OUT}/chroma_search_stats.csv \
  --output {OUT}/eval_C_v2.json

import json
print("\n" + "=" * 60)
for label in ("A", "C"):
    d = json.load(open(f'{OUT}/eval_{label}_v2.json', encoding='utf-8'))
    status = d.get("mapping_status")
    print(f"\n[{d['label']}] measurement {d['measurements']}")
    print(f"  후보 있는 measurement: {d['measurements_with_candidates']}")
    if isinstance(status, dict):
        print(f"  API-valid: {d['api_valid_measurements']} ({d['api_valid_ratio']:.1%})"
              f" | READY {status['READY']} | KOSIS 호출 {d['kosis_api_calls']}")
