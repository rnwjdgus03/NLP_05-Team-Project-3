# v65 신규 blind100

v64 후보를 먼저 동결한 뒤, 개발셋 및 이전 블라인드와 분리된 table-disjoint 좌표 골드 100건으로 한 번만 평가했습니다.

| 지표 | Top-1 | Top-3 | Top-5 |
|---|---:|---:|---:|
| 표 | 35% | 50% | 59% |
| ITEM | 35% | 50% | 58% |
| 전체 좌표 | 32% | 45% | 54% |

- 예측 누락: 0건
- 사전 기준: ITEM Top-5 75%, 좌표 Top-5 70%
- 결과: `FAIL`
- 데이터 역할: `BLIND_EVALUATION_ONLY_NO_TUNING`
- 정책: 이 결과에서 v64 규칙·가중치·프롬프트를 추가 수정하지 않음

근거는 `one_shot_claim.json`, `blind_manifest.json`, `coordinate_topk_multigold_summary.json`, `blind100_gate.json`에 있습니다.