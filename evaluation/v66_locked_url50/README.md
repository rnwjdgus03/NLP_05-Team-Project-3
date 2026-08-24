# v66 잠금 조선일보 URL50 E2E

원본 `chosun_full.csv`에서 미리 잠근 URL 50건을 v64 동결 엔진으로 끝까지 처리한 최종 실서비스 QA입니다. 중간 결과를 보고 규칙을 수정하지 않았습니다.

| 항목 | 결과 | 사전 기준 | 판정 |
|---|---:|---:|---|
| 기사 수집 성공률 | 50/50 (100%) | 90% 이상 | PASS |
| 작업 성공률 | 50/50 (100%) | 95% 이상 | PASS |
| 공식 근거 선택률 | 11/96 (11.46%) | 10% 이상 | PASS |
| 공식 근거 기사 | 5건 | 5건 이상 | PASS |
| 작업시간 p95 | 290.36초 | 600초 이하 | PASS |
| 단일 동결 엔진 | 1개 SHA | 1개 | PASS |

최종 상태는 `PASS`, `promotion_allowed=true`입니다. 판정은 `MATCH` 11개, `UNRESOLVED` 252개이며, `UNRESOLVED`는 오답으로 세지 않고 자동 검증 보류로 해석합니다.

- `qa_summary.json`: 성공률·판정·근거·지연시간
- `identity_audit.json`: 잠금 입력과 v64 엔진 SHA 동일성
- `funnel_audit.json`: 게이트 및 검증 실패 사유
- `service_readiness.json`: 사전 서비스 기준 최종 판정