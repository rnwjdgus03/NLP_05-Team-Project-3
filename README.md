# KOSIS 뉴스 수치 팩트체크 PoC

조선일보 기사 URL을 입력하면 기사 안의 수치 주장을 추출하고, KOSIS 공식 통계의 표·ITEM·OBJ·기간 좌표를 찾아 실제 값과 비교하는 AI 기반 사실검증 PoC입니다.

현재 발표·서비스 후보는 `v60_service_candidate_20260824_r1`입니다. 개발 300건 목표를 통과한 동결 후보이며, **일반 뉴스 전체에서 검증된 완성 모델이나 독립 테스트 성능으로 해석하면 안 됩니다.**

## 현재 완료 범위

- URL 입력형 프론트/BFF와 FastAPI 단일 작업 큐
- HCX 수치 주장 구조화
- BGE-M3 의미 검색과 reranker 기반 KOSIS 표 후보 검색
- PostgreSQL 기반 ITEM·OBJ·주기 정확 조회
- KOSIS Open API 공식값 비교
- 불확실한 좌표에서 자동 오판을 막는 안전 게이트
- v60 공개용 동결 스냅샷과 개발평가 근거

## v60 개발평가

| 지표 | Top-1 | Top-3 | Top-5 |
|---|---:|---:|---:|
| 표·ITEM 적중률 | 52.3% | 69.7% | **77.3%** |
| 전체 좌표 적중률 | 49.3% | 66.7% | **74.3%** |

- 평가 단위: 개발 좌표 골드 300개 주장
- 누락 예측: 0건
- 개발 중단 기준: ITEM Top-5 75%, 전체 좌표 Top-5 70%
- 결과: 두 기준 모두 통과

여기서 Top-k는 정답 좌표가 상위 k개 후보 안에 들어왔는지를 뜻합니다. 최종 판정 정확도나 일반 뉴스 전체 커버리지가 아닙니다. 개발 데이터로 여러 차례 개선한 결과이므로 과적합 가능성이 있으며, 완전 분리 블라인드 결과를 대표 성능으로 추가 공개하기 전까지 `개발 성능`으로만 표기합니다.

실제 기사 개발 E2E에서는 READY 주장 60개 중 `VERIFIED_MATCH` 6개, `UNRESOLVED` 54개였습니다. 잘못된 자동 판정보다 보류를 우선하는 정책이라 검증 커버리지가 낮습니다.

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
├─ freezes/v60_service_candidate_20260824_r1/  # 공개용 v60 코드·근거 스냅샷
├─ service_api/                                 # 안정화된 FastAPI 서비스 골격
├─ frontend_server/                             # URL 입력 BFF/UI 골격
├─ evaluation/v31b_blind/                       # 이전 소규모 블라인드 기준선
└─ docs/                                        # 구조·평가·운영·발표 문서
```

`freezes/v60...`은 런타임 원본에서 키·DB·인덱스·캐시를 제거한 **공개용 스냅샷**입니다. 따라서 공개 스냅샷의 파일 트리 SHA는 서버 런타임의 엔진 SHA와 다를 수 있으며, 원본 정체성은 `freeze_manifest.json`과 `PUBLICATION_MANIFEST.json`에 기록돼 있습니다.

## Git에 포함하지 않는 자산

- `.env`, API 키, PEM/SSH 키
- PostgreSQL 스냅샷과 비밀번호
- BGE 임베딩(`embeddings.npy`)과 대용량 인덱스
- 모델 캐시, 실행 중 결과, 원본 `chosun_full.csv`

서버 런타임에는 별도로 BGE-M3 표 인덱스 107,138건, PostgreSQL KOSIS 메타데이터, HCX/KOSIS 키가 필요합니다.

## 문서

- [아키텍처](docs/ARCHITECTURE.md)
- [평가 결과와 해석](docs/EVALUATION.md)
- [운영·재현 안내](docs/RUNBOOK.md)
- [최종 PoC 상태](docs/FINAL_POC_STATUS.md)
- [발표자료 제작 프롬프트](docs/PPT_CREATION_PROMPT.md)

## 보안·판정 원칙

- 좌표·기간·단위가 확인되지 않으면 `VALUE_MISMATCH`를 확정하지 않습니다.
- 불확실한 결과는 `UNRESOLVED`로 보류합니다.
- 브라우저에는 외부 API 키를 전달하지 않고 BFF가 서버에서 주입합니다.
- URL 수집기는 사설·loopback·link-local 주소를 차단합니다.
- 공개 발표에서 개발셋 Top-k와 최종 판정 정확도를 혼용하지 않습니다.
