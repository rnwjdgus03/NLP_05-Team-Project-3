# 15. 실버 좌표 위에서 A vs C 검색 재비교
#
# 분모가 SILVER_UNIQUE 로 확정된 measurement 로 줄어든다.
# 이 부분집합은 '기사 숫자가 KOSIS와 맞는' 쪽으로 편향돼 있으므로,
# 결과를 쓸 때 분모와 편향을 반드시 함께 적는다.
import pandas as pd

silver = pd.read_csv(f'{OUT}/silver_coordinates.csv', dtype=str, keep_default_na=False)
usable = silver[silver['tier'] == 'SILVER_UNIQUE']
print(f"실버 확정 {len(usable)}/{len(silver)} measurement")
print(silver['tier'].value_counts().to_string())

if len(usable) == 0:
    print("\n실버가 0건이라 비교할 수 없다. needs_human_review.csv 를 사람이 봐야 한다.")
else:
    gold_path = f'{OUT}/silver_as_gold.csv'
    usable.rename(columns={'silver_tbl_id': 'gold_tbl_id',
                           'silver_itm_id': 'gold_itm_id',
                           'silver_obj_l1': 'gold_obj_l1'})[
        ['claim_measurement_id', 'gold_tbl_id', 'gold_itm_id', 'gold_obj_l1']
    ].to_csv(gold_path, index=False, encoding='utf-8-sig')

    !python evaluate_chroma_hybrid_mapping.py --label A_baseline_silver \
      --measurements {RUN}/05_hcx_measurements_kosis_ready.csv \
      --candidates {RUN}/05_hcx_measurements_kosis_candidates_with_meta.csv \
      --validated {RUN}/05_hcx_measurements_kosis_validated_mappings.csv \
      --gold {gold_path} --output {OUT}/eval_A_silver.json

    !python evaluate_chroma_hybrid_mapping.py --label C_chroma_hybrid_silver \
      --measurements {RUN}/05_hcx_measurements_kosis_ready.csv \
      --candidates {OUT}/05_hcx_measurements_kosis_chroma_candidates.csv \
      --validated {OUT}/05_hcx_measurements_kosis_chroma_validated.csv \
      --stats {OUT}/chroma_search_stats.csv \
      --gold {gold_path} --output {OUT}/eval_C_silver.json

    import json
    for label in ('A', 'C'):
        d = json.load(open(f'{OUT}/eval_{label}_silver.json', encoding='utf-8'))
        print(f"\n[{d['label']}] 분모 {d['table_recall'].get('labeled')}건")
        for name in ('table_recall', 'item_recall', 'obj_recall'):
            print(f"  {name}: {d[name]}")

    print("\n[경고] 위 recall 의 분모는 '기사 숫자가 KOSIS와 맞은' measurement 뿐이다.")
    print("       A팀 골드가 오면 실버와 얼마나 일치했는지부터 대조할 것.")
