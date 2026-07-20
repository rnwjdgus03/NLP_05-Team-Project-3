# NLP_05-Team-Project-3

AI 기반 뉴스 사실검증 시스템 (멋쟁이사자처럼 AI/NLP 5기 클라비 기업 프로젝트)

뉴스 기사 내 수치 기반 주장을 탐지하고, KOSIS(국가데이터처) 공식 통계와 비교하여 사실 여부를 검증하는 AI 시스템 PoC.

## 팀 구성

- **A팀 (2명)** — 조선일보 데이터셋(노션 페이지로 제공) 기반 뉴스 주장 추출
- **B팀 (2명, 김진성/구정현)** — KOSIS API 연동 + 통계표 구조 분석 + claim-통계표 매칭/검증

두 팀의 접점은 `claim_id` 기준으로 연결되는 주장↔통계표 매핑 스키마입니다.

## 폴더 구조

파일이 많아져서 폴더로 정리했습니다. 상세 설명은 [`docs/file_structure.md`](./docs/file_structure.md) 참고.

- 루트: 실행 스크립트(`*.py`), `kosis_table_summary.csv`(통계표 인덱스), `kosis_metadata_summary.csv`(메타 요약)
- `data/claims/`: A팀이 준 최신 claim 데이터 (v2)
- `data/archive/`: 더 이상 직접 작업하지 않는 예전 입력/산출물 (v1 배치 포함)
- `outputs/bteam_review/`: B팀 KOSIS 매칭/검토 산출물 (현재 작업 중인 파일들)
- `outputs/bteam_verification/`: 수동 판정, 표본 검증, 매핑 재검토 큐 산출물
- `outputs/bteam_gold/`: 100건 골드셋, 정확도 지표, 반복 지표 코드북, 1,643건 확대 배치, 337건 사유 분류
- `outputs/bteam_holdout/`: 개발용 골드와 중복 없는 독립 홀드아웃 100건, 동결 코드북 평가, 오류 분석, Excel 대시보드
- `docs/`: 파이프라인 설명, KOSIS API 파라미터 가이드, 템플릿
- `logs/`: 작업 기록, 트러블슈팅 로그

B팀 전체 파이프라인(입력 → 필터링 → 매칭 → 메타 확인 → 검증)에 대한 자세한 설명은 [`docs/docs_bteam_pipeline.md`](./docs/docs_bteam_pipeline.md)에 정리되어 있습니다.

## HCX 파이프라인 (실전2 · 현행 4단계)

발표 이후, 뉴스 정제부터 검증까지 전 구간을 **재현 가능한 코드로 재구성**한 현행 파이프라인입니다. 초기의 Claude 대화 기반 수작업은 재현성 문제로 전부 코드로 대체했습니다. 실행 순서대로:

| 단계 | 스크립트 | 역할 | 입력 → 출력 |
|---|---|---|---|
| ① 정제 | (은결님 정제 산출물 `뉴스_데이터_정제문장.csv`) | 노이즈 제거 + 문장 분리 + claim_id 부여 (규칙 기반 Python) | 기사 → 정제 문장 |
| ② is_claim | `is_claim_filter_hcx.py` | HCX-007 + Structured Outputs로 KOSIS 검증 가능 문장 판별 (프롬프트 v1.2) | 정제 문장 → is_claim True/False |
| ③ 추출 | `extract_hcx.py` | v3 스키마 43컬럼 구조화 추출 (게이트·지표·분류축·시점·수치), measurement 행 분리 (프롬프트 v1.2) | is_claim=True → claim 스키마 CSV |
| ④ 매핑·검증 | `map_verify_kosis.py` | 코드북(CSV)으로 tbl_id·obj·itm 매핑 → KOSIS 실값 조회 → 일치/불일치/판단불가 판정 | 추출 CSV → verdict CSV |

- 매핑 규칙은 코드가 아니라 **`data/claims/kosis_mapping_codebook_v1.csv`** 에 외부화되어 있어, 규칙 추가는 CSV에 행만 추가하면 됩니다(코드 수정 불필요).
- `llm_auto_mapping_prototype.py` = 코드북 밖 지표를 위한 LLM 후보 선택 프로토타입. `verify_claim_schema_v3_pilot.py` = ④의 구(舊) 하드코딩 버전(코드북 외부화로 대체됨).
- 각 스크립트는 `.env`의 `CLOVA_API_KEY`(HCX) 또는 `KOSIS_API_KEY`(KOSIS)를 사용하며, 중단 후 재실행 시 이어받기를 지원합니다.

### 파일 정리 규칙 (실전2 이후)

루트에 실행 스크립트·표본·결과·데이터가 뒤섞여 있어, 아래 규칙으로 정리합니다.

- **실행 스크립트(`*.py`)는 루트 유지**, 데이터·결과는 폴더로 분리.
- **입력 표본** `hcx_input_*.csv` → `data/inputs/` 로 이동 예정.
- **실행 결과** `hcx_extracted_*.csv`, `is_claim_2*.csv`, `my_mapped_*.csv` 등 → `outputs/runs/` 로 이동 예정.
- **원본 데이터** `뉴스_데이터_정제문장.csv` → `data/raw/`.
- **결과 파일 명명 규칙**: `{단계}_{표본}_{프롬프트버전}.csv` (예: `extract_hcx_input200_v12.csv`). 버전·표본이 파일명에 드러나야 신·구 실행이 섞이지 않습니다.
- 중단·롤백된 실행 결과(`is_claim_200.csv`, `hcx_extracted_200_v13.csv` 등)는 `outputs/archive/` 로 보존.

> 파일 이동은 팀원 명령어 습관·코드 내 경로에 영향을 주므로, 별도 정리 커밋으로 합의 후 일괄 반영합니다. 본 README는 그 규칙과 현행 파이프라인 카탈로그를 먼저 기록합니다.

### legacy/ — 실전1 산출 스크립트 (2026-07 정리)

루트를 정리하며, 실전1에서 사용하고 현재는 직접 실행하지 않는 스크립트 29개를 `legacy/`로 이동했습니다. 홀드아웃 평가(`build_kosis_holdout*`, `select_kosis_*`), 코드북 v2/v3(`kosis_codebook_v2/v3.py`), 구 매칭·검증(`match_claims_to_tables.py`, `verify_claim.py`, `fill_obj_itm*`) 등이 여기 속합니다.

- **루트에는 현행 HCX 파이프라인(4개) + KOSIS 공용 도구(`kosis_api_test.py` 등)만 남깁니다.**
- `kosis_api_test.py`는 여러 스크립트가 공유하는 공용 모듈이라 루트에 유지합니다. legacy 스크립트가 이를 import하는 경우, legacy는 이미 실행 완료된 산출물이라 재실행 시에만 경로 처리가 필요합니다(`sys.path`에 루트 추가).
- legacy 스크립트의 이력은 `git mv`로 이동해 보존됩니다.

## 참고: 방법론·참고문헌

`docs_참고문헌_방법론.md` — statistical claim verification 관련 선행 연구(FEVER, Scrutinizer, BLINK 등)와 추출·매칭 단계의 대안 방법론, 적용 로드맵 정리.

## 환경 설정

```bash
git clone https://github.com/rnwjdgus03/NLP_05-Team-Project-3.git
cd NLP_05-Team-Project-3
pip install requests python-dotenv
```

`.env.example`을 복사해서 `.env`를 만들고, 본인이 발급받은 KOSIS 인증키를 넣으세요.

```bash
cp .env.example .env
```

```
# .env
KOSIS_API_KEY=발급받은_실제_인증키
```

`.env`는 절대 커밋하지 마세요 (`.gitignore`에 이미 등록되어 있음).

## 스크립트 사용법

### `kosis_api_test.py` — KOSIS API 호출 기본 테스트

통계목록 API로 카테고리를 탐색하고, 통계자료 API로 실제 수치를 조회하는 예제입니다.

```bash
python kosis_api_test.py
```

### `kosis_table_search.py` — 후보 통계표 검색

통계목록 API에는 키워드 검색 기능이 없어서, 카테고리 트리를 재귀적으로 크롤링해 로컬 인덱스(`kosis_table_summary.csv`)를 만들고, 그 인덱스에서 키워드로 후보 통계표를 찾는 방식입니다.

```bash
python kosis_table_search.py
```

현재 `kosis_table_summary.csv`에는 30개 최상위 카테고리 크롤링 결과와 추가 병합분이 반영되어, 총 107,138개 통계표가 인덱싱되어 있습니다.

### `kosis_metadata_summary.py` — 표별 분류/항목/단위 조회

통계표설명(메타정보) API(`method=getMeta&type=ITM`)를 이용해, 실제 데이터를 조회하지 않고도 표의 분류 코드 전체 + 항목 코드 전체를 확인합니다.

```bash
python kosis_metadata_summary.py
```

### `match_claims_to_tables.py` — claim 후보 자동 매칭

A팀 claim 데이터(claim_id, claim_text 등 컬럼 포함 csv)를 읽어서, 각 주장마다 `kosis_table_summary.csv`에서 후보 통계표를 검색(TF-IDF 식 키워드 가중치)하고 메타정보 힌트까지 붙여 매핑 초안 csv를 생성합니다.

```bash
python match_claims_to_tables.py <입력.csv> <출력.csv>
```

완전 자동 검증은 아니고 1차 초안이라, 후보 표 중 실제로 맞는 표를 고르고 `org_id`/`tbl_id`/`obj_l1`/`itm_id`/`prd_se`는 KOSIS 메타 API로 직접 확인해서 채워야 합니다.

### `fill_obj_itm.py` — obj_l1/itm_id 자동 후보 채우기

`org_id`/`tbl_id`가 확정된 행에 대해 KOSIS 메타 API로 분류축/항목 코드를 조회해 자동으로 채우거나(단일 코드/합계 코드인 경우), 후보가 여러 개면 `obj_l1_candidates`/`itm_id_candidates` 컬럼에 후보 목록을 저장합니다. **반드시 KOSIS API 접속 가능한 로컬 환경에서 실행**해야 합니다.

### `verify_claim.py` — 최종 검증

`org_id`/`tbl_id`/`obj_l1`/`itm_id`/`prd_se`가 채워진 매핑 파일을 읽어 KOSIS 실제 값을 조회하고, 뉴스 claim과 비교해 일치/불일치/판단불가를 판정합니다.

```bash
python verify_claim.py --input <매핑.csv> --output verified_claims.csv
```

### `crawl_more_categories.py` / `merge_table_summaries.py` — 팀원과 나눠서 카테고리 크롤링

팀원이 동시에 다른 카테고리를 크롤링할 때는 같은 파일을 동시에 건드리면 git 충돌이 나므로, `--out`으로 각자 다른 파일에 저장한 뒤 병합합니다.

```bash
# 팀원 A: 인구/노동
python crawl_more_categories.py A D

# 팀원 B: 각자 다른 파일명으로
python crawl_more_categories.py --out kosis_table_summary_이름.csv P2 B

# 병합 (한 명이 최종적으로)
python merge_table_summaries.py kosis_table_summary.csv kosis_table_summary.csv kosis_table_summary_이름.csv
```

## 알아두면 좋은 KOSIS API 주의사항

- 개발가이드 문서엔 `parentId`라고 나오지만, 실제로는 `parentListId` 파라미터여야 동작합니다.
- `format=json`이라 해도 응답이 표준 JSON이 아니라 key에 따옴표가 없는 형식이라, 그냥 `res.json()`을 쓰면 에러가 납니다. `kosis_api_test.py`의 `_parse_kosis_json()`으로 전처리해서 씁니다.
- 응답이 1건뿐이면 배열이 아니라 객체 하나로 오는 경우가 있어, 항상 리스트로 감싸는 처리가 필요합니다.
- 통계표설명(메타정보) API로 실제 데이터 없이 분류/항목 코드를 먼저 확인할 수 있습니다 (`method=getMeta&type=ITM`).
- 파라미터 상세 내용은 [`docs/kosis_param_guide.md`](./docs/kosis_param_guide.md) 참고.

## 현재 진행 상황 (2026.07.14 기준)

- **KOSIS 인덱스/메타 조회**: 107,138개 통계표 인덱싱 완료(최신 병합본 기준), 메타정보 조회 스크립트 완료.
- **A팀 데이터**: 조선일보 원본 코퍼스(2,706건) → `claim_df_with_metric_v2.csv`(20,486건, 문장 단위)로 가공 완료. `is_claim`(실제 검증 대상 여부)과 `population`(대상 집단) 필드가 추가되어, `is_claim=True` 7,385건 확보.
- **B팀 1차 필터링/매칭**: `is_claim=True` 중 KOSIS 검증 가능성이 낮은 metric(날짜·시간/증시지표/기업실적/정책·제도/환율/인명피해)을 제외한 6,404건을 KOSIS 매칭 대상으로 확정.
  - 이 중 2,001건은 `tbl_id`까지, 1,998건은 `obj_l1`/`itm_id`까지 자동/반자동으로 채워짐 (`outputs/bteam_review/bteam_kosis_review_filled.csv`). 주요 ID가 채워졌다는 뜻이며, 통계표와 주장의 의미가 최종 확인됐다는 뜻은 아니다.
  - 남은 3건은 KOSIS 메타데이터를 수동 확인한 결과 선택 통계표의 지표·단위·분류축이 claim과 달라 `판단불가`로 기록했다.
  - 나머지 4,403건은 우선순위 큐로 정리했다. P0 139건(주요 ID 완성), P2 58건(후보 선택 필요), P4 4,206건(기관·통계표부터 재선택)이다.
- **v1 배치(초기 422건, `claim_candidates.csv` 기반)**: TF-IDF 키워드 매칭으로 초안 생성 후 김진성/구정현 반반 검토, 김진성 몫 42건 수동 obj_l1/itm_id 선택 완료. v2 파이프라인으로 대체되어 `data/archive/`에 보관 중.
- **verify_claim.py**: 골격 완성, `CHANGE_RATE`/`LEVEL`/`ABS_TO_ABS` 판정 로직 구현됨. `obj_l1`/`itm_id`/`prd_se`가 채워진 매핑에 대해 실제 KOSIS 값 조회 후 일치/불일치 판정 가능.
  - 대표 검증 배치 197건 실행 완료(verified_claims.csv: 일치 5건, 불일치 131건, 판단불가 61건). 실전1 범위에서는 부가 성과로 기록.
  - 1,998건 확대 전 품질 확인용 표본 24건을 실행했다. KOSIS 값 조회 성공 14건/실패·미매칭 10건, 자동 판정은 일치 1건/불일치 13건/판단불가 10건이었다.
  - 표본에서 세율·설문·수출 claim이 무관한 표와 연결되는 등 의미 오매핑이 확인되어 1,998건 전체 실행은 보류했다. 기간이 없을 때 최신값으로 대체하던 동작도 제거했다.
  - 원격의 2,001건 자동 실행 결과는 진단 자료로 병합했다. 기존 자동 일치 70건을 정확한 시점 로직으로 재실행한 결과는 일치 35건/불일치 26건/판단불가 9건이다.
  - 일치 후보 33건을 KOSIS 메타데이터와 실제값으로 수동 대조한 결과, 확정 일치 15건/재매핑 필요 8건/KOSIS 직접검증 불가 10건으로 판정했다.
  - 재매핑 필요 8건을 다시 조회해 6건을 확정 일치로 전환했다. 동남아 수출 1건은 KOSIS 집계코드가 없고, 가공식품 기여도 1건은 상승률만 확인되고 기여도 표가 없어 판단불가로 분리했다.
  - 원격 enriched 통합 전 로컬 엄격 감사 상태는 확정 일치 21건/재검토 1,643건/판단불가 337건이다. 상세 근거는 `outputs/bteam_review/submission_recheck_8_report.md`에 기록했다.
  - 물가·고용·무역·인구·소매 각 20건으로 개발용 골드셋 100건을 만들고, 기존 정확시점 불일치 22건을 전부 포함해 사람이 검증 가능 여부·통계표·항목·시점·최종 판정을 확정했다.
  - 기존 시스템 기준 성능은 검증 가능 여부 61.0%, 통계표 60.8%, 항목 47.1%, 시점 58.8%, 항목·시점 결합 41.2%, 최종 판정 43.0%였다. API 기술 성공률 94.1%만으로는 의미 매핑 품질을 보장할 수 없음을 확인했다.
  - 수동 확정 코드북으로 직접 검증 가능한 51건을 재조회해 51/51 API 성공을 확인했다. 이 수치는 개발용 골드셋의 확정 매핑 완성도이며 독립 자동 정확도가 아니다.
  - 코드북을 재검토 1,643건에 200건 단위 9개 배치로 적용했다. 엄격 규칙을 통과한 자동조회 후보는 33건이고, API 판정 완료 30건은 일치 28건/불일치 2건이다. 최신 출생 통계 3건은 값 미제공으로 재검토를 유지했다.
  - 나머지 재검토 건은 수동검토 유지 1,281건, 비검증 사유 분류 329건이다. 기존 판단불가 337건은 KOSIS 미제공 273건/정보 부족 32건/지역·분류 불일치 31건/기여도 미제공 1건으로 분류했다.
  - 전체 결과와 근거는 `outputs/bteam_gold/B팀_KOSIS_골드셋_및_확대검증.xlsx` 및 `outputs/bteam_gold/gold100_report.md`, `outputs/bteam_gold/expansion_report.md`에 정리했다.
  - 개발용 골드와 `claim_id`·`article_id`가 모두 겹치지 않는 독립 홀드아웃 100건을 물가·고용·무역·인구·소매 각 20건으로 만들었다. 수동 골드는 검증 가능 33건, 검증 불가 67건이다.
  - 기존 코드북을 수정하지 않고 평가한 결과 자동 결정 커버리지는 26.0%(26/100), 자동 결정 구간 정확도는 96.2%(25/26)였다. 자동으로 검증 가능하다고 매핑한 6건의 통계표·항목·시점 정밀도는 100.0%였다.
  - 보류를 오답으로 포함한 항목·시점 결합 엄격 정확도는 18.2%(6/33)로 80% 품질 게이트에 실패했다. 골드 매핑 API 성공률은 87.9%(29/33)이며, 최신 출생 시점 4건은 현재 선택 표에서 조회되지 않았다.
  - 오류는 검증 가능 보류 26건, 검증 불가 보류 48건, 검증 가능 대상을 검증 불가로 과배제한 1건(`C20191`)으로 나뉜다. 결과와 근거는 `outputs/bteam_holdout/B팀_KOSIS_독립홀드아웃_평가.xlsx`와 `holdout100_report.md`에 정리했다.
  - `fetch_kosis_actual_values.py`는 품목성질별 CPI처럼 분류축이 여러 개인 표를 위해 `obj_l2`~`obj_l8`을 KOSIS `objL2`~`objL8` 파라미터로 전달한다.
- **원격 enriched + 로컬 감사 통합**:
  - 원격 `final_verified_enriched.csv` 2,001건을 새 기준 입력으로 채택했다.
  - 원격 자동 수치 일치 117건은 확정 결과가 아니라 감사 후보로 재분류했다. 로컬 감사와 대조한 결과 수동 확정 17건/재검토 83건/판단불가 17건이다.
  - 원격 후보에서 빠진 로컬 수동 확정 4건(`C00381`, `C02892`, `C15304`, `C20235`)을 근거 재확인 후 복원했다.
  - 현재 통합 기준은 검증완료 21건/재검토 1,462건/판단불가 518건이다.
  - 전체 기준 파일은 `outputs/bteam_review/final_verified_enriched_audited.csv`, 팀 공유 보고서는 `outputs/bteam_review/submission_integrated_bteam_status_report.md`다.
  - 초기 197건 PoC와 과거 표본·제출 파일은 `outputs/archive/bteam_poc_20260714/`에 보존한다.
- **코드북 v2 개발 및 두 번째 독립 평가**:
  - 첫 홀드아웃 오류를 개발 자료로 전환해 `%포인트` 고용률, 총수출 전년동월비, 소비자·근원·생활·가공식품 물가, 월·분기 소매판매, 월별 혼인·출생 규칙을 보강했다.
  - 개발셋 재평가에서 자동결정 커버리지 51.0%, 결정구간 정확도 100.0%, 항목·시점 결합 엄격 정확도 84.8%(28/33), 자동매핑 정밀도 100.0%(28/28), API 성공률 89.3%(25/28)를 확인했다.
  - 이 수치는 기존 홀드아웃을 보고 수정한 개발 성능이며 독립 품질 게이트 통과로 보고하지 않는다.
  - 골드100과 첫 홀드아웃100의 claim_id·article_id 중복이 없는 새 표본 100건을 만들었다. 2,001건 기준 53건과 후속 4,403건 큐 47건으로 구성했다.
  - 동결 코드북 v2의 새 표본 자동 결과는 검증가능 6건(API 6/6 성공), 검증불가 29건, 보류 65건이다.
  - 사람 골드는 100/100건 확정했으며 검증가능 35건, 검증불가 65건(KOSIS 미제공 52건/정보 부족 13건)이다. 검증가능 claim의 최종 판정은 일치 31건/불일치 4건이다.
  - 검증 가능 여부는 자동결정 35건 중 32건이 맞아 결정구간 정확도 91.4%지만, 보류를 오답으로 포함한 엄격 정확도는 32.0%다.
  - 검증가능 35건 중 표·항목·시점을 모두 맞힌 것은 4건(11.4%)이고 자동 검증가능 6건의 완전 매핑 정밀도는 66.7%(4/6)다. API 성공률 100%(6/6)는 기술 연결 성능이며 의미 매핑 정확도와 다르다.
  - 독립 80% 품질 게이트는 실패했다. 오류는 검증가능 과배제 1건(`C12152`), 검증불가 과매핑 2건(`C20289`, `C14971`), 검증가능 보류 30건이다.
  - 공식 결과는 `outputs/bteam_holdout2/holdout2_100_report.md`와 `outputs/bteam_holdout2/B팀_KOSIS_독립홀드아웃2_평가.xlsx`에 정리했다.
- **코드북 v3 후보 착수**:
  - 독립 평가 재현용 `kosis_codebook_v2.py`는 동결하고 `kosis_codebook_v3.py`에서 P0 규칙을 분리했다.
  - `C12152`는 국내 석유류지수(B05)로 매핑하고, `C20289`는 다중 월·다중 물가 수치로 정보 부족 처리하며, `C14971`은 개별 중고차 기업 실적으로 KOSIS 미제공 처리한다.
  - P0 3건 및 v2 위임 회귀 테스트를 추가했으며 전체 19개 테스트가 통과한다.
- **다음 할 일**:
  1. 검증가능 보류 30건을 분야별 반복 지표로 묶어 코드북 v3 후보 규칙을 만든다.
  2. 검증불가 보류 35건을 KOSIS 미제공/정보 부족 사유별 자동 분류 규칙으로 분리한다.
  3. 코드북 v3 전체 회귀 테스트와 개발셋 재평가를 수행하되 독립 성능으로 보고하지 않는다.
  4. 코드북 v3를 동결한 뒤 기존 골드·홀드아웃 300건과 겹치지 않는 세 번째 독립 표본 100건에서 80% 게이트를 측정한다.
  5. 새 독립 평가가 80%를 통과할 때까지 수동검토 유지 1,281건의 자동 확정 확대는 보류한다.
  6. 통과 후 P2 58건 후보를 선택하고 P4 4,206건의 기관·통계표를 탐색한다.

## 실전1 제출 기준 정리

- 핵심 제출물: `docs/templates/통계표_관찰_템플릿.xlsx`의 통계표 관찰 기록, API 파라미터 참고, 탐색 경로 예시, 인덱스 EDA 요약.
- 최신 EDA 기준: `kosis_table_summary.csv` 107,138건.
- 검증 파일(`table_claim_mapping.csv`, `verified_claims.csv`)은 후속 검증 파이프라인의 대표 실행 성과로만 짧게 언급한다.
- 따라서 실전1의 KOSIS API 연동·통계표 관찰·EDA 요약 범위는 완료됐다.
- 남은 4,403건 수동 검토, 코드북 v2 개발과 새 독립 재평가는 실전2·종합 단계의 후속 과제로 둔다.

## 브랜치 전략

- `main`: 안정 버전만. 직접 push 금지
- `develop`: 통합 브랜치
- `feature/기능명`, `fix/버그명`: 각자 작업 브랜치, develop으로 PR 병합

커밋 메시지는 `feat:`, `fix:`, `docs:`, `chore:` 등 Conventional Commits 형식을 따릅니다.
---

## Poc 브랜치 초기 기록

아래 내용은 `Poc` 브랜치에서 정리한 초기 자동 매칭 PoC 진행 결과다. 현재 기준 성능과 제출 파일은 위의 최신 진행 현황 및 `outputs/bteam_holdout2/` 결과를 따른다.

# 📊 B팀 KOSIS 매칭 PoC 진행 결과

## 1. 데이터 수령 및 전처리

**A팀 전달 데이터**

* 원본 파일: `claim_df.csv`
* 총 주장(Claim) 수: **20,486건**

### 포함 컬럼

| 컬럼            |
| ------------- |
| claim_id      |
| article_id    |
| title         |
| date          |
| url           |
| claim_text    |
| prev_sentence |
| next_sentence |
| numbers       |
| units         |
| year          |
| region        |

---

## 2. 수행 작업

| 단계            | 결과 파일                                | 내용                                                                         | 상태 |
| ------------- | ------------------------------------ | -------------------------------------------------------------------------- | -- |
| ① A팀 데이터 확인   | `claim_df.csv`                       | Claim 데이터 구조 및 컬럼 확인                                                       | ✅  |
| ② B팀 입력 형식 변환 | `claim_candidates_from_a_sample.csv` | `claim_text`, `numbers`, `units`, `time`, `population`, `keywords` 형식으로 변환 | ✅  |
| ③ 검증 우선 후보 선별 | `claim_candidates_top30.csv`         | %, 원, 억원, 조원, 명, 건 등 통계 검증 가능성이 높은 주장 30건 선정                               | ✅  |
| ④ KOSIS 자동 매칭 | `table_claim_mapping.csv`            | KOSIS 통계표(`kosis_table_summary.csv`)와 자동 후보 매칭                             | ✅  |
| ⑤ 결과 검토 요약    | `metric_review_summary.csv`          | 자동 후보 적합 여부 및 수동 검토 필요 여부 정리                                               | ✅  |

---

# 🔄 PoC 파이프라인

```text
A팀 Claim 데이터
        │
        ▼
B팀 입력 형식 변환
        │
        ▼
검증 가능 Claim 선별
        │
        ▼
KOSIS 통계표 후보 검색
        │
        ▼
자동 매칭 결과 생성
        │
        ▼
사람 검토용 요약 생성
```

---

# 📈 진행 결과

### ✅ 성공한 부분

* PoC 파이프라인 전체 실행 성공
* A팀 Claim 데이터를 B팀 입력 형식으로 변환 성공
* KOSIS 통계표 후보 자동 매칭 성공
* 사람이 검토 가능한 결과 요약 파일 생성 성공

---

# ⚠️ 확인된 한계

현재 A팀 Claim 데이터에는 아래 정보가 포함되어 있지 않습니다.

* **metric**
* **population**
* **keywords**

이 정보가 부족하여 일부 자동 매칭의 정확도가 낮아지는 사례가 확인되었습니다.

### 예시

* ✅ **물가 관련 주장** → 소비자물가지수(CPI) 통계표와 비교적 정확하게 매칭
* ⚠️ **수출 / GDP / 가계소득 관련 주장** → 의미가 유사한 다른 통계표가 후보로 선택되는 경우 발생

---

# 💡 PoC 결론

### ✔ 확인된 사항

* A팀의 **수치 기반 주장 후보**를 B팀의 **KOSIS 통계표 후보**와 연결하는 전체 파이프라인은 정상적으로 동작함을 확인했습니다.

### ✔ 향후 개선 사항

자동 매칭 정확도를 높이기 위해 A팀 Claim Schema에 아래 컬럼을 추가하여 전달받는 것이 필요합니다.

| 추가 필요 컬럼       | 목적                   |
| -------------- | -------------------- |
| **metric**     | 비교 대상 통계 지표 명확화      |
| **population** | 대상 집단 정보 제공          |
| **keywords**   | 의미 기반 검색 및 매칭 정확도 향상 |

---

## ✅ 최종 결론

> **PoC는 전체 데이터 흐름(Claim → KOSIS 통계표 매칭 → 검토 요약) 검증에 성공했습니다.**
>
> 향후 **metric, population, keywords** 정보를 함께 제공받는다면 KOSIS 통계표 자동 매칭의 정확도를 더욱 향상시킬 수 있을 것으로 판단됩니다.
