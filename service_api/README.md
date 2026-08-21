# KOSIS v31b Service API

미사용 좌표 블라인드 평가를 통과한 `v31b_20260821_r1` 동결본을 수정하지 않고 호출하는 FastAPI 계층입니다. GPU 파이프라인은 단일 작업 큐로 직렬 실행되므로 같은 L4에서 BGE/Reranker 작업이 겹치지 않습니다.

## API 흐름

1. `POST /v1/verifications`가 작업을 큐에 넣고 `job_id`를 즉시 반환합니다.
2. `GET /v1/verifications/{job_id}`로 `QUEUED → RUNNING → SUCCEEDED/FAILED`와 세부 단계를 조회합니다.
3. `GET /v1/verifications/{job_id}/result`에서 MATCH/MISMATCH_REVIEW_REQUIRED/UNRESOLVED와 KOSIS 근거를 받습니다.
4. 불확실한 좌표에서 발생한 값 차이는 절대 MISMATCH로 노출하지 않고 UNRESOLVED로 유지합니다.

원문 주장을 넣을 때는 `input_stage=claims`, 기존 HCX 출력 행을 넣을 때는 `input_stage=measurements`를 사용합니다. URL 입력은 `frontend_server` BFF가 raw claims로 변환합니다. 원문 모드는 서버 환경변수 `CLOVA_API_KEY`가 필요합니다.

## 요청 예시

```json
{
  "input_stage": "claims",
  "claims": [
    {
      "claim_id": "article-001-c1",
      "article_id": "article-001",
      "title": "기사 제목",
      "date": "2026-08-21",
      "url": "https://example.com/article-001",
      "claim_text": "지난달 소비자물가는 전년 동월보다 2.1% 올랐다.",
      "prev_sentence": "통계청이 관련 지표를 발표했다.",
      "next_sentence": "생활물가도 상승했다."
    }
  ]
}
```

```bash
curl -X POST http://SERVER/v1/verifications \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: YOUR_SERVICE_API_KEY' \
  --data @request.json
```

Swagger 문서는 `/docs`, 상태 확인은 `/healthz`와 `/readyz`입니다.

현재 클라우드 배포 상태와 안전한 SSH 터널 사용법은 `DEPLOYMENT_REPORT.md`를 참고하세요.

## 운영 원칙

- 엔진 경로는 `/home/ubuntu/kosis-project/freezes/v31b_20260821_r1`로 고정합니다.
- 동결 manifest SHA가 다르거나 엔진 파일이 쓰기 가능하면 서비스가 기동하지 않습니다.
- Uvicorn worker는 반드시 1개만 사용합니다. 여러 worker를 띄우면 GPU 큐가 중복됩니다.
- `.env`와 실제 API 키는 Git/ZIP/프론트 코드에 넣지 않습니다.
- 외부 공개 전 HTTPS와 허용 프론트 도메인을 설정합니다.
