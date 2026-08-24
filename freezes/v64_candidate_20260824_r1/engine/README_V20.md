# KOSIS hybrid v20 retrieval

이 번들은 v19 안전 게이트를 유지하면서 상류 표 검색과 좌표 다양성을 개선한다.

## 정책

- 새 `OUT_DIR`와 `run_manifest.json` 없이는 실행 산출물을 섞지 않는다.
- 코드 번들, semantic index, PostgreSQL snapshot, 입력 CSV, 검색 파라미터의 SHA-256을 잠근다.
- Stage A reranker 전에 PostgreSQL 수록주기를 적용해 알려진 월·연 불일치 표를 제거한다.
- 조사명·작성기관·통계분류의 토큰 일치를 표 재순위 점수에 반영한다.
- Stage A 표 후보를 Top-10으로 보존한다.
- 좌표 Top-3는 서로 다른 표에서 최소 한 좌표씩 먼저 보존한 뒤 남은 슬롯을 채운다.
- Local Top-3를 먼저 공식 KOSIS API로 검증한다.
- Local이 모두 `UNRESOLVED`일 때만 MCP Top-2를 fallback으로 검증한다.
- MCP도 PostgreSQL의 완전한 표·ITEM·전체 OBJ·주기·단위 검사를 통과한 후보만 API로 전달한다.
- 정확한 기간 범위, 단위, ITEM 의미가 확정되지 않으면 `VALUE_MISMATCH`를 내지 않는다.
- READY 52건 중 실제 좌표 골드 30건에 대해 table/ITEM/OBJ/full Top-1·3·5·10을 각각 계산한다.

## 실행 파일

- `write_kosis_run_manifest.py`: 재현성 지문 생성 및 동일 실행 재개 검사
- `run_kosis_coordinate_stage_a.py`: 주기 선필터와 조사명·기관·분류 표 점수
- `run_kosis_coordinate_stage_c.py`: 표 다양성 보장 좌표 Top-3
- `run_kosis_mcp_coordinate_top2.py`: PostgreSQL 완전성·주기·단위 필수 게이트
- `run_kosis_top5_verification.py`: Local-primary/MCP-fallback 검증
- `evaluate_coordinate_topk.py`: 실제 좌표 골드 Top-k 평가
- `tests/test_v19_safety.py`: 오판정 차단 및 fallback 계약 테스트

## v19 기준선

v19 후보와 종전 실제 자동 좌표 골드의 겹침은 10건이었다.

- table Top-1/3/5: 40% / 40% / 40%
- ITEM Top-1/3/5: 40% / 40% / 40%
- OBJ coordinate Top-1/3/5: 30% / 40% / 40%
- 기간 포함 full Top-1/3/5: 30% / 40% / 40%

v20에서는 별도 `ready52_actual_coordinate_gold_v20.csv` 30건을 사용하므로 종전 10건 결과와 직접 같은 분모로 비교하지 않는다.

## GPU 없는 상태에서 검증된 범위

- Python 구문 검사
- manifest 지문 로직
- partial branch merge
- MCP PostgreSQL preflight 계약
- Local actionable 시 MCP fallback 차단
- 미확정 `VALUE_MISMATCH` 차단
- 실제 좌표 골드 평가기

Stage A/B/C의 BGE-M3 전체 재검색은 Colab GPU에서 새 v20 `OUT_DIR`로 실행해야 하며 v19 체크포인트를 재사용하지 않는다.
