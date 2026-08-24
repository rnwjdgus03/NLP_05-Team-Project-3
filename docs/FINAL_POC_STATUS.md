# 최종 PoC 상태 공유

## 한 줄 요약

조선일보 기사 URL에서 수치 주장을 찾아 KOSIS 공식 좌표와 값을 대조하는 전체 서비스 흐름은 연결됐고, v60은 개발 300건 검색·좌표 목표를 통과한 발표 후보입니다. 잠금 URL50의 공식 근거 커버리지 게이트는 실패해 운영 서비스 승격은 보류됐습니다.

## 완료

- 기사 URL 입력 및 서버측 본문/수치 문장 추출
- HCX structured output
- KOSIS-ready 게이트
- lexical + BGE-M3 + reranker 표 검색
- PostgreSQL ITEM·OBJ·기간 exact retrieval
- KOSIS Open API 실제값 검증
- MATCH / REVIEW / UNRESOLVED 안전 판정
- FastAPI 작업 큐와 프론트 BFF/UI
- 개발 좌표 골드 300건 평가 및 v60 동결
- 보안 정제된 GitHub 공개 스냅샷
- 최종 UI와 v60 비동기 작업 API 선택 세션 어댑터 및 계약 테스트

## 현재 수치

- 개발 300건 ITEM Top-5: 77.3%
- 개발 300건 전체 좌표 Top-5: 74.3%
- 실제 기사 개발 READY 60건 중 VERIFIED_MATCH: 6건
- 표 분리 개발 600건 ITEM Top-5: 64.7%
- 표 분리 개발 600건 전체 좌표 Top-5: 60.3%
- 후보 파이프라인 테스트: 126 passed
- 프론트 문장 선택·작업 등록·상태·결과 계약 테스트: PASS
- 잠금 URL50 기사 수집 성공률: 100%
- 잠금 URL50 작업 성공률: 100%
- 잠금 URL50 공식 근거 선택률: 4.21% (기준 10%, FAIL)
- 잠금 URL50 공식 근거 기사: 3건 (기준 5건, FAIL)
- 잠금 URL50 서비스 승격: 금지

## 남은 일

1. 개발에 사용하지 않은 새 기사/좌표 골드로 독립 블라인드 확대
2. 잠금 URL50과 분리된 개발 기사셋에서 자동 근거 커버리지 개선
3. 개선 버전 동결 후 새로운 잠금 URL셋으로 재평가
4. 최종 프론트 서버 배포와 잠금 URL E2E 결과 표시 확인
5. HTTPS·도메인·인증·rate limit을 포함한 운영 배포
6. API 키 교체와 운영 로그/비용 모니터링

## 팀 발표 역할 제안

- 문제·데이터: 뉴스 수치 주장을 왜 공식 통계로 검증해야 하는지, 조선일보 URL 데이터 설명
- 모델·검색: HCX, BGE-M3, reranker, Stage A
- 정형 좌표·검증: PostgreSQL, ITEM/OBJ, Stage B/C, KOSIS API, 안전 게이트
- 서비스·데모: FastAPI, FIFO GPU 큐, BFF, URL 입력 UI, 실제 결과
- 평가·한계: Top-k 정의, 개발 300건 결과, 낮은 E2E 커버리지와 일반화 한계
