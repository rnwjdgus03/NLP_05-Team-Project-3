# KOSIS Open API 파라미터 가이드

실제로 호출해보면서 확인한 내용 기준으로 정리. 공식 개발가이드 문서와 다른 부분은 따로 표시함.

## 공통 주의사항

1. **`format=json`이어도 표준 JSON이 아님.** 키에 따옴표가 없는 비표준 형식으로 응답이 온다.
   ```
   [{LIST_NM:"인구",LIST_ID:"A"}, ...]
   ```
   그냥 `response.json()`을 쓰면 `JSONDecodeError`가 난다. 정규식으로 키를 따옴표로 감싸는 전처리가 필요하다 (`kosis_api_test.py`의 `_parse_kosis_json()` 참고).

2. **결과가 1건이면 배열이 아니라 객체 하나로 올 때가 있다.** `[{...}]`가 아니라 `{...}`로 오는 경우, 그냥 순회하면 `dict`의 key(문자열)를 도는 사고가 난다. 항상 `dict`면 리스트로 감싸는 처리가 필요하다.

3. **에러 응답도 표준 JSON이 아니다.** 예: `{err:"30",errMsg:"데이터가 존재하지 않습니다."}` — 이 형태도 위 1번 전처리로 파싱되긴 하지만, `err` 키가 있으면 정상 데이터가 아니라 에러라는 걸 체크해야 한다.

4. **분당 호출 제한이 있다.** 대량으로 반복 호출할 때는(카테고리 크롤링 등) 호출 사이에 `sleep`을 넣어야 한다 (`kosis_table_search.py`에서 0.3초 사용).

---

## 1. 통계목록 API — 카테고리/통계표 탐색

```
GET https://kosis.kr/openapi/statisticsList.do?method=getList
```

| 파라미터 | 설명 | 비고 |
|---|---|---|
| apiKey | 인증키 | 필수 |
| vwCd | 서비스뷰 코드 | 국내통계 주제별 = `MT_ZTITLE` |
| parentListId | 상위 목록 ID | **개발가이드엔 `parentId`로 나오지만 실제로는 이 이름이어야 동작함** |
| format | 결과 형식 | `json` |

- `parentListId=""` (공백) → 최상위 카테고리 목록
- 응답의 `LIST_ID`를 다음 호출의 `parentListId`로 넘기면 한 단계 더 내려감
- 계속 내려가다 보면 `TBL_ID`가 있는 항목이 나오는데, 이게 실제 통계표(leaf)

최상위 카테고리 코드 (vwCd=MT_ZTITLE 기준):
```
A=인구 B=사회일반 C=범죄ㆍ안전 D=노동 E=소득ㆍ소비ㆍ자산 F=보건 G=복지
H1=교육ㆍ훈련 H2=문화ㆍ여가 I1=주거 I2=국토이용 J1=경제일반ㆍ경기 J2=기업경영
K1=농림 K2=수산 L=광업ㆍ제조업 M1=건설 M2=교통ㆍ물류 N1=정보통신 N2=과학ㆍ기술
O=도소매ㆍ서비스 P1=임금 P2=물가 Q=국민계정 R=정부ㆍ재정 S1=금융 S2=무역ㆍ국제수지
T=환경 U=에너지 V=지역통계
```

키워드로 직접 검색하는 기능은 없음 — 카테고리를 다 훑어서 로컬 인덱스를 만들고, 그 인덱스에서 검색하는 방식으로 대체함 (`kosis_table_search.py`).

---

## 2. 통계자료(Param) API — 실제 수치 조회

```
GET https://kosis.kr/openapi/Param/statisticsParameterData.do?method=getList
```

| 파라미터 | 설명 | 비고 |
|---|---|---|
| apiKey | 인증키 | 필수 |
| orgId | 기관 ID | 필수 (예: `101`) |
| tblId | 통계표 ID | 필수 (예: `DT_1EA1019`) |
| objL1 ~ objL8 | 분류1~8 코드 | objL1 필수, `ALL`이면 전체 분류 |
| itmId | 항목 코드 | 필수, `ALL`이면 전체 항목 |
| prdSe | 수록주기 | 연간=Y, 반기=H, 분기=Q, 월=M |
| startPrdDe / endPrdDe | 시작/종료 시점 | newEstPrdCnt와 택1 |
| newEstPrdCnt | 최근 시점 개수 | 예: 1 = 최신 1개 시점만 |
| format | 결과 형식 | `json` |

출력 필드 중 자주 쓰는 것: `TBL_NM`(표이름), `C1~C8`(분류코드), `C1_NM~`(분류값 이름), `ITM_ID`/`ITM_NM`(항목), `UNIT_NM`(단위), `PRD_DE`(시점), `DT`(실제 수치값).

---

## 3. 통계표설명(메타정보) API — 분류/항목 코드 목록 조회

```
GET https://kosis.kr/openapi/statisticsData.do?method=getMeta&type=ITM
```

실제 데이터를 안 가져와도, `orgId`+`tblId`만 있으면 그 표의 **분류 코드 전체 + 항목 코드 전체**를 알 수 있다. objL1/itmId 값을 모를 때 이걸로 먼저 확인하면 된다.

| 파라미터 | 설명 | 비고 |
|---|---|---|
| apiKey | 인증키 | 필수 |
| type | 조회 종류 | `TBL`=표 이름만, `ITM`=분류+항목 코드 전체 |
| orgId | 기관 ID | 필수 |
| tblId | 통계표 ID | 필수 |
| format | 결과 형식 | `json` |

응답 안에서 `OBJ_ID == "ITEM"`인 행 = 항목(itmId 후보), 그 외 `OBJ_ID`(A, B ...)인 행 = 분류(objL1, objL2 ... 후보). `OBJ_NM`이 그 분류축의 이름.

단위(`UNIT_NM`)는 이 메타 API에는 없어서, 실제 데이터를 1건만 조회해서 확인해야 한다 (`kosis_api_test.py`의 `get_sample_unit` 참고).

---

## 실전 활용 순서 (추천)

1. `통계목록` API로 카테고리를 타고 내려가며 후보 표(orgId, tblId) 찾기 — 또는 미리 크롤링해둔 `kosis_table_summary.csv`에서 키워드 검색
2. `통계표설명(메타정보)` API로 그 표의 분류축/항목 코드 확인
3. `통계자료(Param)` API로 실제 필요한 조합(objL1, itmId)의 수치 조회
4. 결과의 `DT` 값과 뉴스 기사 속 수치를 비교

## 참고 코드

- `kosis_api_test.py` — `get_stat_data()`, `get_meta()`, `summarize_meta()`
- `kosis_table_search.py` — `crawl_all_tables()`, `search_candidate_tables()`
- `kosis_metadata_summary.py` — 여러 표에 대해 메타정보를 한 번에 뽑아 CSV로 정리
