# KOSIS 뉴스 수치 팩트체크 PoC

조선일보 기사 URL을 입력하면 기사 안의 수치 주장을 추출하고, KOSIS 공식 통계의 표·ITEM·OBJ·기간 좌표를 찾아 실제 값과 비교하는 AI 기반 사실검증 PoC입니다.

최종 PoC 데모 후보는 `v64_candidate_20260824_r1`입니다. 이 버전은 개발 600건 재대입 평가에서 ITEM Top-5 90.3%, 전체 좌표 Top-5 90.2%였지만, 완전히 분리한 신규 v65 blind100에서는 각각 58%, 54%였습니다. 반면 조선일보 원본에서 잠근 v66 URL50 실서비스 QA는 수집·작업 성공률 100%, 공식 근거 선택률 11.46%, 근거 기사 5건으로 사전 서비스 준비도 기준을 모두 통과했습니다. **개발 성능, 블라인드 검색 성능, 실제 URL 서비스 QA는 서로 다른 지표이며 하나의 정확도로 합쳐 해석하면 안 됩니다.**

## 현재 완료 범위

- URL 입력형 프론트/BFF와 FastAPI 단일 작업 큐
- HCX 수치 주장 구조화
- BGE-M3 의미 검색과 reranker 기반 KOSIS 표 후보 검색
- PostgreSQL 기반 ITEM·OBJ·주기 정확 조회
- KOSIS Open API 공식값 비교
- 불확실한 좌표에서 자동 오판을 막는 안전 게이트
- v64 동결 스냅샷, v65 독립 blind100, v66 URL50 서비스 감사 근거

## 검색·좌표 평가

| 지표 | Top-1 | Top-3 | Top-5 |
|---|---:|---:|---:|
| 표·ITEM 적중률 | 52.3% | 69.7% | **77.3%** |
| 전체 좌표 적중률 | 49.3% | 66.7% | **74.3%** |

- 평가 단위: 개발 좌표 골드 300개 주장
- 누락 예측: 0건
- 개발 중단 기준: ITEM Top-5 75%, 전체 좌표 Top-5 70%
- 결과: 두 기준 모두 통과

위 표는 v60 개발 좌표 골드 300건 결과입니다. 이후 v64는 별도 개발 600건에 지도형 exact mapping cache를 적용해 같은 600건 재대입 평가에서 ITEM Top-5 90.3%, 전체 좌표 Top-5 90.2%를 기록했습니다. 이는 `DEVELOPMENT_ONLY_NOT_BLIND`이며 과적합 가능성이 큰 재대입 수치입니다.

동결 뒤 한 번만 실행한 v65 신규 table-disjoint blind100에서는 ITEM Top-5 58%, 전체 좌표 Top-5 54%였습니다. 사전 목표 75%·70%에는 실패했으며, 이 결과를 보고 v64 규칙을 다시 수정하지 않았습니다. 따라서 대표 일반화 수치는 이 58%·54%이고, 90%대 개발 수치는 일반화 성능으로 발표하지 않습니다.

최종 v66 잠금 조선일보 URL50에서는 기사 수집과 작업이 모두 50/50 성공했습니다. KOSIS-ready 측정값 96개 중 공식 근거 11개가 선택되어 근거 선택률은 11.46%였고, 근거가 나온 기사는 5건입니다. 작업시간 p95는 290.36초였으며 단일 v64 엔진 SHA가 50건 모두에서 확인돼 서비스 준비도 감사가 PASS, promotion_allowed=true로 끝났습니다. UNRESOLVED 252개는 오답이 아니라 자동 판정 보류입니다.

## 전체 흐름

```text
조선일보 기사 URL
  → BFF 기사 HTML 수집·본문/수치 문장 추출
  → HCX structured measurement
  → READY / ENRICH / REJECT 게이트
  → Stage A: lexical + BGE-M3 + reranker 표 후보
  → Stage B: PostgreSQL ITEM·OBJ 좌표 beam
  → Stage C: 대상·기간·단위 기반 좌표 재순위
  → PostgreSQL preflight
  → KOSIS Open API 공식값 조회
  → MATCH / MISMATCH_REVIEW_REQUIRED / UNRESOLVED
```

핵심 설계는 비정형 의미 검색과 정형 좌표 조회의 분리입니다. 벡터 검색은 “어떤 통계표와 관련 있는가”를 찾고, PostgreSQL은 “그 표에 실제 ITEM·OBJ·주기 코드가 존재하는가”를 확인합니다.

## 저장소 구성

```text
.
├─ freezes/v64_candidate_20260824_r1/          # 최종 PoC 동결 엔진
├─ service_api/                                 # 안정화된 FastAPI 서비스 골격
├─ frontend_server/                             # URL 입력 BFF/UI 골격
├─ evaluation/v31b_blind/                       # 이전 소규모 블라인드 기준선
├─ evaluation/generalization_audit/              # 공개용 일반화 감사 집계
├─ evaluation/v60_locked_url50/                  # 잠금 URL50 승격 감사
├─ evaluation/v65_blind100/                      # 신규 독립 blind100 근거
├─ evaluation/v66_locked_url50/                  # 최종 실제 URL50 서비스 감사
└─ docs/                                        # 구조·평가·운영·발표 문서
```

`freezes/v64...`에는 키·DB·인덱스·API 캐시가 없으며, 서버에서 실제 사용한 엔진 트리 SHA `760033bb...a7d64`를 manifest와 감사 파일로 확인할 수 있습니다. 기존 `freezes/v60...`은 이전 공개 기준선으로 보존합니다.

## Git에 포함하지 않는 자산

- `.env`, API 키, PEM/SSH 키
- PostgreSQL 스냅샷과 비밀번호
- BGE 임베딩(`embeddings.npy`)과 대용량 인덱스
- 모델 캐시, 실행 중 결과, 원본 `chosun_full.csv`

서버 런타임에는 별도로 BGE-M3 표 인덱스 107,138건, PostgreSQL KOSIS 메타데이터, HCX/KOSIS 키가 필요합니다.

## 문서

- [아키텍처](docs/ARCHITECTURE.md)
- [평가 결과와 해석](docs/EVALUATION.md)
- [일반화 감사](docs/GENERALIZATION_AUDIT.md)
- [운영·재현 안내](docs/RUNBOOK.md)
- [최종 PoC 상태](docs/FINAL_POC_STATUS.md)
- [발표자료 제작 프롬프트](docs/PPT_CREATION_PROMPT.md)

## 보안·판정 원칙

- 좌표·기간·단위가 확인되지 않으면 `VALUE_MISMATCH`를 확정하지 않습니다.
- 불확실한 결과는 `UNRESOLVED`로 보류합니다.
- 브라우저에는 외부 API 키를 전달하지 않고 BFF가 서버에서 주입합니다.
- URL 수집기는 사설·loopback·link-local 주소를 차단합니다.
- 공개 발표에서 개발셋 Top-k와 최종 판정 정확도를 혼용하지 않습니다.
