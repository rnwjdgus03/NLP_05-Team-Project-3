# 프론트 연결 확인

```text
Browser → URL BFF (127.0.0.1:3100)
        → v31b FastAPI (127.0.0.1:8000)
        → HCX + BGE/Reranker + PostgreSQL + KOSIS API
```

2026-08-21 확인 결과:

- `kosis-frontend.service`: active
- 내부 API readiness 연결: PASS
- 실제 기사 URL에서 제목·날짜·수치 주장 자동 추출: PASS
- URL E2E job 완료: SUCCEEDED
- 최종 판정: MATCH
- 기존 KOSIS MCP 포트 3000과 충돌하지 않도록 프론트는 3100 사용

외부 공개 전까지 localhost 바인딩을 유지합니다.
