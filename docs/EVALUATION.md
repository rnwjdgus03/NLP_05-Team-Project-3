# 최종 PoC 평가와 해석

## 지표 정의

- 표·ITEM Top-k: 정답 `tbl_id + ITEM`이 상위 k개 후보 안에 존재하는 주장 비율
- 전체 좌표 Top-k: 정답 표·ITEM·OBJ 좌표가 상위 k개 안에 존재하는 주장 비율
- MRR: 첫 정답 후보 순위의 역수 평균
- E2E 근거 선택률: KOSIS-ready 측정값 중 공식 근거가 선택된 비율

Top-k는 검색·좌표 매핑 지표입니다. 기사 전체 판정 정확도, 일반 뉴스 recall, 자동 검증률과 동일하지 않습니다.

## v60 개발 좌표 골드 300건

| 지표 | Top-1 | Top-3 | Top-5 | MRR |
|---|---:|---:|---:|---:|
| 표·ITEM | 157/300 (52.3%) | 209/300 (69.7%) | 232/300 (77.3%) | 0.613 |
| 전체 좌표 | 148/300 (49.3%) | 200/300 (66.7%) | 223/300 (74.3%) | 0.583 |

- 300개 모두 예측 패킷 존재
- 다중 정답 좌표 456행을 허용한 claim 단위 평가
- 사전 중단 기준 ITEM Top-5 75%, 좌표 Top-5 70% 통과
- 데이터 역할: `DEVELOPMENT_ONLY_NOT_BLIND`

## 실제 기사 개발 E2E 기준선

| 항목 | 결과 |
|---|---:|
| READY 측정값 | 60 |
| VERIFIED_MATCH | 6 |
| UNRESOLVED | 54 |
| MATCH 도달률 | 10.0% |
| MATCH가 나온 서로 다른 기사 | 5 |

`UNRESOLVED`는 오답이 아니라 자동 검증 보류입니다.

## v64 개발 600건 재대입

v64는 표가 분리된 개발 600건에 지도형 exact mapping cache를 만들고 같은 600건에 재대입 평가했습니다.

| 지표 | cache 적용 전 Top-5 | v64 재대입 Top-5 |
|---|---:|---:|
| ITEM | 64.7% | 90.3% |
| 전체 좌표 | 60.3% | 90.2% |

평가 모드는 `SUPERVISED_EXACT_MAPPING_CACHE_RESUBSTITUTION`입니다. 90%대 수치는 개발 재대입 결과이며 독립 일반화 성능이 아닙니다.

## v65 신규 blind100

v64를 먼저 동결한 뒤 개발셋 및 이전 블라인드와 분리된 table-disjoint 좌표 골드 100건을 한 번만 평가했습니다.

| 지표 | Top-1 | Top-3 | Top-5 | MRR |
|---|---:|---:|---:|---:|
| 표 | 35% | 50% | 59% | 0.429 |
| ITEM | 35% | 50% | 58% | 0.426 |
| 전체 좌표 | 32% | 45% | 54% | 0.392 |

- 예측 누락: 0건
- 사전 기준 ITEM Top-5 75%, 좌표 Top-5 70%: FAIL
- 데이터 역할: `BLIND_EVALUATION_ONLY_NO_TUNING`
- 평가 뒤 v64 규칙·가중치·프롬프트 수정: 없음

이 58%·54%가 최종 후보의 대표 일반화 검색 성능입니다.

## v66 잠금 조선일보 URL50 E2E

원본 `chosun_full.csv`에서 잠근 URL 50건을 v64 동결 엔진으로 처리했습니다.

| 항목 | 결과 | 기준 | 판정 |
|---|---:|---:|---|
| 기사 수집 성공률 | 50/50 (100%) | 90% 이상 | PASS |
| 작업 성공률 | 50/50 (100%) | 95% 이상 | PASS |
| 공식 근거 선택률 | 11/96 (11.46%) | 10% 이상 | PASS |
| 공식 근거 기사 | 5건 | 5건 이상 | PASS |
| 작업시간 p95 | 290.36초 | 600초 이하 | PASS |
| 엔진 정체성 | 단일 v64 SHA, 50건 | 단일 SHA | PASS |

추출 측정값은 393개, KOSIS-ready 측정값은 96개였습니다. 최종 판정은 `MATCH` 11개, `UNRESOLVED` 252개이며 `service_readiness.json`은 `PASS`, `promotion_allowed=true`입니다.

URL50 PASS는 URL 수집, 파이프라인 완주, 최소 공식 근거 커버리지, 지연시간, 동결 엔진 동일성 기준을 통과했다는 뜻입니다. 팩트체크 정확도 100%를 뜻하지 않습니다.

## 일반화 감사

- 최초 v33 blind100 실패 35건은 Stage A 20건, ITEM 11건, OBJ 4건으로 분류됐습니다.
- 후속 신규 blind100의 ITEM/좌표 Top-5는 71/68%, 65/64%, 56/50%, 73/70%, 최종 58/54%로 변동했습니다.
- 개발 600건의 cache 적용 전 성능은 ITEM 64.7%, 좌표 60.3%였습니다.
- 지도형 cache 재대입은 90%대로 상승했지만 최종 blind100은 목표에 미달했습니다.

따라서 PoC는 실제 서비스 흐름과 안전 게이트를 완성했지만 검색·좌표 일반화 목표를 달성한 모델로 주장하지 않습니다.

## 발표 시 반드시 지킬 해석

1. 77.3%·74.3%는 개발 300건, 90.3%·90.2%는 개발 600건 재대입이라고 표시합니다.
2. 대표 일반화 검색 성능은 v65 blind100 ITEM 58%, 좌표 54%입니다.
3. Top-k를 “팩트체크 정확도”라고 표현하지 않습니다.
4. v66 URL50 PASS는 서비스 준비도 기준 통과이지 정답률 100%가 아닙니다.
5. `UNRESOLVED`를 정답이나 오답으로 계산하지 않습니다.
6. 시스템의 강점은 높은 자동 판정률보다 공식 좌표 확인과 보수적 보류 정책입니다.

## 근거 파일

- `freezes/v64_candidate_20260824_r1/engine/freeze_manifest.json`
- `evaluation/v65_blind100/one_shot_claim.json`
- `evaluation/v65_blind100/blind_manifest.json`
- `evaluation/v65_blind100/coordinate_topk_multigold_summary.json`
- `evaluation/v65_blind100/blind100_gate.json`
- `evaluation/v66_locked_url50/qa_summary.json`
- `evaluation/v66_locked_url50/identity_audit.json`
- `evaluation/v66_locked_url50/funnel_audit.json`
- `evaluation/v66_locked_url50/service_readiness.json`
- `evaluation/generalization_audit/public_generalization_audit.json`