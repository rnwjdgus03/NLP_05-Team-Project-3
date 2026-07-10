# NLP_05-Team-Project-3

AI 기반 뉴스 사실검증 시스템 (멋쟁이사자처럼 AI/NLP 5기 클라비 기업 프로젝트)

뉴스 기사 내 수치 기반 주장을 탐지하고, KOSIS(국가데이터처) 공식 통계와 비교하여 사실 여부를 검증하는 AI 시스템 PoC.

## 팀 구성

- **A팀 (2명)** — 조선일보 기사 크롤링 + 뉴스 주장 추출
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

## 알아두면 좋은 KOSIS API 주의사항

- 개발가이드 문서엔 `parentId`라고 나오지만, 실제로는 `parentListId` 파라미터여야 동작합니다.
- `format=json`이라 해도 응답이 표준 JSON이 아니라 key에 따옴표가 없는 형식이라, 그냥 `res.json()`을 쓰면 에러가 납니다. `kosis_api_test.py`의 `_parse_kosis_json()`으로 전처리해서 씁니다.

## 브랜치 전략

- `main`: 안정 버전만. 직접 push 금지
- `develop`: 통합 브랜치
- `feature/기능명`, `fix/버그명`: 각자 작업 브랜치, develop으로 PR 병합

커밋 메시지는 `feat:`, `fix:`, `docs:`, `chore:` 등 Conventional Commits 형식을 따릅니다.
