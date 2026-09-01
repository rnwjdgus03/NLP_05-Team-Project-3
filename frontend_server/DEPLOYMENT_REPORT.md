# v60 프론트 통합 상태

## 현재 구성

```text
Browser
  → 최종 UI + Node BFF
    → v60 FastAPI FIFO 작업 큐
      → HCX → BGE-M3/Reranker → PostgreSQL → KOSIS Open API
```

브라우저는 BFF의 동일 출처 `/api/*`만 호출합니다. HCX, KOSIS, 서비스 API 키는 브라우저 JavaScript에 포함되지 않습니다.

## 완료된 검증

- 팀 최종 UI의 HTML/CSS/JavaScript 선별 통합
- 조선일보 기사 URL 전용 입력
- 기사 수치 문장 탐지 후 사용자 선택 세션
- 선택 문장을 v60 비동기 작업 큐에 등록
- 작업 상태 polling 및 v60 결과를 판정 카드로 변환
- 기존 실제 URL 일괄 E2E 엔드포인트 유지
- 기사 추출기 테스트 4건 통과
- 문장 탐지 → 선택 → 등록 → 상태 → 결과 프록시 계약 테스트 통과
- JavaScript 구문 검사 통과

## 아직 승격하지 않은 항목

- 잠금 조선일보 URL 50건 E2E 최종 감사
- `service_readiness.json` 판정 확인
- 최종 서버 프로세스 교체 및 브라우저 실화면 확인

URL 50건 평가 중간 결과는 튜닝에 사용하지 않습니다. 최종 감사가 끝나고 승격 게이트가 통과한 경우에만 기존 서비스 프로세스를 교체합니다.

## 개발 접속

```powershell
ssh -N -L 13100:127.0.0.1:3100 `
  -i "C:\Users\사용자\.ssh\3rd.pem" `
  ubuntu@SERVER_IP
```

터널 연결 뒤 `http://127.0.0.1:13100`을 엽니다.

## 공개 전 추가 요구사항

- 도메인과 HTTPS
- 사용자 인증 및 요청 속도 제한
- 영속 작업 큐와 장애 복구
- API 사용량·응답시간·오류 모니터링
- 키 교체와 최소 권한 운영
