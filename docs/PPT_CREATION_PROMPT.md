# 팀 발표자료 제작용 프롬프트

아래 프롬프트를 PPT 제작 담당자의 AI 도구에 그대로 전달하세요.

---

당신은 AI/NLP 부트캠프 최종 프로젝트 발표자료를 만드는 기술 PM이자 데이터 스토리텔러다. 아래 GitHub `Poc` 브랜치를 먼저 읽고, 저장소의 문서와 JSON 근거만 사용해 10~12분 분량의 14~16장 발표자료 초안을 만들어라.

저장소: `https://github.com/rnwjdgus03/NLP_05-Team-Project-3/tree/Poc`

반드시 먼저 읽을 파일:

1. `README.md`
2. `docs/FINAL_POC_STATUS.md`
3. `docs/ARCHITECTURE.md`
4. `docs/EVALUATION.md`
5. `docs/RUNBOOK.md`
6. `freezes/v60_service_candidate_20260824_r1/freeze_manifest.json`
7. `freezes/v60_service_candidate_20260824_r1/evidence/dev300/coordinate_topk_multigold_summary.json`
8. `freezes/v60_service_candidate_20260824_r1/evidence/development_real_article/development_e2e_gate.json`

프로젝트 정의:

- 조선일보 기사 URL을 입력하면 기사 속 수치 기반 주장을 탐지한다.
- HCX로 indicator/item/OBJ/period/value/unit을 구조화한다.
- 관련 KOSIS 통계표는 lexical + BGE-M3 + reranker로 검색한다.
- ITEM·OBJ·주기 좌표는 PostgreSQL 공식 메타데이터에서 exact retrieval한다.
- 확인된 좌표만 KOSIS Open API로 조회해 MATCH / MISMATCH_REVIEW_REQUIRED / UNRESOLVED를 생성한다.
- 목표는 단순 기사 검색이 아니라 `검증 가능한 주장 탐지 → 공식 통계 조회 → 비교 검증 → 근거 설명`이다.

슬라이드 권장 구성:

1. 표지: 프로젝트명, 팀, 한 줄 가치 제안
2. 문제 정의: 뉴스 수치가 왜 검증하기 어려운가
3. 사용자 시나리오: 조선일보 URL 하나를 넣어 근거까지 받는 흐름
4. 기존 접근의 문제: 벡터 검색만으로 ITEM·OBJ 정확 코드를 고를 때 생긴 오답과 84만 좌표/대용량 DB 문제
5. 핵심 아이디어: 비정형 의미 검색과 정형 좌표 조회 분리
6. 전체 아키텍처 다이어그램
7. HCX 수치 주장 구조화와 READY/ENRICH/REJECT 게이트
8. Stage A: lexical + BGE-M3 + reranker 표 검색
9. Stage B/C: PostgreSQL ITEM·OBJ beam과 대상·기간·단위 재순위
10. KOSIS Open API 검증과 안전한 verdict 정책
11. 인프라·서비스: NVIDIA L4, PostgreSQL, FastAPI FIFO 큐, BFF/프론트
12. 평가 설계: 개발셋·블라인드·실제 URL E2E를 구분하고 Top-k 정의
13. v60 개발 300건 결과 차트
14. 실제 기사 데모 또는 화면 흐름
15. 실패 분석·한계·후속 개선
16. 결론과 팀 기여

수치 표기 규칙:

- ITEM Top-5 `77.3%`, 전체 좌표 Top-5 `74.3%`는 반드시 `개발 좌표 골드 300건`이라고 붙인다.
- Top-k는 “정답이 상위 k개 후보 안에 존재한 비율”이며 최종 팩트체크 정확도나 일반 뉴스 recall이 아니라고 설명한다.
- 실제 기사 개발 E2E는 READY 60건 중 VERIFIED_MATCH 6건, UNRESOLVED 54건이다.
- v60을 완성된 운영 모델이나 독립 테스트 검증 완료 모델이라고 표현하지 않는다.
- 이전 v31b 30건 수치는 작은 기준선일 뿐 v60 대표 성능으로 앞세우지 않는다.
- 별도 근거 파일이 저장소에 없는 숫자는 절대 만들지 않는다.
- 진행 중 URL E2E 중간 집계는 최종 결과처럼 사용하지 않는다.

시각화 요구:

- 아키텍처는 `URL → HCX → Gate → Stage A → Stage B/C → PostgreSQL/KOSIS API → Verdict` 흐름으로 그린다.
- Stage A의 “의미 후보 검색”과 PostgreSQL의 “정확 코드 검증”을 서로 다른 색으로 표현한다.
- 개발 300건 결과는 Top-1/3/5 묶은 막대그래프 두 계열(ITEM, 전체 좌표)로 표시한다.
- MATCH/UNRESOLVED는 원형그래프보다 6 대 54의 가로 누적 막대로 표시하고, 낮은 커버리지를 숨기지 않는다.
- UI 화면은 입력, 진행 단계, 판정, KOSIS 근거 위치에 주석을 단다.
- 한 슬라이드에 핵심 메시지 하나, 본문 5줄 이내, 코드 전문은 넣지 않는다.

보안 규칙:

- 서버 IP, DB 비밀번호, HCX/KOSIS/API 키, SSH 경로와 PEM 정보는 절대 노출하지 않는다.
- GitHub에 포함되지 않은 DB·인덱스를 첨부 파일처럼 표현하지 않는다.

출력 형식:

1. 먼저 전체 발표 스토리를 5문장으로 요약한다.
2. 슬라이드마다 `제목 / 한 줄 메시지 / 화면 구성 / 넣을 문구 / 발표자 노트 / 근거 파일`을 작성한다.
3. 마지막에 10분용 시간 배분표와 예상 질문 10개 및 답변을 작성한다.
4. 예상 질문에는 과적합, 블라인드 성능, UNRESOLVED가 많은 이유, PostgreSQL을 쓴 이유, BGE/reranker 선택, KOSIS API 한계, 서비스 비용을 포함한다.
5. 발표자가 개발 성능을 테스트 성능으로 잘못 말하지 않도록 마지막에 금지 표현과 권장 표현 표를 넣는다.

발표 톤은 “모든 뉴스를 자동 판정했다”가 아니라 “공식 통계 좌표를 근거로 검증 가능한 범위를 안전하게 자동화한 PoC”로 유지하라.

---
