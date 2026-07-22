# 파일 지도 (file structure)

- 최종 갱신: 2026-07-21
- 목적: 루트에 py·csv가 많아 "뭐가 뭔지" 찾기 어려운 문제 해결. **역할별**로 묶어 한 줄 설명.
- 주의: 루트 py들은 서로 임포트하므로 **하위 폴더로 옮기면 임포트가 깨진다.** 코드 재배치는 골드 완료 후 codex와 조율해서 진행할 것.

---

## 빠른 시작 — 핵심 파이프라인 한 줄 실행

```
python run_kosis_measurement_pipeline.py --input hcx_v15.csv --table-index kosis_table_summary.csv --retrieval-mode lexical --verify
```

이 오케스트레이터가 아래 A의 ①~⑦을 순서대로 호출한다.

---

## A. 핵심 파이프라인 (뉴스 → 검증)

| 단계 | 파일 | 하는 일 |
|---|---|---|
| ① 전처리 | `preprocess_news.py` | 기사 CSV → 문장 단위 HCX 입력 CSV로 변환 |
| ② is_claim 필터 | `is_claim_filter_hcx.py` | 문장이 KOSIS 검증 가능한 수치 주장인지 True/False (HCX-007 + Structured Outputs) |
| ③ 추출 | `extract_hcx.py` | 문장을 measurement 단위로 구조화 (measurement-first v5 스키마) |
| ④ 게이트 | `prepare_kosis_mapping_input.py` | KOSIS 매핑 대상만 통과 (measurement-level 정제) |
| ⑤ 검색 | `kosis_match_claims_to_index.py` | claim ↔ KOSIS 표 후보 매칭. **현재 lexical(키워드) 채택** |
| ⑤ 검색엔진(미채택) | `kosis_semantic_search.py` | BGE-M3 밀집 검색 + 리랭킹. 골드 비교 결과 lexical에 열세 → 필수 경로 제외, 재현·재검토용 보존 |
| ⑥ 메타 | `kosis_build_meta_index.py` | 후보 표의 축·항목 코드(obj/itm)를 KOSIS getMeta로 수집 |
| ⑦ 검증 | `kosis_verify_claim_values.py` | KOSIS 실제값 조회 → 주장값 대조 → 일치/불일치/판정보류/판단불가 |
| 오케스트레이터 | `run_kosis_measurement_pipeline.py` | ④~⑦을 순서대로 실행하는 진입점 |

## B. KOSIS 유틸 · 인덱스 구축

| 파일 | 하는 일 |
|---|---|
| `kosis_api_test.py` | KOSIS Open API 호출 래퍼 (목록·메타·자료 3종) |
| `kosis_table_search.py` | 통계목록 API로 통계표 트리 크롤링 (107,138개 표 인덱스 생성) |
| `crawl_more_categories.py` | 기존 표 인덱스에 특정 카테고리 하위를 추가 크롤링 |
| `kosis_build_embedding_index.py` | BGE-M3/KURE 임베딩 인덱스 구축 (Colab GPU). **미채택** — 골드 비교에서 lexical에 열세, 재실험용으로만 유지 |
| `kosis_metadata_summary.py` | 후보 표들의 분류축·항목·단위를 조회해 요약 CSV로 정리 |
| `merge_table_summaries.py` | 팀원별로 나눠 크롤링한 table_summary들을 하나로 병합 |
| `merge_metadata_summaries.py` | 팀원별로 나눠 조회한 metadata_summary들을 병합 |
| `fetch_kosis_actual_values.py` | 매핑된 좌표로 KOSIS 실제값을 일괄 조회 (수동 검토용) |

## C. 코드북 매핑 (대안 경로 — 측정 파이프라인과 별개)

| 파일 | 하는 일 |
|---|---|
| `map_verify_kosis.py` | 코드북 CSV(규칙)로 매핑·검증. 임베딩 검색 대신 고정 규칙 사용 (정현님 경로) |
| `kosis_codebook_v2.py` | 1차 홀드아웃 감사로 만든 고정밀 코드북 v2 |
| `kosis_codebook_v3.py` | 홀드아웃2 P0 오류를 보정한 코드북 v3 후보 |
| `expand_kosis_codebook.py` | 검증된 코드북을 대량 행에 일괄 적용 |
| `llm_auto_mapping_prototype.py` | LLM 기반 자동 매핑 프로토타입 (HCX-007) |

## D. 골드 · 평가

| 파일 | 하는 일 |
|---|---|
| `make_gold_templates.py` | 골드 라벨 시트 템플릿 생성 (사람이 gold_ 컬럼만 채움) |
| `score_gold.py` | 골드 vs 파이프라인 채점 (단계별 정확도·recall@k) |
| `build_kosis_holdout2_evaluation.py` | 2차 독립 홀드아웃 골드 검증·공식 지표 재생성 |
| `measurement_regression.py` | measurement-first 추출 회귀 배치 준비·감사 |

## E. 후처리 · 패치 (개별 보정 애드온)

| 파일 | 하는 일 |
|---|---|
| `patch_month_periods.py` | 이미 추출된 CSV에 월 시점 복구를 소급 적용 (API 재호출 없음) |
| `flag_unit_traps.py` | 단위 함정(개월→개 등)을 규칙으로 플래그 (자동 수정 안 함, 검토 표시) |
| `resolve_codeset_claims.py` | 승인된 OBJ 코드셋을 다중 조회·합산해 CODESET_REQUIRED 재판정 (항공 묶음 등) |

## 두 경로 구분 (중요)

- **측정 파이프라인** (A): 검색으로 표를 자동으로 찾음 → **현재 lexical(키워드) 채택**. 임베딩(hybrid)은 골드 비교에서 열세라 미채택
- **코드북 매핑** (C): 사람이 고정한 규칙으로 매핑 → 정현님 주도, `map_verify_kosis.py`
- 둘은 독립 경로. 코드북은 확정 매핑을 축적하는 자산, 파이프라인은 미지 지표를 검색으로 처리.

---

## 주요 참조 데이터 (스크립트가 기본값으로 참조 — 이동 금지)

| 파일 | 내용 |
|---|---|
| `kosis_table_summary.csv` | KOSIS 통계표 전체 인덱스 (107,138행). 검색 대상 |
| `kosis_metadata_summary.csv` | 주요 표의 축·항목·단위 요약 (코드값은 없음) |
| `data/claims/kosis_mapping_codebook_v1.csv` | 코드북 (지표→좌표 규칙). map_verify가 읽음 |
| `hcx_v15.csv` / `hcx_v15_monthfix.csv` | v1.5 추출본 (114 measurement). monthfix는 월 시점 보정판 |
| `.env` | KOSIS/CLOVA API 키. **GitHub에 올리면 안 됨** |

---

## 폴더 개요

| 폴더 | 내용 |
|---|---|
| `data/` | 원천·중간 데이터 (`chosun_full.csv`=원천 기사 2,705, `data/claims/`, `data/archive/`) |
| `outputs/` | 실행 결과 (`outputs/runs/`, `outputs/gold/`, `outputs/bteam_*` 홀드아웃·검토) — 아래 상세 |
| `docs/` | 문서 (이 지도, 파이프라인 설명, 골드 스펙, 멘토 브리핑, KOSIS 파라미터 가이드) |
| `tests/` | pytest 테스트 (80개). `pytest` 한 줄로 실행 |
| `notebooks/` | `kosis_bge_colab.ipynb` — 임베딩 인덱스 구축용 Colab 노트북 |
| `legacy/` | 옛 regex 파이프라인·1회성 스크립트 보관 (현행 아님) |
| `logs/` | 작업 로그·트러블슈팅 기록 |

---

# 상세: data / outputs 하위 (결과물 이력)

## `data/`

- `chosun_full.csv`: A팀 원본 조선일보 기사 코퍼스 전체 (용량 문제로 `.gitignore`, 로컬에만 보관)

### `data/claims/`

A팀이 준 claim 데이터와 B팀 필터링 입력.

- `claim_df_with_metric_v2.csv`: 최신 원본 claim 데이터
- `claim_df_with_metric_v2_is_claim.csv`: `is_claim=True`만 필터링한 파일
- `claim_df_with_metric_v2_kosis_like.csv`: KOSIS 검토 우선 대상
- `kosis_mapping_codebook_v1.csv`: 코드북 (지표→좌표 규칙)

### `data/archive/`

현재 기준 아닌 예전 입력/참고 + v2 이전(v1, 422건 배치) 산출물.

- `kosis_table_summary_p2_b.csv`, `kosis_table_summary_a_d.csv`: 과거 부분 크롤링
- `kosis_metadata_summary_*.csv`: 팀원별 메타 요약
- `candidate_claim_articles.csv`, `claim_candidates_*.csv`: v1 배치 입력
- `table_claim_mapping_v1*.csv`: v1 배치 매칭 결과 (v2로 대체됨)

## `outputs/runs/`

측정 파이프라인 실행 산출물 (input 이름별로 생성). 예: `hcx_v15_monthfix_kosis_*.csv`
- `*_kosis_ready.csv` / `*_rejected.csv`: 게이트 통과/반려
- `*_kosis_table_candidates.csv`: 검색 후보
- `*_kosis_meta_index.csv`: 후보 표의 obj/itm 코드 상세
- `*_kosis_candidates_with_meta.csv`: 메타 해소된 최종 후보
- `*_kosis_verified.csv`: 최종 verdict

## `outputs/gold/`

- `gold_is_claim.csv`, `gold_measurement.csv`: 골드 라벨 시트 (사람이 gold_ 컬럼 채움)

## `outputs/bteam_review/`

B팀 KOSIS 매칭/검토 산출물 (2,001건 기준 이력).

- `bteam_kosis_review_enriched.csv`: target_number/unit/time_basis/verifiable 보강 입력
- `final_verified_enriched.csv` / `_summary.csv`: 원격 enriched 자동 실행 기준
- `final_verified_enriched_audited.csv`: 원격 + 로컬 엄격 감사 통합 2,001건
- `submission_integrated_*.csv`: 통합 감사 후 확정(21)/재검토(1,462)/판단불가(518)/수동복구(4)/요약
- `submission_integrated_bteam_status_report.md`: 현재 팀 공유·발표 기준 보고서

## `outputs/bteam_gold/`, `outputs/bteam_holdout/`

- `bteam_gold/`: 개발용 골드 100건, 코드북, 1,643건 확대 결과
- `bteam_holdout/`: 개발과 겹치지 않는 독립 홀드아웃 100건 + 최초 평가
- 독립 평가: 자동결정 구간 정확도 96.2%(25/26), 보류 포함 엄격 정확도 18.2%(6/33). 80% 게이트 통과 전엔 자동 확정 안 함.

## `outputs/bteam_holdout2/`

- `holdout2_100_selection.csv`: 골드100·홀드아웃100과 중복 없는 새 100건
- `holdout2_100_review.csv`: 동결 코드북 v2 예측 + 사람 확정 gold_ 기준
- `holdout2_100_evaluation.csv` / `_metrics*.csv` / `_error_analysis.csv` / `_improvement_backlog.csv`: 비교·지표·오류·개선 백로그
- `holdout2_100_report.md`, `B팀_KOSIS_독립홀드아웃2_평가.xlsx`: 발표용
- 결과: 자동결정 커버리지 35.0%, 결정구간 정확도 91.4%, 엄격 정확도 11.4%(4/35). 80% 게이트 실패로 1,281건 확대 보류.

## `outputs/archive/bteam_poc_20260714/`

초기 197건 PoC, 과거 표본 검증, 4,403건 검토 큐, enriched 통합 전 제출 파일 보존. 현재 기준 아님.

## `docs/` · `logs/`

- `docs/`: `docs_bteam_pipeline.md`(파이프라인 설명), `kosis_param_guide.md`(API 가이드), `골드라벨_스펙.md`, `멘토회의_브리핑_20260721.md`, `kosis_model_logic_review.md`, `templates/`
- `logs/`: `baseline_26-07-13.md`, `troubleshooting_26-07-13.md`
