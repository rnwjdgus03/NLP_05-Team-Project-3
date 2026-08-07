# 저장소 파일 지도

- 최종 갱신: 2026-08-07
- 원칙: 실행 코드는 Git으로 관리하고, 재생성 가능한 실행 산출물은 로컬 `outputs/`에만 둔다.

## 빠른 시작

```powershell
python run_kosis_measurement_pipeline.py `
  --input hcx_v15.csv `
  --table-index data/reference/kosis_table_summary.csv `
  --retrieval-mode lexical `
  --verify
```

## 최상위 구조

| 경로 | 내용 |
|---|---|
| `*.py` | 현행 파이프라인과 서로 import하는 핵심 모듈·CLI |
| `data/reference/` | KOSIS 표·메타 기준 인덱스 |
| `data/gold/` | 잠긴 골드 CSV와 manifest |
| `data/shared_20260802/` | 현재 회귀 기준이 되는 최소 공유 산출물 |
| `data/archive/` | 현행 기준이 아닌 과거 입력·참고 데이터 |
| `scripts/gold/` | 자동 골드 생성기와 Excel 변환기 |
| `scripts/experiments/` | 현행 파이프라인 밖의 독립 실험 도구 |
| `scripts/archive/` | 완료된 실전1 자동화 스크립트 |
| `notebooks/` | 실행 가능한 Colab 노트북 |
| `notebooks/archive/cells/` | 과거 노트북에서 분리한 셀 단위 스크립트 |
| `docs/` | 현행 설계·실험·실행 문서 |
| `docs/archive/legacy_outputs/` | 과거 `outputs/`에서 보존한 Markdown 보고서 |
| `legacy/` | 실전1 완료 코드. 현행 경로에서 사용하지 않음 |
| `tests/` | 전체 회귀 테스트 |
| `outputs/gold/` | 사람이 검토할 최종 골드 Excel·요약 파일 |

`outputs/gold/`를 제외한 `outputs/` 하위는 로컬 실행 결과이며 Git에 커밋하지 않는다.

## 핵심 파이프라인

| 단계 | 파일 | 역할 |
|---|---|---|
| 기사 전처리 | `preprocess_news.py` | 기사 CSV를 문장 단위로 분리 |
| 주장 판정 | `is_claim_filter_hcx.py` | HCX로 수치 주장 후보 판정 |
| 측정값 추출 | `extract_hcx.py` | measurement 단위 구조화 |
| 입력 게이트 | `prepare_kosis_mapping_input.py` | KOSIS 매핑 대상 선별 |
| 표 검색 | `kosis_match_claims_to_index.py` | KOSIS 통계표 후보 검색 |
| 좌표 검색 | `kosis_chroma_hybrid_search.py` | ITEM·OBJ 좌표 후보 검색·정렬 |
| 좌표 검증 | `kosis_validate_mapping_candidates.py` | 공식 메타·기간·단위·API 검증 |
| 값 판정 | `kosis_verify_claim_values.py` | 실제값과 주장값 비교 |
| 전체 실행 | `run_contextual_news_kosis_pipeline.py` | 기사부터 measurement까지 실행 |
| 매핑 실행 | `run_kosis_measurement_pipeline.py` | measurement부터 검증까지 실행 |

## 주요 기준 데이터

| 파일 | 내용 |
|---|---|
| `data/reference/kosis_table_summary.csv` | KOSIS 통계표 107,138건 인덱스 |
| `data/reference/kosis_metadata_summary.csv` | 주요 표의 축·항목·단위 요약 |
| `data/seed_region_codes.csv` | 지역명 108개·6개 코드 체계 |
| `data/claims/kosis_mapping_codebook_v1.csv` | 지표→좌표 고정 코드북 |
| `data/gold/gold_measurement_merged.csv` | 과거 measurement 골드 원본 |
| `data/gold/mcp_auto_gold_200.csv` | 현재 200개 자동 골드 후보 |

## 산출물 정책

- 실행 중간 CSV·JSON·로그는 `outputs/<run-id>/`에 생성하고 커밋하지 않는다.
- 발표·검토용 Markdown 결과는 `docs/`에 둔다.
- 대용량 XLSX나 원본 응답은 필요할 때 GitHub Release 또는 외부 저장소로 배포한다.
- 골드셋은 CSV와 manifest를 `data/gold/`에 두고, 검토용 Excel은 `outputs/gold/`에 둔다.
- 비밀키는 `.env`에서만 읽고 절대 커밋하지 않는다.

## 현재 루트 파일을 바로 이동하지 않는 이유

핵심 Python 파일은 서로 최상위 모듈명으로 import하고 테스트도 같은 경로를 사용한다.
루트를 더 줄이려면 단순 이동이 아니라 `src/kosis_factchecker/` 패키지 전환이 필요하다.
그 작업은 별도 변경으로 진행하고 전체 테스트를 통과한 뒤 반영한다.
