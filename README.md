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
- `docs/`: 파이프라인 설명, KOSIS API 파라미터 가이드, 템플릿
- `logs/`: 작업 기록, 트러블슈팅 로그

B팀 전체 파이프라인(입력 → 필터링 → 매칭 → 메타 확인 → 검증)에 대한 자세한 설명은 [`docs/docs_bteam_pipeline.md`](./docs/docs_bteam_pipeline.md)에 정리되어 있습니다.

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
- **다음 할 일**:
  1. `outputs/bteam_verification/bteam_kosis_mapping_recheck_1998.csv`의 P0 표본 오매핑 23건부터 통계표·분류·항목·단위·기간을 다시 확인한다.
  2. `outputs/bteam_verification/bteam_kosis_review_manual_batch_001.csv`의 P0 수동검토 100건을 확인한다.
  3. 표본을 다시 실행해 API 성공 여부뿐 아니라 의미 매핑 품질까지 통과하면 1,998건 전체 검증을 실행한다.
  4. 이후 P2 58건 후보를 선택하고 P4 4,206건의 기관·통계표를 탐색한다.
  5. A팀에 `time`(구조화된 시점), 개별기업/해외기업 claim 제외 등 추가 정제 요청을 검토한다.

## 실전1 제출 기준 정리

- 핵심 제출물: `docs/templates/통계표_관찰_템플릿.xlsx`의 통계표 관찰 기록, API 파라미터 참고, 탐색 경로 예시, 인덱스 EDA 요약.
- 최신 EDA 기준: `kosis_table_summary.csv` 107,138건.
- 검증 파일(`table_claim_mapping.csv`, `verified_claims.csv`)은 후속 검증 파이프라인의 대표 실행 성과로만 짧게 언급한다.
- 남은 4,403건 수동 검토, `prd_se` 확정, 대량 검증 실행은 실전1 이후 다음 단계로 둔다.

## 브랜치 전략

- `main`: 안정 버전만. 직접 push 금지
- `develop`: 통합 브랜치
- `feature/기능명`, `fix/버그명`: 각자 작업 브랜치, develop으로 PR 병합

커밋 메시지는 `feat:`, `fix:`, `docs:`, `chore:` 등 Conventional Commits 형식을 따릅니다.
