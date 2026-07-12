# NLP_05-Team-Project-3

AI 기반 뉴스 사실검증 시스템 (멋쟁이사자처럼 AI/NLP 5기 클라비 기업 프로젝트)

뉴스 기사 내 수치 기반 주장을 탐지하고, KOSIS(국가데이터처) 공식 통계와 비교하여 사실 여부를 검증하는 AI 시스템 PoC.

## 팀 구성

- **A팀 (2명)** — 조선일보 데이터셋(노션 페이지로 제공) 기반 뉴스 주장 추출
- **B팀 (2명)** — KOSIS API 연동 + 통계표 구조 분석

두 팀의 접점은 `claim_id` 기준으로 연결되는 주장↔통계표 매핑 스키마입니다.

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

- 통계목록 최상위 카테고리 조회
- "농림 → 농림어업조사 → 농업 → 2010년~" 경로로 내려가서 통계표 탐색
- "경영주 연령별 농가"(orgId=101, tblId=DT_1EA1019) 표의 2024년 전국 데이터 조회

### `kosis_table_search.py` — 후보 통계표 검색

통계목록 API에는 키워드 검색 기능이 없어서, 카테고리 트리를 재귀적으로 크롤링해 로컬 인덱스(`kosis_table_summary.csv`)를 만들고, 그 인덱스에서 키워드로 후보 통계표를 찾는 방식입니다.

```bash
python kosis_table_search.py
```

- `crawl_all_tables(start_parent="K1")` — 지정한 카테고리(예: 농림=K1) 하위 통계표 전체를 크롤링해 `kosis_table_summary.csv`로 저장
- `search_candidate_tables(keywords, table_index)` — A팀이 뽑은 주장 키워드로 로컬 인덱스에서 후보 표 검색

전체 카테고리를 한 번에 크롤링하면 오래 걸리고 KOSIS 분당 호출 제한에 걸릴 수 있으니, 관련 있는 상위 카테고리 1~2개부터 시작하는 걸 권장합니다. 최상위 카테고리 코드는 스크립트 상단 주석 참고.

현재 `kosis_table_summary.csv`에는 농림·인구·노동·물가·사회일반·소득소비자산·경제일반경기·무역국제수지·임금·도소매서비스 카테고리, 총 27,127개 통계표가 인덱싱되어 있습니다.

### `kosis_metadata_summary.py` — 표별 분류/항목/단위 조회

통계표설명(메타정보) API(`method=getMeta&type=ITM`)를 이용해, 실제 데이터를 조회하지 않고도 표의 분류 코드 전체 + 항목 코드 전체를 확인합니다.

```bash
python kosis_metadata_summary.py
```

- `kosis_api_test.py`의 `get_meta()` / `summarize_meta()` 함수를 사용
- 응답에서 `OBJ_ID=="ITEM"`인 행이 항목(itmId), 그 외 `OBJ_ID`(A, B ...)인 행이 분류(objL1 등)
- 결과를 `kosis_metadata_summary.csv`로 저장

### `match_claims_to_tables.py` — A팀 주장 후보 자동 매칭

A팀이 만든 `claim_candidates.csv`(claim_id, claim_text, metric, time, population, unit 컬럼)를 읽어서, 각 주장마다 `kosis_table_summary.csv`에서 후보 통계표를 검색하고 메타정보 힌트까지 붙여 `table_claim_mapping.csv` 초안을 생성합니다.

```bash
python match_claims_to_tables.py
```

완전 자동 검증은 아니고 1차 초안이라, 후보 표 중 실제로 맞는 표를 고르고 `calculation`(계산식)·`verifiable`(일치/불일치/판단불가)은 직접 확인해서 채워야 합니다.

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
- 파라미터 상세 내용은 [`kosis_param_guide.md`](./kosis_param_guide.md) 참고.

## 현재 진행 상황 (2026.07.11 기준)

- B팀: KOSIS API 연동, 통계표 인덱스(27,127개), 메타정보 조회, 파라미터 가이드, 자동 매칭 스크립트까지 준비 완료
- A팀: 조선일보 데이터셋은 A팀이 직접 크롤링하는 게 아니라 노션 페이지로 별도 제공될 예정. `feature/data`의 `chosun.csv`는 초기 테스트용 데이터로 보임. 정식 데이터셋 수신 후 `claim_candidates.csv` 형식(claim_id, claim_text, metric, time, population, unit)으로 정리되면 B팀 매칭 스크립트를 바로 돌릴 수 있음
- 2026.07.11: KOSIS 서버 접속이 간헐적으로 안 되는 상황이라, 이미 확보한 데이터로 실전1(EDA 포함 요약) 과제를 마무리함
  - `통계표_관찰_템플릿.xlsx`에 **인덱스 EDA 요약** 시트 추가 (상위 조사명/작성기관/표 이름 키워드 Top N + 차트 + 해석)
  - 같은 파일의 **API 파라미터 참고** 시트에 메타정보(getMeta) API 파라미터 섹션과 공통 주의사항(단일 객체 응답, 서버 타임아웃) 보강
  - wrap_text 대비 행 높이 부족, 좁은 컬럼 폭으로 텍스트가 잘려 보이던 서식 오류 수정, 전체 시트를 가로(landscape) + 폭 맞춤으로 인쇄 설정 변경 (PDF 20페이지 → 9페이지, 표/차트가 한 페이지 안에 온전히 들어가도록 정리)
- 2026.07.11 추가: KOSIS 서버 복구 후 소득·소비·자산(E), 경제일반·경기(J1), 무역·국제수지(S2), 임금(P1), 도소매·서비스(O) 카테고리 크롤링 완료 (7,214건 추가, 총 27,127건)

## 브랜치 전략

- `main`: 안정 버전만. 직접 push 금지
- `develop`: 통합 브랜치
- `feature/기능명`, `fix/버그명`: 각자 작업 브랜치, develop으로 PR 병합

커밋 메시지는 `feat:`, `fix:`, `docs:`, `chore:` 등 Conventional Commits 형식을 따릅니다.
