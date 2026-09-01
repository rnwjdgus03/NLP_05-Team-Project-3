# AI 뉴스 수치 주장 추출 및 KOSIS 사실검증 PoC

뉴스 기사 URL에서 수치 기반 주장을 탐지하고 KOSIS Open API 공식 통계와 비교하는 PoC 프론트엔드 및 BFF입니다. 단순 기사 검색이 아니라 아래 전체 검증 흐름을 사용자에게 보여줍니다.

1. 기사 본문 수집 및 통계 관련 수치 문장 Top-4 선별
2. HCX 기반 indicator·item·period·value 구조화
3. BGE·Reranker 기반 KOSIS 통계표 검색
4. PostgreSQL 공식 메타데이터 기반 ITEM·OBJ·주기 확인
5. KOSIS Open API 공식값 조회
6. MATCH·REVIEW·UNRESOLVED 판정과 표·항목·기간·수치 근거 표시

브라우저와 내부 v42 FastAPI 사이에는 BFF를 둡니다. 브라우저에는 `KOSIS_SERVICE_API_KEY`, `CLOVA_API_KEY`, `KOSIS_API_KEY`가 전달되지 않습니다.

- UI: `http://127.0.0.1:3100/`
- Browser-safe API: `/api/verifications`
- Internal upstream: `http://127.0.0.1:8000/v1/verifications` 또는 평가용 후보 포트
- Runtime: Node.js 22, external dependencies 없음

정확한 통계표·ITEM·OBJ·기간이 확인되지 않으면 오답을 만들지 않고 `UNRESOLVED`로 반환합니다. 이 화면은 기술 검증용 PoC이며 KOSIS의 공식 서비스나 국가데이터처의 공식 판단을 대신하지 않습니다.

개발 중에는 SSH 터널로 접속합니다.

```powershell
ssh -N -L 3100:127.0.0.1:3100 -i "C:\Users\김진성\.ssh\3rd.pem" ubuntu@SERVER_IP
```

외부 공개 전에는 도메인, HTTPS, 사용자 인증, 요청 속도 제한을 추가해야 합니다.

실제 뉴스 URL E2E의 잠금·평가·승격 기준은 `E2E_SERVICE_PROMOTION_POLICY.md`를 따릅니다. 좌표 골드 성능만으로 서비스 버전을 확정하지 않으며, `service_readiness.json`이 `PASS`인 후보만 승격합니다.

현재 클라우드 연결 결과는 `DEPLOYMENT_REPORT.md`에 기록되어 있습니다.
