# KOSIS v64 Service API

`v64_candidate_20260824_r1` 동결 엔진을 호출하는 FastAPI 계층입니다. 실제 최종 URL50 QA에서는 v60에서 검증된 API 셸에 v64 엔진 경로와 SHA를 환경변수로 주입했습니다. GPU 파이프라인은 단일 FIFO 작업 큐로 직렬 실행합니다.

## API 흐름

1. `POST /v1/verifications`가 작업을 큐에 넣고 `job_id`를 반환합니다.
2. `GET /v1/verifications/{job_id}`로 `QUEUED → RUNNING → SUCCEEDED/FAILED`를 조회합니다.
3. `GET /v1/verifications/{job_id}/result`에서 `MATCH`, `MISMATCH_REVIEW_REQUIRED`, `UNRESOLVED`와 KOSIS 근거를 받습니다.
4. 좌표·기간·단위가 완전히 확인되지 않은 값 차이는 `MISMATCH`로 단정하지 않고 `UNRESOLVED`로 유지합니다.

원문 주장은 `input_stage=claims`, 기존 HCX 출력은 `input_stage=measurements`를 사용합니다. URL 입력은 `frontend_server` BFF가 기사 본문을 수집해 raw claim으로 변환합니다. 원문 모드는 서버 환경변수 `CLOVA_API_KEY`가 필요합니다.

## 최종 실행

서버 프로젝트 루트에서 다음 스크립트를 사용합니다.

```bash
./cloud_setup/start_v64_final_api.sh
./cloud_setup/start_v64_final_frontend.sh
curl -fsS http://127.0.0.1:8002/readyz
curl -I http://127.0.0.1:3102/
```

Swagger 문서는 API가 실행 중일 때 `http://127.0.0.1:8002/docs`입니다. 외부 공개 전에는 HTTPS 또는 SSH 터널을 사용합니다.

## 요청 예시

```json
{
  "input_stage": "claims",
  "claims": [{
    "claim_id": "article-001-c1",
    "article_id": "article-001",
    "title": "기사 제목",
    "date": "2026-08-21",
    "url": "https://example.com/article-001",
    "claim_text": "지난달 소비자물가는 전년 동월보다 2.1% 올랐다.",
    "prev_sentence": "통계청이 관련 지표를 발표했다.",
    "next_sentence": "생활물가도 상승했다."
  }]
}
```

## 운영 원칙

- 엔진은 `freezes/v64_candidate_20260824_r1/engine`과 manifest SHA로 고정합니다.
- v65 blind100은 ITEM Top-5 58%, 좌표 Top-5 54%로 사전 목표에 실패했습니다. 서비스 실행 허용은 발표용 PoC 판단이며 블라인드 성능 통과를 의미하지 않습니다.
- Uvicorn worker와 GPU 파이프라인은 각각 하나만 실행합니다.
- `.env`, API 키, PEM, PostgreSQL 덤프와 BGE 임베딩은 Git에 넣지 않습니다.
- 상세 근거는 `evaluation/v65_blind100/`과 `evaluation/v66_locked_url50/`을 확인합니다.