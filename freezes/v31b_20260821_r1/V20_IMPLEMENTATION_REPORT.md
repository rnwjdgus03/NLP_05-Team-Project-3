# KOSIS hybrid v20 retrieval 개선 보고서

## 구현 완료

- Stage A cross-encoder 실행 전에 PostgreSQL 수록주기를 조회한다.
- 요청 주기가 명확하고 표의 알려진 주기가 다르면 reranker 입력에서 제외한다.
- 주기가 일치하는 표를 우선하고 주기 메타데이터가 없는 표는 후보 부족 시에만 보충한다.
- 조사명·작성기관·통계분류·indicator/item 일치 신호를 표 점수에 더한다.
- Stage A 최종 표 후보를 Top-3에서 Top-10으로 확장한다.
- 좌표 Top-3는 서로 다른 표의 1위 좌표를 먼저 선택하고 남는 슬롯만 전체 점수순으로 채운다.
- MCP 후보는 PostgreSQL 좌표 완전성, 정확한 주기, 기간 범위, 단위, ITEM 구조를 모두 통과해야 API 후보가 된다.
- 정확한 표·ITEM·OBJ·기간을 확인하지 못한 후보는 기존과 동일하게 `VALUE_MISMATCH`를 생성할 수 없다.

## 실제 좌표 골드

- READY 전체: 52건
- 실제 좌표 골드: 30건(57.69%)
- 기존 실제 MCP 좌표 재잠금: 11건
- 2026-08-19 KOSIS MCP 재조회로 신규 확정: 19건
- 표별 구성: SITC 무역 13건, ICT 월 반도체 3건, ICT 연 반도체 3건, 산업기술인력 9건, 소매판매 1건, 소비자물가 1건
- 공식 집계 좌표가 없거나 KOSIS 범위 밖인 READY는 골드에서 제외했다.

## v19 예측에 새 30건 골드를 적용한 기준선

| 수준 | Top-1 | Top-3 | Top-5 | Top-10 |
|---|---:|---:|---:|---:|
| 표 | 20.00% | 23.33% | 23.33% | 23.33% |
| ITEM | 20.00% | 23.33% | 23.33% | 23.33% |
| 좌표 | 13.33% | 20.00% | 20.00% | 20.00% |
| 좌표+기간 | 13.33% | 20.00% | 20.00% | 20.00% |

이 수치는 v20 재검색 결과가 아니라 v19 예측을 더 큰 골드 30건으로 다시 측정한 기준선이다.

## 검증

- Python compileall 통과
- 안전·주기·다양성·MCP 게이트 테스트 13개 통과
- Colab 노트북 JSON 검증 통과
- 실행 번들 ZIP 무결성 검사 통과
- 노트북은 새 v20 `RUN_ID`를 사용하고 bundle SHA, semantic index SHA, PostgreSQL snapshot ID, 입력 SHA, 검색 파라미터를 `run_manifest.json`에 기록한다.

## 다음 실행

1. `KOSIS_hybrid_GPU_v20_retrieval.ipynb`를 Colab GPU에서 연다.
2. `kosis_hybrid_gpu_bundle_v20_retrieval.zip`과 `06_in_ready_all_latest.csv`를 H0에서 업로드한다.
3. 기존 `kosis_postgres_meta_full_snapshot.zip`과 BGE-M3 index 3개 파일은 Drive에 둔다.
4. H0부터 H11까지 실행한다.
5. H11의 `coordinate_topk_actual_gold_summary.json`을 v19 기준선과 비교한다.

## 공식 좌표 출처

- KOSIS SITC에의한무역통계, 품목별 수출액 수입액: `360/DT_1R11001_FRM101`
- KOSIS ICT수출입통계, IT산업별/월별 수출 현황: `127/DT_092_115_2009_S023`
- KOSIS ICT실태조사, 수출 및 수입액: `127/DT_127005_005`
- KOSIS 산업기술인력수급실태조사, 산업별 현재인원: `115/DT_115_2012_AA001`
- KOSIS 소비자물가조사, 연도별 소비자물가 등락률: `101/DT_1J22041`
