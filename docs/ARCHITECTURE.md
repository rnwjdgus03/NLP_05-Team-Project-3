# v60 파이프라인 아키텍처

## 설계 목표

뉴스의 다양한 표현을 이해하는 검색과 KOSIS의 엄격한 코드 좌표 조회를 분리합니다. 의미가 비슷하다는 이유만으로 공식 통계값을 비교하지 않고, 실제 메타데이터에 존재하는 표·ITEM·OBJ·기간·주기·단위가 확인된 경우에만 값 검증으로 진행합니다.

## 단계별 입력과 출력

| 단계 | 주요 파일/컴포넌트 | 입력 | 출력 |
|---|---|---|---|
| URL 수집 | `frontend/server.mjs` | 조선일보 공개 URL | 제목·날짜·본문·수치 문장 |
| 주장 구조화 | `engine/extract_hcx.py` | 문장과 앞뒤 문맥 | indicator/item/obj/period/value/unit |
| 준비 게이트 | `engine/prepare_kosis_mapping_input.py` | measurements | READY/ENRICH/REJECT |
| Stage A | `engine/run_kosis_coordinate_stage_a.py` | READY 주장, BGE 표 인덱스 | KOSIS 표 후보 |
| Stage B | `engine/run_kosis_coordinate_stage_b.py` | 표 후보, PostgreSQL metadata | ITEM·OBJ 좌표 beam |
| Stage C | `engine/run_kosis_coordinate_stage_c.py` | 좌표 beam | 재순위 Top-3/Top-5 |
| 값 검증 | `engine/run_kosis_top5_verification.py` | 좌표·기간·값 | KOSIS evidence/verdict |
| API | `api/app/` | 검증 job | 상태·결과 JSON |
| 프론트/BFF | `frontend/` | URL | 진행 단계·판정·근거 UI |

## 비정형 검색

Stage A는 기사 표현과 KOSIS 표명 사이의 어휘 차이를 처리합니다.

1. lexical 후보와 BGE-M3 dense 후보를 넓게 수집
2. cross-encoder reranker로 관련 표를 재정렬
3. 조사명·작성기관·통계분류·표 계열·기간 힌트를 반영
4. 관련 표 Top-N을 정형 조회 단계로 전달

이 단계의 답은 정답 좌표가 아니라 `tbl_id 후보`입니다.

## 정형 조회

PostgreSQL에는 KOSIS 메타데이터가 정규화돼 있습니다.

- `kosis_tables`: 통계표와 조사/기관 정보
- `kosis_items`: 수록 항목 코드
- `kosis_axes`, `kosis_axis_values`: 성별·연령·지역·품목 등 OBJ 축과 값
- `kosis_periodicities`: 월·분기·연 주기

Stage B/C는 후보 표가 실제로 지원하는 좌표만 만들고, 대상 범위·전체/세부 품목·기간·단위를 반영해 순위를 정합니다. 이 구조 덕분에 84만 개 좌표 문서를 모두 벡터 DB에 넣지 않고도 exact retrieval을 수행할 수 있습니다.

## 공식값 검증과 안전 정책

PostgreSQL preflight를 통과한 좌표만 KOSIS Open API 후보가 됩니다. 다음 중 하나라도 불확실하면 값 차이를 확정하지 않습니다.

- 통계표와 조사 범위
- ITEM 의미
- 성별·연령·지역·품목 OBJ
- 기간 및 월·분기·연 주기
- 단위와 환산계수
- 직접값·증감률·구성비 등 값 유형

외부 상태는 다음 세 가지입니다.

- `MATCH`: 확인된 좌표와 공식값이 허용 범위 안에서 일치
- `MISMATCH_REVIEW_REQUIRED`: 확인된 근거에서 차이가 있으나 검토 필요
- `UNRESOLVED`: 좌표·기간·단위 또는 공식값을 충분히 확정하지 못함

## 서비스 구조

```text
Browser
  ↕ URL-only request
Node BFF / Frontend
  ↕ internal API key
FastAPI FIFO job queue
  ↕ single GPU worker
v60 frozen engine
  ├─ BGE-M3 + reranker (GPU)
  ├─ PostgreSQL exact metadata
  ├─ HCX API
  └─ KOSIS Open API
```

GPU 메모리 충돌과 API rate limit을 피하기 위해 메인 추론은 단일 FIFO 큐로 직렬화합니다. SQL 분석·프론트 개발처럼 GPU를 사용하지 않는 작업은 병행할 수 있습니다.
