# BGE-M3 Top-K 1·2·3·5 예비 비교

## 실험 입력

- 후보 파일: `hcx_extracted_handoff_100_v15_kosis_table_candidates.csv`
- 검색 방식: BGE-M3 dense retrieval + lexical RRF + BGE reranker
- 후보 measurement: 22개
- 후보 row: 110개(각 measurement Top-5)
- 평가 골드: `gold_measurement_v1_locked.csv`
- `gold_tbl_id` 라벨: 24개
- 후보가 생성된 gold measurement: 14개(58.3%)

## 결과

| 최종 후보 수 | 정답 포함 | 전체 gold recall | 후보 row |
|---:|---:|---:|---:|
| Top-1 | 4 / 24 | 16.7% | 22 |
| Top-2 | 5 / 24 | 20.8% | 44 |
| Top-3 | 5 / 24 | 20.8% | 66 |
| Top-5 | 5 / 24 | 20.8% | 110 |

## 해석

- Top-2는 Top-1보다 정답 통계표를 1개 더 포함했다.
- Top-3과 Top-5는 후보 row만 늘고 Top-2보다 추가 정답을 찾지 못했다.
- 따라서 현재 파일만 기준으로 보면 Top-2가 검색 성능과 후속 API 비용의 균형이 가장 좋다.
- 다만 이 후보 파일은 24개 gold 중 14개에만 후보가 존재하는 과거 산출물이다. 이 결과는 예비 비교이며 최종 모델 성능으로 사용하면 안 된다.

## 정식 재실험 조건

`gold_measurement_scopefix_kosis_ready.csv` 39건 전체에 대해 같은 인덱스와 모델로 후보를 다시 생성한다. Dense Top-50, reranker Top-20은 고정하고 최종 후보만 Top-1, Top-2, Top-3, Top-5로 누적 절단한다. 이후 각 후보 세트에 동일한 Mapping-end 검증을 적용해 TBL recall, READY coverage, ITEM/OBJ 정확도, verdict 정확도와 API 호출량을 함께 비교한다.
