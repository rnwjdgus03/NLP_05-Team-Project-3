# v31b locked blind evidence

`v31b_20260821_r1`을 동결한 뒤 처음 사용한 좌표 식별 가능 READY 주장 30건의 평가 근거입니다.

- `blind_input30.csv`: 평가 입력
- `blind_coordinate_gold30_locked.csv`: 잠금 좌표 골드
- `blind_gold_manifest.json`: 골드 생성·잠금 정보
- `pre_evaluation_prediction_manifest.json`: 골드 공개 전 예측 manifest
- `stage_a_table_recall_*`: 표 검색 결과
- `coordinate_topk_*`: ITEM·OBJ·Full Top-k 결과
- `blind_final_report.json`: 사전 등록 기준 통과 여부와 최종 안전성 요약

이 데이터는 재현·감사용이며 새 규칙 튜닝에 사용하지 않습니다. 다음 모델 변경은 별도 개발셋에서 수행하고 새로운 미사용 홀드아웃으로 평가해야 합니다.
