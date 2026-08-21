# KOSIS 뉴스 팩트체크 PoC

기사 URL 하나를 입력하면 기사 속 수치 주장을 자동 추출하고, KOSIS 공식 통계의 정확한 표·ITEM·OBJ·기간 좌표를 찾아 실제 값과 비교하는 서비스형 PoC입니다.

현재 서비스 후보는 변경 불가능하게 잠근 `v31b_20260821_r1`입니다.

## 현재 상태

- URL 입력형 프론트/BFF와 FastAPI 작업 큐 연결 완료
- HCX-007 측정값 추출 → BGE-M3 검색 → reranker → PostgreSQL 좌표 조회 → KOSIS Open API 검증 완료
- NVIDIA L4, PostgreSQL 107,138개 표 환경에서 실제 기사 E2E 검증 완료
- 개발 30건: Full Top-5 `23/30 (76.7%)`
- 미사용 좌표 블라인드 30건: Full Top-5 `28/30 (93.3%)`, Stage A 표 Top-10 `29/30 (96.7%)`
- 블라인드 최종 판정: `VERIFIED_MATCH 26`, `UNRESOLVED 4`, 잘못된 자동 `VALUE_MISMATCH 0`

블라인드 수치는 KOSIS 좌표가 식별 가능한 READY 주장 30건에 대한 검색·좌표 성능입니다. 일반 뉴스 전체의 자동 판정률로 해석하면 안 됩니다. 평가 범위와 실제 기사 결과는 [평가 문서](docs/EVALUATION.md)를 참고하세요.

## 서비스 흐름

```text
기사 URL
  → 프론트 BFF가 공개 기사 HTML 수집
  → 제목·날짜·본문 및 수치 주장 최대 8개 추출
  → HCX-007 measurement 구조화
  → READY / ENRICH / REJECT 안전 게이트
  → Stage A: lexical + BGE-M3 + reranker 표 Top-10
  → Stage B: PostgreSQL ITEM·OBJ 좌표 beam
  → Stage C: 좌표 Top-3 + 제한적 Top-5
  → PostgreSQL preflight + KOSIS Open API 실제값 조회
  → MATCH / MISMATCH_REVIEW_REQUIRED / UNRESOLVED
```

벡터 검색은 “관련 통계표 후보”만 찾고, 실제 ITEM·OBJ·주기 존재 여부는 PostgreSQL이 확정합니다. 좌표·기간·단위가 완전히 확인되지 않은 값 차이는 자동 MISMATCH로 노출하지 않습니다.

## 저장소 구성

```text
.
├─ freezes/v31b_20260821_r1/  # 운영 엔진 동결본과 manifest
├─ service_api/               # FastAPI, 단일 GPU 작업 큐, 결과 계약
├─ frontend_server/           # URL 전용 UI와 서버측 BFF
├─ evaluation/v31b_blind/     # 잠금 블라인드 골드와 요약 결과
└─ docs/                      # 구조, 배포, 평가 문서
```

대용량 BGE 인덱스, PostgreSQL 데이터, 모델 캐시, 실행 결과, API 키는 Git에 포함하지 않습니다.

## 필요한 외부 자산

서버의 `/home/ubuntu/kosis-project` 아래에 다음 자산이 별도로 있어야 합니다.

```text
indexes/bge_m3_table_v2_complete/
  tables.csv
  embeddings.npy
  manifest.json
PostgreSQL database: kosis_project
.env
```

운영 확인값은 `kosis_tables=107138`, `kosis_axis_values=9663625`, 임베딩 shape `(107138, 1024)`입니다.

## 개발 접속

프론트와 API는 기본적으로 서버 localhost에만 바인딩합니다.

```powershell
ssh -N -L 13100:127.0.0.1:3100 `
  -i "$env:USERPROFILE\.ssh\3rd.pem" `
  ubuntu@SERVER_IP
```

터널을 유지한 상태에서 `http://127.0.0.1:13100`을 엽니다. 공개 배포에는 도메인, HTTPS, 사용자 인증, rate limit을 추가해야 합니다.

설치와 운영 명령은 [RUNBOOK](docs/RUNBOOK.md), 설계 근거는 [ARCHITECTURE](docs/ARCHITECTURE.md)를 참고하세요.

## 보안 원칙

- `.env`, PEM, HCX/KOSIS 키를 커밋하지 않습니다.
- 브라우저에 서비스 API 키를 전달하지 않습니다. BFF가 서버에서 주입합니다.
- 기사 수집기는 HTTP/HTTPS 공개 주소만 허용하고 사설·loopback·link-local 주소를 차단합니다.
- FastAPI worker와 GPU worker는 각각 하나만 실행합니다.
- 동결 엔진의 `freeze_id`와 SHA가 다르면 API를 기동하지 않습니다.
