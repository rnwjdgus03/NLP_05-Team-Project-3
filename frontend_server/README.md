# AI 뉴스 수치 주장 추출 및 KOSIS 사실검증 PoC

조선일보 기사 URL에서 통계 관련 수치 문장을 찾고, 사용자가 검증할 문장을 선택하면 동결된 v60 엔진이 KOSIS 공식 통계와 대조하는 프론트엔드/BFF입니다.

## 사용자 흐름

1. 조선일보 기사 URL 입력
2. 서버가 기사 본문을 수집하고 통계 관련 문장 Top-4 탐지
3. 사용자가 검증할 문장 선택
4. v60 작업 큐에 선택 문장을 등록
5. HCX 구조화 → Stage A 표 검색 → Stage B/C 좌표 선택 → PostgreSQL preflight → KOSIS Open API 조회
6. 브라우저가 작업 상태를 polling하고 `MATCH`, `MISMATCH_REVIEW_REQUIRED`, `UNRESOLVED`와 근거를 표시

브라우저에는 `KOSIS_SERVICE_API_KEY`, `CLOVA_API_KEY`, `KOSIS_API_KEY`가 전달되지 않습니다. BFF가 내부 FastAPI에만 서비스 키를 주입합니다.

## API 계약

### 문장 탐지

- `POST /api/articles/claims-url`: `{ "url": "https://..." }`
- `POST /api/articles/claims`: 테스트용 직접 본문 입력

응답은 만료 시간이 있는 `session_id`와 선택 가능한 `claims`를 반환합니다. 세션은 메모리에만 30분간 보존되며 최대 200개입니다.

### 선택 문장 검증 등록

- `POST /api/articles/analyze-selection`

```json
{
  "session_id": "...",
  "claim_ids": ["URL-...-1"]
}
```

응답은 `202`와 `job_id`를 반환합니다. UI는 다음 내부 프록시를 사용해 완료까지 조회합니다.

- `GET /api/verifications/{job_id}`
- `GET /api/verifications/{job_id}/result`

기존 URL 일괄 E2E용 `POST /api/article-verifications`도 유지합니다.

## 실행

필수 환경변수:

- `KOSIS_API_BASE_URL`: 내부 FastAPI 주소
- `KOSIS_SERVICE_API_KEY`: FastAPI 서비스 키
- `KOSIS_FRONTEND_HOST`: 기본값 `127.0.0.1`
- `KOSIS_FRONTEND_PORT`: 기본값 `3000`
- `KOSIS_MAX_ARTICLE_CLAIMS`: 기본값 `4`, 최대 `8`

```bash
node server.mjs
```

개발 중에는 SSH 터널로 접속합니다.

```powershell
ssh -N -L 13100:127.0.0.1:3100 -i "C:\Users\사용자\.ssh\3rd.pem" ubuntu@SERVER_IP
```

## 검증

```bash
node --check server.mjs
node --check public/static/app.js
node test_article_extractor.mjs
node test_frontend_v60_adapter.mjs
python test_frontend_url_only.py
```

`test_frontend_v60_adapter.mjs`는 임시 모의 FastAPI를 띄워 문장 탐지, 선택 세션, v60 작업 등록, 상태 조회, 결과 프록시, 정적 UI 제공을 함께 확인합니다.

## 안전 원칙

- URL 수집기는 사설·loopback·link-local 주소를 차단합니다.
- 좌표·기간·단위가 확인되지 않으면 `VALUE_MISMATCH`를 확정하지 않습니다.
- 불확실한 결과는 `UNRESOLVED`로 보류합니다.
- 이 화면은 기술 검증용 PoC이며 KOSIS나 국가데이터처의 공식 판정을 대신하지 않습니다.
- 외부 공개 전에는 HTTPS, 사용자 인증, 요청 속도 제한, 영속 작업 큐가 추가로 필요합니다.

실제 뉴스 URL E2E의 잠금·평가·승격 기준은 `E2E_SERVICE_PROMOTION_POLICY.md`를 따릅니다. `service_readiness.json`이 `PASS`인 후보만 서비스 버전으로 승격합니다.
