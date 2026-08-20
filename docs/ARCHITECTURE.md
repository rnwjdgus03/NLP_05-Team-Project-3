# 파이프라인 아키텍처

## 1. 처리 단계

| 단계 | 주 실행 파일 | 방식 | 주요 출력 |
|---|---|---|---|
| 기사 정제 | `preprocess_news.py` | 규칙 + KSS | 문장, 문단, 제목, 발행일 |
| 문맥 구성 | `build_news_chunks.py`, `build_claim_contexts.py` | 규칙 기반 window | claim 주변·관련 문장 |
| span 탐지 | `detect_claim_spans_hcx.py` | HCX-007 | 넓은 수치 claim span |
| measurement 추출 | `extract_hcx.py` | HCX-007 + 후처리 규칙 | 지표, 대상, 값, 단위, 기간, 증감 기준 |
| 1차 게이트 | `prepare_kosis_mapping_input.py`, `kosis_scope_gate.py` | 결정적 규칙 | READY / ENRICH / REJECT, `in_ready` |
| 표 검색 | `run_kosis_coordinate_stage_a.py` | lexical + BGE-M3 + reranker | 표 후보 pool |
| 좌표 조합 | `run_kosis_coordinate_stage_b.py` | PostgreSQL exact metadata + dense | ITEM·OBJ beam pool |
| 좌표 선택 | `run_kosis_coordinate_stage_c.py` | cross-encoder reranker + hard gate | 좌표 Top-3/Top-5 |
| 실제값 검증 | `run_kosis_top5_verification.py` | KOSIS API + 캐시 + 단위/기간 비교 | MATCH / MISMATCH / UNRESOLVED |

## 2. HCX와 규칙의 역할

HCX-007은 문맥이 필요한 비정형 작업에만 사용한다.

- 수치 주장 span 탐지
- 하나의 claim에서 여러 measurement 분리
- indicator, item, value, unit, period, value type, change base 구조화

그 뒤 판정은 가능한 한 재현 가능한 규칙으로 수행한다.

- 기간·주기 정규화
- `value_type=증감률`과 `change_base=전월/전년동월`을 이용한 `mapping_type` 복구
- 기사 근거가 없는 item 제거
- 개별 기업 실적·시장 시점값·파생값·구성비 등 직접 대조 불가 주장 차단
- 주장 지표와 표 이름·통계 분야·기관·ITEM/OBJ 의미 충돌 차단

LLM이 `READY`를 직접 확정하지 않는다.

## 3. 두 READY의 구분

### 1차: `in_ready` / `mapping_gate`

`prepare_kosis_mapping_input.py`가 measurement 자체만 보고 판단한다.

- `mapping_gate=READY`, `in_ready=Y`: 표 검색에 투입 가능한 최소 계약 충족
- `mapping_gate=ENRICH`, `in_ready=N`: 기간·단위·범위·binding 등을 보강하면 회복 가능
- `mapping_gate=REJECT`, `in_ready=N`: KOSIS 직접 대조 범위 밖이거나 의미상 직접 검증 불가

현재 `in_ready`는 `mapping_eligible`의 호환 alias다. 1차 READY는 **정답 표를 찾았다는 뜻이 아니다**.

### 2차: `mapping_status` / `candidate_status`

검색 후 표와 좌표를 결합해 판단한다.

- 표명·통계 분야·기관이 주장과 일치하는가
- ITEM이 주장 지표와 같은 공표값인가
- OBJ가 지역·성별·연령·품목 등 대상을 정확히 표현하는가
- 단위, 주기, 기간, 직접값/파생값 의미가 일치하는가
- 1·2위 후보가 애매하지 않은가

하나라도 불충분하면 `READY`가 아니라 `REVIEW`, `NEEDS_CONFIRMATION`, `UNRESOLVED` 계열로 보류한다. 예를 들어 수입물가 주장에 소비자물가 표가 검색되면 API가 값을 반환해도 의미 불일치다.

### 최종 판정

2차 READY와 API 성공도 최종 정답을 자동 보장하지 않는다. 공식 좌표의 실제 값, 기간, 단위 환산을 확인한 뒤 `MATCH`, `MISMATCH`, `UNRESOLVED`를 낸다. 독립 잠금 골드 평가는 이 운영 판정과 별개다.

## 4. 검색 구성

Stage A는 세 검색 신호를 합친다.

- lexical: 정확한 통계 용어·기관·지역·품목 anchor에 강하고 빠르다.
- dense(BGE-M3): 기사 표현과 표명이 달라도 의미상 유사한 후보를 넓힌다.
- reranker: 합쳐진 후보를 claim-표 쌍 단위로 재정렬한다.

lexical만 사용하면 동의어·우회 표현 recall이 낮고, dense만 사용하면 비슷하지만 다른 조사표가 섞인다. 따라서 lexical을 제거하지 않고 dense recall과 hard semantic gate를 결합한다.

Stage B는 PostgreSQL에 적재한 표 메타데이터에서 실제 ITEM/OBJ 축만 사용한다. 벡터 DB는 후보 검색용이고 좌표의 존재 여부를 확정하는 DB가 아니다.

## 5. v24에서 채택한 변경

- 여러 측정값의 개별 기간을 claim 대표 기간으로 덮어쓰지 않는다.
- Stage B에서 표가 정상 좌표를 하나도 만들지 못해도 안전 게이트를 통과하는 검토용 좌표 1개를 낮은 우선순위로 보존한다.
- `table_slot_fallback=true`, `verification_review_required=true`를 기록한다.
- Stage A 표 계열별 슬롯은 A/B에서 무개선·회귀해 채택하지 않았다.

## 6. 현재 실패 경계

- 표명에 대표 지표명이 없는 고용 표는 Stage A에서 누락된다.
- 세부 대상어가 없는 소비자물가 주장에서 기본 `총지수` OBJ를 놓친다.
- 월 범위 `YYYY.MM` 정규화 오류가 좌표 성공도 최종 검증에서 막는다.
- MCP 장애와 메타데이터 불완전성은 최종 보류 사유로 남겨야 한다.

성능 수치는 `docs/results/`의 잠금 보고서를 기준으로 한다.
