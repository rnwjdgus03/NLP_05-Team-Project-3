# v60 평가와 해석

## 지표 정의

- 표·ITEM Top-k: 정답 `tbl_id + ITEM`이 상위 k개 후보 안에 존재하는 주장 비율
- 전체 좌표 Top-k: 정답 표·ITEM·OBJ 좌표가 상위 k개 안에 존재하는 주장 비율
- MRR: 첫 정답 후보 순위의 역수 평균
- E2E 검증 커버리지: READY 주장 중 공식 근거로 자동 MATCH까지 도달한 비율

Top-k는 검색·좌표 매핑 지표입니다. 기사 전체 판정 정확도, recall, 자동 검증률과 동일하지 않습니다.

## v60 개발 좌표 골드 300건

| 지표 | Top-1 | Top-3 | Top-5 | MRR |
|---|---:|---:|---:|---:|
| 표·ITEM | 157/300 (52.3%) | 209/300 (69.7%) | 232/300 (77.3%) | 0.613 |
| 전체 좌표 | 148/300 (49.3%) | 200/300 (66.7%) | 223/300 (74.3%) | 0.583 |

- 300개 모두 예측 패킷 존재
- 다중 정답 좌표 456행을 허용한 claim 단위 평가
- 사전 중단 기준 ITEM Top-5 ≥75%, 좌표 Top-5 ≥70% 통과
- 데이터 역할: `DEVELOPMENT_ONLY_NOT_BLIND`

## 실제 기사 개발 E2E

| 항목 | 결과 |
|---|---:|
| READY 측정값 | 60 |
| VERIFIED_MATCH | 6 |
| UNRESOLVED | 54 |
| MATCH 도달률 | 10.0% |
| MATCH가 나온 서로 다른 기사 | 5 |

이 결과는 안전 게이트가 동작하지만 서비스 커버리지가 아직 낮다는 뜻입니다. `UNRESOLVED`는 오답이 아니라 자동 검증 보류입니다.

## 이전 v31b 기준선

저장소에는 READY 주장 30건 규모의 이전 소규모 블라인드 자료가 남아 있습니다. 이는 개발 과정의 기준선으로만 보존하며, 표본이 작고 좌표 식별 가능한 주장에 한정되어 v60의 대표 일반화 성능으로 사용하지 않습니다.

## 발표 시 반드시 지킬 해석

1. 77.3%와 74.3%는 `개발 300건 Top-5 적중률`이라고 말합니다.
2. 이를 “팩트체크 정확도 74%”라고 표현하지 않습니다.
3. 독립 블라인드 일반화는 개발 결과보다 낮을 수 있으며 후속 확대 평가가 필요하다고 밝힙니다.
4. URL 기반 실제 기사 E2E 결과가 최종 확정되기 전에는 중간 집계를 성능표에 넣지 않습니다.
5. 서비스의 장점은 높은 자동 판정률보다 공식 좌표 확인과 보수적 `UNRESOLVED` 정책입니다.

## 근거 파일

- `freezes/v60_service_candidate_20260824_r1/freeze_manifest.json`
- `freezes/v60_service_candidate_20260824_r1/evidence/dev300/coordinate_topk_multigold_summary.json`
- `freezes/v60_service_candidate_20260824_r1/evidence/dev300/regression_gate.json`
- `freezes/v60_service_candidate_20260824_r1/evidence/development_real_article/development_e2e_gate.json`
