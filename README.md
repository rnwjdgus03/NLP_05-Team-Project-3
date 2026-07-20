# NLP_05-Team-Project-3

AI 기반 뉴스 수치 주장 추출 및 KOSIS 사실검증 PoC입니다.

발표 이후 실전2에서는 전달받은 정제 문장 파일을 시작점으로 사용하지 않고, **뉴스 기사 원문 CSV부터 동일한 결과를 다시 생성하는 코드 기반 파이프라인**으로 전환했습니다.

## 팀 구성

- A팀: 조선일보 뉴스 데이터 기반 주장 추출
- B팀(김진성, 구정현): KOSIS 통계표 탐색, 메타 분석, claim 매핑 및 검증

두 영역은 `claim_id`와 측정값별 `claim_measurement_id`로 연결됩니다.

## 현행 파이프라인

```text
뉴스 기사 원문 데이터
↓
기사 본문 정제 및 문장 분리
↓
각 문장에 article_id / claim_id 부여
↓
정제 문장 CSV 생성
↓
HCX-007 is_claim 판정
↓
is_claim=True 문장만 measurement-first 구조화
↓
측정값별 claim_measurement_id 행 분리
↓
KOSIS 후보 선별
↓
코드북 / 메타 / API로 tbl_id, obj, itm, period, unit 확정
↓
actual_value 비교 및 verdict 생성
```

| 단계 | 스크립트 | 입력 → 출력 |
|---|---|---|
| 1. 기사 정제 | `preprocess_news.py` | 기사 원문 CSV → 정제 문장 CSV |
| 2. KOSIS 후보 1차 판정 | `is_claim_filter_hcx.py` | 정제 문장 → is_claim True/False |
| 3. 측정값 추출 | `extract_hcx.py` | is_claim=True → 측정값별 구조화 CSV |
| 4. 회귀 감사 | `measurement_regression.py` | 구 누락 표본 + 현행 결과 → PASS/REVIEW/FAIL |
| 5. KOSIS 매핑·검증 | `run_kosis_measurement_pipeline.py` | 구조화 CSV → 후보·메타·실제값·verdict CSV |

## 빠른 시작

### 설치

```powershell
git clone https://github.com/rnwjdgus03/NLP_05-Team-Project-3.git
cd NLP_05-Team-Project-3
pip install requests python-dotenv pytest
# 선택: 더 정교한 한국어 문장 분리
pip install kss
```

KOSIS 통계표 임베딩 검색과 리랭커를 사용할 때만 ML 의존성을 추가합니다.

```powershell
pip install -r requirements-ml.txt
```

기본 모델은 한국어를 포함한 다국어 검색을 지원하는 `BAAI/bge-m3`와
`BAAI/bge-reranker-v2-m3`입니다. 두 모델은 최초 실행 시 내려받으므로 GPU 환경을
권장합니다. 모델이 필요 없는 기존 규칙 검색은 계속 사용할 수 있습니다.

프로젝트 루트의 `.env`에 API 키를 설정합니다.

```text
CLOVA_API_KEY=발급받은_실제_키
KOSIS_API_KEY=발급받은_실제_키
```

`.env`는 Git에 커밋하지 않습니다. `kss`가 설치되어 있으면 전처리 단계에서 사용하고, 없으면 내장 정규식 문장 분리기를 사용합니다.

### 폴더 구조

```text
data/raw/           원본 기사 CSV
data/inputs/        전처리·HCX 입력 CSV(로컬 생성)
data/claims/        코드북과 기존 claim 기준 데이터
data/archive/       실전1 입력 및 과거 데이터
outputs/runs/       실전2 API 실행·감사 결과(로컬 생성)
outputs/archive/    회귀 기준 및 중단·롤백 산출물
outputs/bteam_*/    실전1 골드·홀드아웃·검증 결과
docs/               KOSIS 파라미터 가이드와 보고서
legacy/             실전1 완료 스크립트
tests/              현행 회귀 테스트
```

`data/inputs/*.csv`, `outputs/runs/*.csv`, `outputs/runs/*.json`은 `.gitignore` 대상입니다. 실행 코드는 루트에 두고, 재현에 필요한 코드·테스트·작은 회귀 기준만 Git으로 관리합니다.

## 실행 방법

아래 명령은 Windows PowerShell 기준입니다. HCX API를 전체 데이터에 호출하기 전에 `--limit 20`으로 먼저 확인합니다.

### 1. 기사 원문 전처리

```powershell
python preprocess_news.py `
  --input "data\raw\chosun_full.csv" `
  --output "data\inputs\news_sentences.csv" `
  --overwrite
```

`preprocess_news.py`는 다음 작업을 수행합니다.

- HTML, 바이라인, 입력·수정 시각, 댓글·추천·꼬리말 제거
- 한국어 문장 분리
- 기사별 `article_id` 생성: `A0001`
- 문장별 `claim_id` 생성: `A0001-C001`
- 이전·다음 문장 문맥 보존

본문·제목·날짜·URL 컬럼은 일반적인 한국어·영어 별칭으로 자동 인식합니다. 자동 인식이 안 되면 `--body-col`, `--title-col`, `--date-col`, `--url-col`로 지정합니다.

출력 컬럼은 다음과 같습니다.

```text
claim_id, article_id, title, date, url,
claim_text, prev_sentence, next_sentence
```

### 2. is_claim 1차 판정

```powershell
python is_claim_filter_hcx.py `
  --input "data\inputs\news_sentences.csv" `
  --output "outputs\runs\is_claim.csv" `
  --model HCX-007 `
  --limit 20
```

결과를 확인한 뒤 `--limit` 없이 같은 명령을 실행하면 완료된 `claim_id` 다음부터 이어받습니다. 추출 단계에는 True 행만 전달합니다.

```powershell
Import-Csv "outputs\runs\is_claim.csv" |
  Where-Object { $_.is_claim -eq "True" } |
  Export-Csv "data\inputs\is_claim_true.csv" -NoTypeInformation -Encoding UTF8
```

`is_claim=True`는 HCX v1.2의 **KOSIS 후보 1차 판정**이지 최종 매핑 가능 판정이 아닙니다. 실제 실행에서는 최저임금·육아휴직 급여 같은 정책값도 True로 들어올 수 있습니다. 따라서 3단계에서 측정값을 보존한 뒤 4단계의 `measurement_usage + claim_domain_scope` 조건으로 최종 KOSIS 후보를 다시 선별합니다.

### 3. measurement-first 구조화 추출

```powershell
python extract_hcx.py `
  --input "data\inputs\is_claim_true.csv" `
  --output "outputs\runs\hcx_extracted_v15.csv" `
  --model HCX-007
```

추출 순서는 다음과 같습니다.

1. 규칙으로 문장 안 숫자·단위 후보를 먼저 수집합니다.
2. HCX-007 Structured Outputs로 claim 의미와 measurements를 추출합니다.
3. 후보가 빠졌으면 HCX에 한 번 재요청합니다.
4. 그래도 빠진 후보는 `measurement_source=rule_fallback`, `needs_review=Y`로 보존합니다.
5. 측정값이 여러 개면 한 measurement당 한 행으로 분리합니다.
6. 각 measurement에 지표·품목·기간·주기를 따로 연결합니다.
7. 기사 날짜나 멀리 떨어진 배경 연도를 측정 기간으로 추정하지 않고, 문장 근거가 없는 기간은 `-`로 남깁니다.

예를 들어 아래 문장은 3행으로 분리됩니다.

```text
최저임금 시간당 1만30원  → 현재값 → 10030원
최저임금 시간당 9860원   → 이전값 → 9860원
1.7%                     → 증감률 → 1.7%
```

주요 measurement 컬럼은 다음과 같습니다.

```text
claim_measurement_id, measurement_text, measurement_usage,
measurement_role, value, unit, value_type,
direction, change_base, measurement_source,
measurement_indicator, measurement_item,
measurement_period, measurement_prd_se,
measurement_binding_source
```

`measurement_binding_source=hcx`는 HCX가 해당 측정값의 의미와 기간을 직접 연결했다는 뜻입니다. `claim_fallback` 또는 `rule_fallback`은 검토 대상으로 보존하되 KOSIS 자동매핑에는 넣지 않습니다.

`measurement_usage`는 다음 네 종류입니다.

- `KOSIS_VALUE`: KOSIS 통계값 후보
- `POLICY_VALUE`: 최저임금·급여·지원금 등 정책 기준값
- `CONDITION`: 나이·근로시간·소득기준 등 조건값
- `CONTEXT`: 기간·연속 개월 등 보조 문맥값

추출 CSV에는 `verifiable_kosis`와 `unverifiable_reason`을 저장하지 않습니다. KOSIS 검색 전에 검증 가능 여부를 단정하면 실제 통계표 탐색 결과와 순환 관계가 생기기 때문입니다.

### 4. KOSIS 매핑·검증

#### 통계표 임베딩 인덱스 최초 1회 생성

`kosis_table_summary.csv`가 바뀌지 않는 동안 인덱스는 다시 만들 필요가 없습니다.

```powershell
python kosis_build_embedding_index.py `
  --table-index "kosis_table_summary.csv" `
  --out-dir "data\indexes\kosis_bge_m3" `
  --embedding-model "BAAI/bge-m3" `
  --device cuda
```

현재 통계표 약 10만 건을 1024차원 float32로 저장하면 임베딩 행렬만 약 420 MiB입니다.
GPU가 없으면 `--device cpu`로 생성할 수 있지만 시간이 오래 걸립니다. 생성물은 로컬
캐시이므로 `data/indexes/` 아래에 저장하며 Git에는 커밋하지 않습니다.

Colab Pro+에서는 [`notebooks/kosis_bge_colab.ipynb`](notebooks/kosis_bge_colab.ipynb)를
순서대로 실행합니다. 인덱스는 Google Drive에 직접 저장되며, 세션이 끊겨도 같은 셀을
다시 실행하면 `progress.json`에 기록된 완료 행부터 재개합니다. 최종 산출물은 아래
세 파일입니다.

```text
embeddings.npy
tables.csv
manifest.json
```

`manifest.json`에는 사용 모델, 행 수, 차원, 원본 통계표 SHA-256이 기록됩니다. 현재
`kosis_table_summary.csv`와 해시나 행 수가 다르면 파이프라인은 오래된 인덱스를
사용하지 않고 재생성을 요구합니다.

#### 하이브리드 검색과 검증

```powershell
python run_kosis_measurement_pipeline.py `
  --input "outputs\runs\hcx_extracted_handoff_100_v15.csv" `
  --table-index "kosis_table_summary.csv" `
  --out-dir "outputs\runs\kosis_v2" `
  --retrieval-mode hybrid `
  --semantic-index "data\indexes\kosis_bge_m3" `
  --semantic-top-k 50 `
  --rerank-top-k 20
```

후보 검색 순서는 다음과 같습니다.

```text
measurement 입력 게이트
→ 기존 토큰·도메인 규칙 Top-K
→ BGE-M3 dense retrieval Top-K
→ reciprocal rank fusion으로 후보 합치기
→ BGE multilingual cross-encoder rerank
→ 상위 표 메타 API 조회
→ ITEM·OBJ·단위·기간 엄격 검증
→ READY만 실제값 API 호출
```

임베딩과 리랭커는 후보를 추천할 뿐 `READY`를 직접 결정하지 않습니다. 기존의 단위,
기간, 의미 유형, 모집단, 코드셋 안전장치가 최종 승인권을 가집니다. 후보 CSV에는
`retrieval_backend`, `lexical_score`, `semantic_score`, `reranker_score`,
`fusion_score`가 남아 순위 근거를 감사할 수 있습니다.

`--retrieval-mode auto`는 임베딩 인덱스가 있으면 하이브리드 검색을 사용하고, 없으면
기존 lexical 검색으로 실행합니다. `--retrieval-mode hybrid`는 인덱스나 ML 의존성이
없을 때 즉시 실패하므로 시연·평가 환경 확인에 적합합니다. `--no-reranker`를 주면
임베딩과 규칙 검색만 결합합니다.

현행 매핑 단계는 다음 조건을 만족하는 행만 KOSIS 후보로 사용합니다.

```text
measurement_usage == KOSIS_VALUE
and claim_domain_scope == 국내공식통계
and measurement_binding_source == hcx
and measurement_indicator/measurement_period/measurement_prd_se가 모두 존재
```

정책·조건·문맥 값, 해외 통계, 개별기업 값, 순위값, 이전값·참고값·목표값은 API 호출 전에 제외합니다. `canonical_unit`, `unit_dimension`, `semantic_type`, `entity_type`, `comparison_period`를 만든 뒤 KOSIS 입력으로 전달합니다.

통계표와 메타를 조회한 후보는 다음 세 상태로 나뉩니다.

- `READY`: 표·ITEM·OBJ·단위·기간이 확정되어 실제값 검증 가능
- `REVIEW`: 코드셋·계산식·후보 또는 모집단 확인 필요
- `REJECT`: 의미가 맞는 KOSIS ITEM 없음

실제값 API는 `READY`에만 호출합니다. 전체 과정을 확인한 뒤 같은 명령에 `--verify`를 추가합니다. 판단불가에는 `CODESET_REQUIRED`, `NO_COMPATIBLE_ITEM`, `FORMULA_REQUIRED` 같은 `verdict_code`와 단계별 이유를 남깁니다.

`--skip-meta`로 후보를 검토한 뒤 메타 단계만 이어갈 때는
`--reuse-table-candidates`를 사용합니다. 현재 READY measurement와 기존 후보 CSV의
ID 집합 및 1위 후보 수가 일치할 때만 재사용하며, 임베딩·리랭커 모델은 다시
로딩하지 않습니다.

`map_verify_kosis.py`와 `data/claims/kosis_mapping_codebook_v1.csv`는 이미 확정된 규칙의 오프라인 재현용으로 유지합니다. 코드북 밖 지표는 동적 통계표 인덱스와 메타를 사용합니다.

## 실전2 검증 결과

### 원문 전처리

| 항목 | 결과 |
|---|---:|
| 조선일보 원문 기사 | 2,706건 |
| 생성된 정제 문장 | 47,514건 |
| 본문이 비어 있던 기사 | 4건 |
| 사용 문장 분리기 | regex fallback |

### 수치 누락 회귀

v1.3에서 `value=-`였던 45개 claim을 고정 표본으로 다시 실행했습니다.

| 항목 | 결과 |
|---|---:|
| 회귀 claim | 45건 |
| 예상 / 실제 measurement | 92 / 92 |
| 다중 measurement 완전 분리 | 28 / 28 |
| 필수 필드 누락 | 0건 |
| 원문에 근거 없는 값 | 0건 |
| 예상 밖 값 | 0건 |
| rule fallback | 0건 |
| 최종 상태 | PASS 45 / REVIEW 0 / FAIL 0 |

### 정현님 전달 표본

현재 전달 파일은 `outputs/runs/hcx_extracted_handoff_100_v15.csv`입니다.

| 항목 | 결과 |
|---|---:|
| 전체 행 | 100행 |
| claim | 47건 |
| measurement 행 | 96행 |
| 측정값 없는 placeholder | 4행 |
| 필수 필드 누락 | 0건 |
| measurement ID 중복 | 0건 |
| 원문 근거 없는 measurement 기간 | 0건 |
| KOSIS_VALUE | 55행 |
| 기간 미확정 KOSIS_VALUE | 12행 |
| KOSIS 자동매핑 후보 | 22행, 10 claim |
| 현행 코드북 오프라인 매칭 | 1행, 1 claim |

정현님 측 매퍼도 `verifiable_kosis=Y`가 아니라 위의 measurement 단위 게이트로 입력을 선별해야 합니다. 기간이 문장에 없는 값은 임의로 기사 날짜를 넣지 않고 후보에서 제외합니다.

### 동적 KOSIS 재검증

`origin/feature/model`의 동적 목록·메타 조회 방식을 measurement-first 계약에 맞게 보강해 100행을 다시 실행했습니다.

| 단계 | 결과 |
|---|---:|
| 전체 입력 | 100행 |
| KOSIS 입력 게이트 통과 | 22행 |
| 표 후보 | 94행 |
| 실제 메타 조회 통계표 | 12개 |
| READY | 1행 |
| REVIEW | 17행 |
| REJECT | 4행 |
| 실제값 일치 | 1행 |
| 실제값 불일치 | 0행 |
| 사유가 명확한 판단불가 | 21행 |

판단불가 21행은 코드셋 필요 14, 의미가 맞는 ITEM 없음 4, 계산식 필요 1, 표 후보 모호 1, 모집단 정의 불일치 1입니다. 상세 감사는 `docs/kosis_model_logic_review.md`에 있습니다.

### 테스트

```powershell
pytest
```

현재 전체 테스트 결과는 `73 passed`입니다.

## 회귀 검증 재현

```powershell
python measurement_regression.py prepare `
  --baseline "outputs\archive\hcx_extracted_isclaim51.csv" `
  --output "data\inputs\measurement_regression_45.csv" `
  --expect-claims 45

python extract_hcx.py `
  --input "data\inputs\measurement_regression_45.csv" `
  --output "outputs\runs\measurement_regression_45_v15.csv" `
  --model HCX-007 `
  --overwrite

python measurement_regression.py audit `
  --baseline "outputs\archive\hcx_extracted_isclaim51.csv" `
  --candidate "outputs\runs\measurement_regression_45_v15.csv" `
  --report "outputs\runs\measurement_regression_45_audit.csv"
```

감사 결과는 claim별 `PASS`, `REVIEW`, `FAIL`과 후보 누락, 필수 필드 누락, 원문 밖 값, fallback 비율을 CSV와 JSON으로 남깁니다.

## 현재 한계와 다음 작업

1. 반도체·석유화학·바이오헬스·농수산식품·화장품과 LCC/대형 항공사 묶음 14행은 단일 OBJ가 아니라 코드셋 합산 규칙이 필요합니다.
2. 무역수지는 수출액-수입액 계산식을 추가해야 합니다.
3. 정비사 4행은 현재 후보 표에 의미가 맞는 ITEM이 없습니다. KOSIS 다른 표를 재탐색하고 없으면 국토교통부 등 다른 공식 출처 대상으로 분리합니다.
4. 기간이 문장에 없는 KOSIS_VALUE 12행은 계속 자동매핑에서 제외합니다.

## KOSIS 보조 도구

- `kosis_api_test.py`: KOSIS 목록·통계자료 API 기본 호출과 응답 파싱
- `prepare_kosis_mapping_input.py`: measurement 표준 단위·의미·기간 정규화 및 22행 입력 게이트
- `kosis_build_embedding_index.py`: BGE-M3 기반 KOSIS 통계표 dense index 최초 생성
- `kosis_semantic_search.py`: dense retrieval, RRF hybrid fusion, 다국어 cross-encoder rerank
- `kosis_match_claims_to_index.py`: measurement 중심 통계표·ITEM·OBJ 후보와 READY/REVIEW/REJECT 판정
- `kosis_build_meta_index.py`: 상위 통계표의 KOSIS 메타 long index 생성
- `kosis_verify_claim_values.py`: READY 후보 실제값 조회와 단계별 verdict code 생성
- `run_kosis_measurement_pipeline.py`: 준비·후보·메타·검증 통합 러너
- `kosis_table_search.py`: 로컬 통계표 인덱스 생성 및 후보 검색
- `kosis_metadata_summary.py`: 통계표의 분류축·항목·단위 메타 조회
- `llm_auto_mapping_prototype.py`: 코드북 밖 지표의 LLM 후보 선택 실험
- `kosis_codebook_v2.py`: 첫 홀드아웃 오류를 반영한 동결 코드북
- `kosis_codebook_v3.py`: 두 번째 홀드아웃 P0 오류를 반영한 개발 후보
- `build_kosis_holdout2_evaluation.py`: 독립 홀드아웃2 평가 재생성

KOSIS API 사용 시 주의사항은 다음과 같습니다.

- 목록 API의 상위 목록 파라미터는 실제 호출에서 `parentListId`를 사용합니다.
- 일부 응답은 표준 JSON이 아니므로 `kosis_api_test.py`의 파서를 사용합니다.
- 응답이 한 건이면 배열이 아니라 객체로 올 수 있어 리스트 정규화가 필요합니다.
- 실제값 호출 전에 메타 API로 분류축과 항목 코드를 확인합니다.
- 상세 파라미터는 `docs/kosis_param_guide.md`를 참고합니다.

## Legacy와 이력

실전1의 TF-IDF 후보 매칭, 수동 obj/item 보완, 골드·홀드아웃 평가 스크립트는 `legacy/`와 `outputs/bteam_*`에 보존합니다. 과거 산출물은 방법론 비교와 회귀 참고용이며, 현행 실행 순서는 이 README의 실전2 파이프라인을 기준으로 합니다.

상세 폴더 설명은 `docs/file_structure.md`, B팀 기존 파이프라인 기록은 `docs/docs_bteam_pipeline.md`, 선행 연구와 방법론은 `docs_참고문헌_방법론.md`를 참고합니다.

## 브랜치 전략

- `main`: 안정 버전
- `develop`: 통합 브랜치
- `feature/기능명`, `fix/버그명`: 기능·수정 브랜치

커밋 메시지는 `feat:`, `fix:`, `docs:`, `chore:` 등 Conventional Commits 형식을 사용합니다.
