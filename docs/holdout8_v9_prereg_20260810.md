# Holdout8 v9 사전등록: 축 정렬·주기 필터·제한적 폴백

## 목적

v8 결과와 HCX measurement 체크포인트를 고정하고, 표·좌표 검색 단계만 변경해 실제 KOSIS 좌표 골드의 Top-k 성능을 측정한다.

## 고정 입력

- 기사 48건, measurement 769건, 평가 대상 97건은 v8과 동일하다.
- HCX-007 추출은 다시 호출하지 않고 체크포인트를 복사한다.
- 실제 좌표 골드 4건은 2026-08-10 KOSIS MCP의 search/table_info/validate/get_data 순서로 독립 조회했다.
- 대조용 주기 음성 골드 2건은 월 표와 연 표를 의도적으로 교차시킨다.

## v9 변경 사항

1. 성별·지역·국가·연령·품목 대상어는 해당 이름의 실제 OBJ 축에 일치하는 좌표를 우선한다.
2. 표 검색 후보를 자르기 전에 claim의 M/Q/Y 주기와 표의 수록주기를 비교해 알려진 불일치 표를 제거한다.
3. 정확 좌표가 빈 응답일 때만 OBJ를 하나씩 제거해 재조회하되, 회수된 결과는 `NEEDS_CONFIRMATION`으로 유지한다.
4. Top-5에서 기술적으로 실패한 measurement만 Top-10 좌표를 추가 검증한다.
5. 실제 좌표 골드로 표 Recall@1/5/10과 완전 좌표 Recall@1/5/10을 함께 기록한다.

## 성공 판단

- 주기 음성 골드가 검색 후보에 남지 않아야 한다.
- Top-10 API 호출은 Top-5 실패 건에만 발생해야 한다.
- OBJ 완화로 회수된 행은 자동 `READY`가 되면 안 된다.
- v8 실제 좌표 기준선인 표 Recall@5 25%, Recall@10 50%, 좌표 Recall@5/10 0%와 비교한다.
- 골드가 4건으로 작고 개발 홀드아웃을 사용했으므로 v9 수치는 최종 일반화 성능이 아니라 회귀 진단으로만 보고한다.

## 산출물

- `chroma_candidates_top5.csv`, `chroma_candidates_top10.csv`
- `two_stage_selected_top5.csv`, `two_stage_selected_top10.csv`
- `chroma_validated_top5.csv`, `top10_fallback_input.csv`, `top10_fallback_validated.csv`
- `chroma_validated_bounded_fallback.csv`
- `actual_coordinate_eval/summary.json`, `actual_coordinate_eval/coordinate_recall_metrics.csv`
- `period_negative_metrics.json`, `gpu_run_summary.json`
