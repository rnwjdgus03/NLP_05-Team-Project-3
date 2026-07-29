# 문맥 보존형 뉴스-KOSIS 파이프라인

## 목표

기존 문장 단위 `is_claim` 단계에서 KOSIS 가능성까지 함께 판단해 유효한
주장을 일찍 버리는 문제를 줄인다. 앞단에서는 수치·통계 주장만 넓게
탐지하고, KOSIS 범위와 실제 매핑 가능성은 measurement 구조화 뒤에
판단한다.

```text
기사 원문
→ KSS 문장 분리
→ 기사별 5~8문장 중첩 chunk
→ 넓은 수치·통계 claim span 탐지
→ BGE-M3 Top-20 + reranker
→ Top-5 KOSIS 메타를 HCX 참고 정보로 제공
→ HCX measurement 구조화
→ READY / ENRICH / REJECT
→ hybrid BGE/lexical 매핑
→ ITEM / OBJ / 기간 확정
→ KOSIS API 실제값 검증
```

## 핵심 원칙

- span 탐지에서는 KOSIS 가능성을 판단하지 않는다.
- 제목, 기사 날짜, 앞뒤 문장, 원래 sentence ID를 끝까지 보존한다.
- KOSIS 검색 결과는 HCX의 용어 정규화 참고 정보일 뿐 기사 근거가 아니다.
- 기사에 없는 기간·값·단위를 후보 메타에서 복사하지 않는다.
- `mapping_eligible=Y`는 `mapping_gate=READY`와 같은 의미로 유지한다.
- 기간 누락, fallback binding, 단위 보정 가능 행은 `ENRICH`로 보존한다.
- 정책값, 개별기업, 해외통계처럼 명확한 범위 밖만 `REJECT`한다.

## 실행

먼저 `.env`에 `CLOVA_API_KEY`를 설정하고 BGE-M3 인덱스를 준비한다.
KOSIS 실제값까지 조회하려면 `KOSIS_API_KEY`도 설정한다.

Colab에서 10개 기사로 처음 확인할 때는
[`notebooks/contextual_news_kosis_smoke_colab.ipynb`](../notebooks/contextual_news_kosis_smoke_colab.ipynb)를
사용한다. 원문 CSV에서 숫자가 포함된 기사 10개를 고정 seed로 뽑고,
아래 단계별 산출물과 verdict 분포를 출력한다.

```powershell
python run_contextual_news_kosis_pipeline.py `
  --articles "data\raw\news_articles.csv" `
  --table-index "kosis_table_summary.csv" `
  --semantic-index "data\indexes\kosis_bge_m3" `
  --early-meta-index "outputs\runs\kosis_meta_full.csv" `
  --out-dir "outputs\runs\contextual_v1" `
  --device cuda `
  --verify
```

초기 소량 검증은 아래처럼 중단 지점을 지정한다.

```powershell
python run_contextual_news_kosis_pipeline.py `
  --articles "data\raw\news_articles.csv" `
  --table-index "kosis_table_summary.csv" `
  --semantic-index "data\indexes\kosis_bge_m3" `
  --out-dir "outputs\runs\contextual_smoke" `
  --article-limit 10 `
  --span-limit 10 `
  --measurement-limit 20 `
  --stop-after gate
```

`detect_claim_spans_hcx.py`, `kosis_early_retrieve.py`, `extract_hcx.py`는 기존
출력과 진행 파일을 읽어 이어받는다. 전체를 새로 시작할 때만 `--force`를
사용한다.

## 단계별 산출물

| 파일 | 의미 |
|---|---|
| `01_sentences.csv` | KSS 문장과 원문 문맥 |
| `02_chunks.csv` | 기사 경계를 넘지 않는 중첩 chunk |
| `03_claim_spans.csv` | KOSIS 판단 전 넓은 claim span |
| `03_claim_spans_progress.csv` | HCX chunk 처리 재개 정보 |
| `04_early_bge_candidates_top20.csv` | 조기 KOSIS 통계표 후보 |
| `04_early_bge_context_top5.csv` | HCX에 제공할 압축 후보 메타 |
| `05_hcx_measurements.csv` | 측정값별 구조화 결과 |
| `06_mapping_ready.csv` | 즉시 매핑 가능한 measurement |
| `06_mapping_enrich.csv` | 기간·scope·binding 보강 대상 |
| `06_mapping_reject.csv` | 명확한 KOSIS 범위 밖 |
| `07_mapping/` | 후보·메타·ITEM/OBJ·실제값 verdict |

## ENRICH 처리

`enrichment_actions`를 기준으로 보강 작업을 나눈다.

| action | 처리 |
|---|---|
| `RESOLVE_PERIOD_FROM_CONTEXT` | 제목·앞뒤 문장·기사 본문에서 시점 재탐색 |
| `CONFIRM_KOSIS_SCOPE` | 국내 공식 반복 통계인지 확인 |
| `CONFIRM_MEASUREMENT_BINDING` | fallback 값과 indicator/item 연결 재검토 |
| `NORMALIZE_UNIT` | 원, 명, 개사, 대 등의 KOSIS 단위 정규화 |
| `REPAIR_VALUE_TYPE_OR_UNIT` | 비율·증감률·수준값과 단위 충돌 교정 |
| `REEXTRACT_MEASUREMENT` | span은 있으나 measurement가 없는 행 재추출 |

ENRICH를 자동으로 READY로 승격하지 않는다. 보강 후 동일한
`prepare_kosis_mapping_input.py`를 다시 실행해 모든 READY 조건을 통과한
행만 매핑한다.
