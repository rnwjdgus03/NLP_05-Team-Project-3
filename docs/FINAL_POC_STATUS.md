# 최종 PoC 상태 공유

## 한 줄 요약

조선일보 기사 URL에서 수치 주장을 추출해 KOSIS 공식 좌표와 값을 대조하는 전체 서비스가 연결됐습니다. v64는 최종 PoC 데모 후보이며, 신규 v65 blind100 검색 성능은 ITEM Top-5 58%, 좌표 Top-5 54%로 목표에 미달했지만, v66 실제 URL50 서비스 QA는 사전 준비도 기준을 모두 통과했습니다.

## 완료

- 기사 URL 입력 및 서버측 본문·수치 문장 추출
- HCX structured output
- KOSIS-ready READY / ENRICH / REJECT 게이트
- lexical + BGE-M3 + reranker Stage A 표 검색
- PostgreSQL ITEM·OBJ·기간 exact retrieval
- Stage B 좌표 beam과 Stage C 대상·기간·단위 재순위
- KOSIS Open API 실제값 검증
- MATCH / REVIEW / UNRESOLVED 안전 판정
- FastAPI FIFO 작업 큐와 프론트 BFF/UI
- v64 동결 및 엔진 SHA 감사
- 신규 v65 blind100 일회 평가
- 조선일보 원본 기반 v66 잠금 URL50 E2E
- 공개용 코드·평가 근거·운영 문서 정리
- v64 API `/readyz` 및 최종 프론트 HTTP 200 스모크 확인

## 최종 수치

### 개발

- v60 개발 300건 ITEM Top-5: 77.3%
- v60 개발 300건 전체 좌표 Top-5: 74.3%
- v64 개발 600건 재대입 ITEM Top-5: 90.3%
- v64 개발 600건 재대입 전체 좌표 Top-5: 90.2%
- 90%대 수치는 지도형 cache를 같은 개발 600건에 평가한 `DEVELOPMENT_ONLY_NOT_BLIND` 결과

### 독립 blind100

- v65 ITEM Top-5: 58%
- v65 전체 좌표 Top-5: 54%
- 예측 누락: 0건
- 사전 기준 75%·70%: FAIL
- 평가 뒤 v64 재튜닝: 하지 않음

### 실제 URL50 E2E

- 기사 수집 성공률: 50/50 (100%)
- 작업 성공률: 50/50 (100%)
- 추출 측정값: 393개
- KOSIS-ready 측정값: 96개
- 공식 근거 선택: 11/96 (11.46%)
- 공식 근거 기사: 5건
- 최종 판정: MATCH 11개, UNRESOLVED 252개
- 작업시간 p50 / p95 / max: 87.78초 / 290.36초 / 386.49초
- 단일 v64 엔진 SHA: 50/50 확인
- 서비스 준비도: PASS
- `promotion_allowed`: true

## 해석

- 개발 90%대 수치를 테스트 또는 일반화 성능으로 말하지 않습니다.
- 대표 일반화 검색 성능은 v65 blind100의 58%·54%입니다.
- v66 URL50 PASS는 서비스 실행 안정성과 최소 근거 커버리지 통과입니다.
- `UNRESOLVED`는 오답이나 정답이 아니라 안전한 자동 판정 보류입니다.
- 따라서 이 결과는 운영 완성품이 아니라, 실제 URL을 끝까지 처리하고 한계를 측정한 PoC 완성 결과입니다.

## 발표·시연 전 남은 일

1. 발표 슬라이드에 개발·블라인드·E2E 지표를 분리 표기
2. 데모용 URL과 예상 소요시간 준비
3. 발표 당일 API `/readyz`와 프론트 상태 재확인
4. HTTPS·도메인·인증·rate limit은 운영 전환 과제로 명시
5. 시연 종료 후 GPU 인스턴스 중지 및 키 교체

## 팀 발표 역할 제안

- 문제·데이터: 뉴스 수치 주장을 왜 공식 통계로 검증해야 하는지, 조선일보 원본 URL 데이터 설명
- 모델·검색: HCX, BGE-M3, reranker, Stage A
- 정형 좌표·검증: PostgreSQL, ITEM/OBJ, Stage B/C, KOSIS API, 안전 게이트
- 서비스·데모: FastAPI FIFO GPU 큐, BFF, URL 입력 UI, v66 실제 결과
- 평가·한계: Top-k 정의, 개발 재대입, 신규 blind100, URL50 서비스 QA를 구분