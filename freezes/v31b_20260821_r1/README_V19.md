# KOSIS hybrid v19 clean

이 번들은 사용자 v16 실행에서 확인된 혼합 체크포인트와 MCP 오판정 문제를 막는다.

## 정책

- 새 `OUT_DIR`와 `run_manifest.json` 없이는 실행 산출물을 섞지 않는다.
- 코드 번들, semantic index, PostgreSQL snapshot, 입력 CSV, 검색 파라미터의 SHA-256을 잠근다.
- Local Top-3를 먼저 공식 KOSIS API로 검증한다.
- Local이 모두 `UNRESOLVED`일 때만 MCP Top-2를 fallback으로 검증한다.
- MCP도 Local과 동일하게 PostgreSQL의 표·ITEM·전체 OBJ·주기 검사를 통과해야 한다.
- 정확한 기간 범위, 단위, ITEM 의미가 확정되지 않으면 `VALUE_MISMATCH`를 내지 않는다.
- 실제 좌표 골드와 겹치는 표본에 대해 table/ITEM/OBJ/full Top-1·3·5를 각각 계산한다.

## 실행 파일

- `write_kosis_run_manifest.py`: 재현성 지문 생성 및 동일 실행 재개 검사
- `run_kosis_top5_verification.py`: Local-primary/MCP-fallback 검증
- `evaluate_coordinate_topk.py`: 실제 좌표 골드 Top-k 평가
- `tests/test_v19_safety.py`: 오판정 차단 및 fallback 계약 테스트

## 현재 로컬에서 측정한 v16 후보 회귀값

현재 후보와 실제 자동 좌표 골드의 겹침은 10건이다.

- table Top-1/3/5: 40% / 40% / 40%
- ITEM Top-1/3/5: 40% / 40% / 40%
- OBJ coordinate Top-1/3/5: 30% / 40% / 40%
- 기간 포함 full Top-1/3/5: 30% / 40% / 40%

표본이 10건뿐이고 일부 통계표는 동일 총계를 제공하는 대체표가 있으므로 이 수치는 최종 성능이 아니라 회귀 기준이다.

## GPU 없는 상태에서 검증된 범위

- Python 구문 검사
- manifest 지문 로직
- partial branch merge
- MCP PostgreSQL preflight 계약
- Local actionable 시 MCP fallback 차단
- 미확정 `VALUE_MISMATCH` 차단
- 실제 좌표 골드 평가기

Stage A/B/C의 BGE-M3 전체 재검색은 GPU가 확보되면 새 v19 `OUT_DIR`에서 실행해야 한다.
