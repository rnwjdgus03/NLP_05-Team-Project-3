# 파이프라인 아키텍처

## 1. 구성 요소

| 구성 요소 | 역할 | 주요 입력 → 출력 |
|---|---|---|
| URL BFF | 공개 기사 수집, SSRF 차단, 메타데이터·수치 문장 추출 | URL → raw claims |
| HCX-007 | 비정형 문장에서 지표·대상·값·단위·기간 구조화 | raw claims → measurements |
| 안전 게이트 | KOSIS 직접 대조 가능성 판정 | measurements → READY/ENRICH/REJECT |
| Stage A | 관련 KOSIS 통계표 검색 | READY → table Top-10 |
| Stage B | 실제 메타데이터 안에서 ITEM·OBJ 좌표 구성 | tables → coordinate beam |
| Stage C | 대상·기간·단위·표 범위를 반영해 좌표 재순위 | beam → Top-3 + rank 4–5 |
| 값 검증 | PostgreSQL preflight 후 KOSIS API 실제값 비교 | coordinates → evidence/verdict |
| FastAPI | FIFO 작업 큐, 상태 조회, 결과 직렬화 | request → job/result |
| 프론트 | URL 입력, 진행 단계, KOSIS 근거 표시 | browser → BFF |

## 2. 비정형 검색과 정형 조회의 분리

기사 표현은 다양하므로 표 검색에는 lexical, BGE-M3 dense retrieval, cross-encoder reranker를 함께 사용합니다. 이 단계는 의미상 관련된 표 후보를 넓게 찾는 역할만 합니다.

ITEM·OBJ·주기처럼 실제 API 호출에 필요한 좌표는 PostgreSQL의 KOSIS 공식 메타데이터에서 조회합니다. 벡터 검색 결과가 유사하더라도 DB에 존재하지 않거나 주장 대상과 맞지 않는 좌표는 사용할 수 없습니다.

```text
비정형: 기사 표현 → BGE/Reranker → tbl_id 후보
정형: tbl_id → PostgreSQL ITEM/OBJ/주기 → 유효 좌표
공식값: 유효 좌표 → KOSIS Open API → 비교 근거
```

## 3. v31b 검색 정책

- Stage A를 `legacy`와 `balanced` 두 정책으로 실행합니다.
- 각 정책은 lexical Top-300, dense Top-300, rerank Top-200을 사용합니다.
- 두 결과를 합쳐 표 Top-10을 보존합니다.
- 조사·기관·표 계열 슬롯과 ITEM recall을 함께 반영합니다.
- Stage B는 표별 fallback 좌표를 보존하며 beam 250개까지 구성합니다.
- Stage C는 Top-3를 기본으로 사용하고 rank 4–5는 제한적 fallback으로만 사용합니다.

## 4. 판정 안전성

`READY`는 입력 주장이 검색 가능하다는 뜻이지 정답 좌표가 확정됐다는 뜻이 아닙니다. 다음이 확인돼야 공식값 차이를 판정 근거로 사용할 수 있습니다.

- 주장과 같은 통계표 범위
- 같은 ITEM 의미
- 성별·연령·지역·품목 등 OBJ 대상 일치
- 기간과 주기 일치
- 단위와 환산계수 확인
- 직접값/증감률/구성비 등 값 유형 일치

하나라도 불확실하면 `UNRESOLVED`로 보류합니다. 값 차이가 있어도 미확정 좌표에서는 `VALUE_MISMATCH`를 차단합니다. 외부에 노출되는 상태는 `MATCH`, `MISMATCH_REVIEW_REQUIRED`, `UNRESOLVED` 세 가지입니다.

## 5. 서비스 경계

- FastAPI는 한 개의 Uvicorn worker와 한 개의 FIFO GPU 큐를 사용합니다.
- 동결 엔진은 `freezes/v31b_20260821_r1`에서 읽기 전용으로 실행합니다.
- BFF는 브라우저 대신 내부 API 키를 주입합니다.
- URL 수집은 최대 5MB HTML, 최대 4회 redirect, 최대 8개 수치 주장으로 제한합니다.
- 로그인·구독·JavaScript 렌더링만 허용하는 기사는 수집하지 못할 수 있습니다.
