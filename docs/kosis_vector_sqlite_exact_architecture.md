# KOSIS 표 Vector Search + SQLite Exact Resolver 아키텍처

## 결정

좌표 전체를 ChromaDB에 임베딩하는 경로를 기본 후보에서 제외하고 다음 세 계층을 분리한다.

```text
HCX structured claim
  → KOSIS table lexical/BGE/reranker Top-N
  → SQLite ITEM/OBJ/period exact resolver
  → KOSIS Open API
  → MATCH / MISMATCH / 판단불가
```

기존 좌표 Chroma 경로는 회귀 A/B 비교를 위해 삭제하지 않는다.

## 계층별 책임

| 계층 | 책임 | 금지 사항 |
|---|---|---|
| 표 검색 | 주장과 관련된 KOSIS `tbl_id` 후보 생성 | ITEM·OBJ 최종 확정 |
| SQLite | 후보 표가 지원하는 ITEM·OBJ·주기 정확 조회 | API 성공을 의미 정답으로 간주 |
| 좌표 resolver | ITEM과 typed OBJ 축을 분리 선택 | target 미일치 좌표 READY 승격 |
| KOSIS API | 확정 좌표의 공식값 조회 | 좌표 의미 적합성 판단 |
| verdict | 기사값과 공식값의 유형별 비교 | 검색·좌표 선택 수행 |

## 새 파일

- `kosis_sqlite_metadata.py`: CSV 메타데이터를 누적 SQLite DB로 변환한다.
- `kosis_sqlite_resolver.py`: 표 Top-N 안에서 ITEM과 OBJ를 정확 조회·선택한다.
- `run_kosis_sqlite_exact_pipeline.py`: SQLite resolver와 KOSIS API 검증을 연결한다.
- `data/indexes/kosis_metadata.sqlite`: 현재 누적 메타데이터 DB다.

## SQLite 스키마

- `kosis_tables`: 기관·표·통계명·분류경로
- `kosis_items`: ITEM 코드·이름·단위·단위차원
- `kosis_axes`: OBJ 축 순서·축 ID·축 이름
- `kosis_axis_values`: OBJ 코드·이름·상위 코드
- `kosis_periodicities`: 표별 지원 수록주기
- `api_cache`: 요청 좌표·기간별 KOSIS 응답 캐시 공간
- `verified_mapping_cache`: 검증된 좌표 증거 캐시 공간
- `metadata_imports`: 원천 CSV SHA-256과 import 이력

## 현재 DB 상태

2026-08-11 현재 보유한 메타 CSV 8개를 누적한 결과다.

| 항목 | 건수 |
|---|---:|
| 통계표 | 107,138 |
| ITEM·OBJ 메타 확보 표 | 715 |
| ITEM | 2,366 |
| OBJ 축 | 1,336 |
| OBJ 값 | 60,745 |
| 수록주기 | 503 |
| DB 크기 | 약 47MB |

통계표 107,138개 모두 기본 정보가 있지만 ITEM·OBJ 메타는 지금까지 실제 조회한 표에만 존재한다.
새 실행에서는 BGE/Reranker Top-N 표의 메타를 기존 `kosis_build_meta_index.py`로 수집한 뒤 SQLite에 누적한다.

## 실행

기존 measurement runner에서 `sqlite` backend를 선택한다.

```powershell
python run_kosis_measurement_pipeline.py `
  --input outputs/run/05_hcx_measurements.csv `
  --table-index data/reference/kosis_table_summary.csv `
  --semantic-index data/indexes/kosis_bge_m3 `
  --retrieval-mode hybrid `
  --top-tables 10 `
  --top-rank-for-meta 10 `
  --coordinate-backend sqlite `
  --metadata-db data/indexes/kosis_metadata.sqlite `
  --out-dir outputs/run/07_mapping_sqlite
```

API와 값 검증까지 실행하려면 `--verify`를 추가한다.

## 출력

`<out-dir>/sqlite_exact/` 아래에 다음 파일을 생성한다.

- `01_sqlite_coordinate_candidates.csv`
- `02_sqlite_selected_coordinates.csv`
- `02_sqlite_resolution_failures.csv`
- `03_sqlite_api_validated.csv`
- `04_sqlite_value_verified.csv`
- `summary.json`

## 스모크 결과

holdout8 v7의 평가 measurement 97건과 표 후보 970행을 사용한 오프라인 스모크 결과다.

- 좌표 Chroma 사용: 없음
- SQLite 좌표 후보: 2,470행
- 최종 좌표 선택: 97행
- 메타 부족으로 선택 실패: 0행
- API 호출: 수행하지 않음

실제 `DT_1DA7001S` 메타에서 `남자 실업률`은 ITEM `T80(실업률)`과 OBJ `2(남자)`를 선택했고 typed OBJ strict match를 통과했다.

## 남은 제한

1. 정답 표가 BGE/Reranker Top-N에 없으면 SQLite가 복구할 수 없다.
2. HCX가 여자 측정값을 남자로 구조화하면 SQLite는 잘못된 구조화 target을 정확히 수행할 수 있다.
3. 현재 `api_cache`와 `verified_mapping_cache`는 스키마만 준비됐으며 실행기의 cache hit 경로는 후속 구현 대상이다.
4. 실제 좌표 골드 4건만으로 새 구조의 최종 성능을 확정할 수 없다.
5. 잠금 300건에서는 표 검색·ITEM·OBJ·기간·값 지표를 분리 평가해야 한다.
