# Verify KOSIS MCP connection

뉴스의 수치 주장을 구조화하고, KOSIS 통계표와 정확한 `ITEM·OBJ·기간` 좌표를 찾은 뒤 공식 API 값으로 검증하는 파이프라인이다. 이 `Poc` 브랜치는 2026-08-20 기준 v24b 코드와 잠금 평가 자료만 남긴 정리본이다.

## 현재 상태

- 최신 개발 버전: **v24b**
- 개발 좌표 골드 30건: Full Top-1 `15/30 (50.0%)`, Top-3 `20/30 (66.7%)`, Top-5 `22/30 (73.3%)`
- 동결 블라인드 31건: 표 Top-3 `16/31 (51.6%)`, Full Top-3/5/10 `8/31 (25.8%)`
- 블라인드 최종 값 확정: `0/31`
- 최신 회귀 테스트: 정리된 `Poc` 통합 기준 `230 passed` (v24 핵심 패키지 29개 포함)

개발 성능은 v23보다 개선됐지만 블라인드 일반화는 충분하지 않다. 특히 고용 표 recall, 기본 총계 OBJ, 월 범위 파서가 다음 수정 우선순위다. 상세 수치와 실패 원인은 [v24 실험 보고서](docs/results/V24_EXPERIMENT_REPORT.md)와 [v24b 블라인드 보고서](docs/results/V24B_BLIND_EVALUATION_REPORT.md)에 있다.

## 파이프라인

```text
뉴스 원문
  → 문장/문맥 보존 전처리
  → HCX-007 claim span 및 measurement 추출
  → 규칙 기반 1차 게이트: in_ready / READY·ENRICH·REJECT
  → Stage A: lexical + BGE-M3 dense + reranker 표 검색
  → Stage B: PostgreSQL 메타데이터로 ITEM·OBJ 좌표 조합
  → Stage C: 좌표 rerank, Top-3 + 검토용 Top-5
  → MCP/KOSIS Open API 실제값 조회
  → 최종 MATCH / MISMATCH / UNRESOLVED
```

`in_ready=Y`는 **입력 주장이 검색 가능한 형태인지** 보는 1차 규칙 게이트다. 하류의 `mapping_status=READY` 또는 후보 `candidate_status=READY`는 **통계표·ITEM·OBJ·단위 의미가 확정됐는지** 보는 2차 게이트다. 둘은 같은 READY가 아니다. API 호출 성공도 의미 일치를 보장하지 않으므로 최종 검증과 독립 골드 평가를 별도로 수행한다.

자세한 단계, 모델, 게이트 기준은 [아키텍처 문서](docs/ARCHITECTURE.md), 실제 명령은 [실행 가이드](docs/RUNBOOK.md)를 참고한다.

## 빠른 시작

Python 3.12 환경을 권장한다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

`.env`에는 필요한 범위에서 `CLOVA_API_KEY`, `KOSIS_API_KEY`, `KOSIS_POSTGRES_DSN`을 설정한다. 실제 키와 대용량 인덱스·DB·실행 산출물은 Git에 올리지 않는다.

테스트:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

1차 게이트만 재현하는 최소 명령:

```powershell
.\.venv\Scripts\python.exe prepare_kosis_mapping_input.py `
  --input outputs\run\05_hcx_measurements.csv `
  --output outputs\run\06_mapping_ready.csv `
  --enrich-output outputs\run\06_mapping_enrich.csv `
  --rejected-output outputs\run\06_mapping_reject.csv `
  --all-output outputs\run\06_in_ready_all.csv
```

GPU가 있으면 검색·rerank 단계에 `--device cuda`, CPU는 `--device cpu`를 사용한다. BGE-M3와 reranker는 CPU에서 매우 느릴 수 있으므로 전체 평가에는 GPU를 권장한다.

## 저장소 구조

```text
.
├─ preprocess_news.py / build_news_chunks.py
├─ detect_claim_spans_hcx.py / extract_hcx.py
├─ prepare_kosis_mapping_input.py
├─ run_kosis_coordinate_stage_a.py
├─ run_kosis_coordinate_stage_b.py
├─ run_kosis_coordinate_stage_c.py
├─ run_kosis_top5_verification.py
├─ kosis_*                         # 검색·메타·게이트·검증 모듈
├─ data/gold/                      # 개발용 잠금 골드와 manifest
├─ evaluation/blind_v24b/          # 재사용 금지 블라인드 감사셋
├─ experiments/v24/                # 채택/기각 A/B 및 요약 결과
├─ docs/                            # 아키텍처, 실행법, 인수인계, 결과
├─ schemas/                         # 좌표 handoff JSON schema
├─ sql/                             # PostgreSQL 메타데이터 schema
└─ tests/                           # 핵심 회귀 테스트
```

과거 `legacy/`, 실행 로그, 수백 개의 중간 `outputs/`, 구형 노트북과 중복 CSV는 제거했다. 필요한 과거 실험은 Git 이력 또는 `codex/repro-baseline-20260727` 브랜치에서 확인할 수 있다.

## 평가 자료 사용 원칙

- `data/gold/stratified_actual_coordinate_gold_v21.csv`: 개발 회귀평가용이다.
- `evaluation/blind_v24b/blind_official_release_coordinate_gold31_locked.csv`: v24b 블라인드 감사용이다.
- 블라인드 31건을 규칙 튜닝에 반복 사용하지 않는다.
- 수정은 개발셋에서만 회귀 확인하고, 다음 일반화 평가는 새로운 기사·새 표군으로 다시 잠근다.
- `READY` 수를 늘리는 것보다 잘못된 확정을 막는 것이 우선이다.

## 알려진 한계와 다음 작업

1. `YYYY.MM`, `YYYY-MM`, `YYYYMM` 월 범위를 동일하게 처리하도록 검증 파서를 수정한다.
2. Stage A에 대표 ITEM→표 lexical recall 채널을 추가해 고용 표 검색 누락을 줄인다.
3. 명시적 세부 대상이 없을 때 공식 `계·전체·총지수` OBJ를 안전하게 보존한다.
4. 개발 골드에서 회귀를 통과한 뒤 새 블라인드셋으로 한 번만 평가한다.

현재 체크포인트와 재개 순서는 [HANDOFF_20260820.md](docs/HANDOFF_20260820.md)에 정리돼 있다.
