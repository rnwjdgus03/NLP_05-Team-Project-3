# v24 기간 보존·표별 좌표 슬롯 실험 보고서

## 결론

- 채택: 복수 측정값의 개별 기간 보존
- 채택: Stage B에서 표별 최소 1개 검토용 좌표 보존
- 기각: Stage A 조사·기관·표 계열별 rerank pool 슬롯
- 잠금 좌표 골드 30건 최종 결합 성능: Full Top-1 15/30, Top-3 20/30, Top-5 22/30
- v23 대비: Full Top-1 13→15, Top-3 18→20, Top-5 19→22

## 실험 1: 개별 기간 보존

`A에서 B로` 형태의 문장에 포함된 첫 번째 측정값이 claim 대표 기간으로 덮이지 않도록 했다. 단, 비율·비중은 직접 수준값(`rate_level`)으로, 증가율·감소율·증감률은 직접 공표된 변화율(`rate_change`)로 구분한다.

- 입력 443행의 게이트 분포 유지: READY 55, ENRICH 46, REJECT 342
- 일반 구성비 주장은 기존처럼 `SHARE_CLAIM_UNSUPPORTED`로 차단
- 기간 복구 사례: `A0012-SPFEFB3037E3-m1`의 1.5%를 2023년이 아니라 2022년으로 보존
- 운영 안전장치: `prepare_kosis_mapping_input.py --expect-ready 55`

기간-only 대조군 결과는 Full Top-1 14/30, Top-3 19/30, Top-5 20/30, MRR 0.5456이다. v23의 Full Top-5 19/30에서 `A0012-SPFEFB3037E3-m1` 한 건을 단독으로 회복했다.

## 실험 2: Stage B 표별 좌표 보존

Stage A가 찾은 각 표에서 일반 OBJ 계층 게이트를 통과한 좌표가 하나도 없을 때, 역할 기반 하드 안전 게이트를 위반하지 않는 최상위 좌표 1개를 검토 전용 후보로 남긴다.

- 후보에 `table_slot_fallback=true`와 `verification_review_required=true` 기록
- fallback penalty를 적용해 정상 좌표보다 우선하지 않게 함
- Stage C에서 표 다양성을 유지한 뒤 Top-3와 제한적 Top-5를 구성
- PostgreSQL 완전성 및 최종 검증 게이트는 그대로 유지

## 최종 결합 회귀평가

| 지표 | v23 | v24 최종 | 변화 |
|---|---:|---:|---:|
| Full Top-1 | 13/30 (43.3%) | 15/30 (50.0%) | +2 |
| Full Top-3 | 18/30 (60.0%) | 20/30 (66.7%) | +2 |
| Full Top-5 | 19/30 (63.3%) | 22/30 (73.3%) | +3 |
| Full MRR | 0.5122 | 0.5817 | +0.0695 |

최종 결과는 기간까지 일치하는 `full`과 표·ITEM·OBJ 좌표인 `coordinate`가 모두 같은 22/30이다.

정책별 누적 효과는 다음과 같다.

| 구성 | Full Top-1 | Full Top-3 | Full Top-5 | MRR |
|---|---:|---:|---:|---:|
| v23 기준 | 13 | 18 | 19 | 0.5122 |
| 기간 보존만 | 14 | 19 | 20 | 0.5456 |
| 기간 보존 + Stage B 표별 슬롯 | 15 | 20 | 22 | 0.5817 |

Stage B 슬롯이 추가로 회복한 측정값은 `A0018-SP8114050F3A-m1`, `A0031-SP041EDC0971-m1`이다.

## 실험 3: Stage A 계열 슬롯

Stage A 잔여 실패를 대상으로 조사명·작성기관·표 계열별 rerank pool 슬롯을 적용했지만 채택하지 않았다.

| 설정 | Table Top-10 |
|---|---:|
| 기준 slots=0 | 23/30 |
| family slots=20 | 23/30 |
| family slots=40 | 22/30 |
| family slots=60 | 21/30 |
| survey groups=5, slots=60 | 19/30 |
| survey groups=10, slots=60 | 19/30 |
| survey groups=20, slots=60 | 21/30 |

계열 슬롯은 무개선 또는 회귀였으므로 운영 Stage A에는 반영하지 않았다. manifest에는 `stage_a_family_slots=0_REJECTED_BY_AB`로 기록한다.

## 잔여 실패

최종 Full Top-5 실패 8건은 Stage A 표 미검색 7건과 Stage B/C 하류 실패 1건으로 분리됐다.

- Stage A 7건: `A0006-SP270B11DBD0-m2`, `A0006-SP9282109973-m1`, `A0006-SP9282109973-m2`, `A0006-SP9461F3F4FE-m2`, `A0012-SP13E0E2E6EE-m2`, `A0012-SP13E0E2E6EE-m3`, `A0018-SP2F67F9842A-m1`
- Stage B/C 1건: `A0041-SP87530E5592-m3` — 정답 표는 Stage A 9위에 있었지만 최종 Top-5 좌표로 올라오지 못함

상세 목록은 `v24_experiments/server_audit/v24_residual_failures.csv`, 요약은 `v24_residual_failure_summary.json`에 저장했다.

## 운영 반영

- 서버 실행 ID: `hybrid_bge_m3_postgres_mcp_v24b_period_stage_b_slots_20260820`
- 실행 로그: `/home/ubuntu/kosis-project/runs/hybrid_bge_m3_postgres_mcp_v24b_period_stage_b_slots_20260820/pipeline.log`
- 중단된 READY 54 실행은 `..._partial_ready54_archived`로 이동해 보존
- 운영 반영 후 테스트: 29 passed
- 전체 파이프라인 완료 마커: `V21 COMPLETE`
