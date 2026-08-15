# KOSIS 뉴스 팩트검증 파이프라인 일반화 위험 감사

- 감사 기준 브랜치: `codex/repro-baseline-20260727`
- 기준 커밋: `25a9dbb`
- 감사일: 2026-08-10
- 결론: 현재 파이프라인은 거짓 확정을 줄이는 방향으로 안전해졌지만, 개발 표본의 개별 실패를 규칙으로 반복 보정하면서 새 기사에 대한 재현율과 일반화 성능을 잃을 위험이 크다.

## 먼저 동결할 것

현재 실행 중인 holdout8 v8 결과가 나오기 전까지 검색·게이트·좌표 규칙을 추가하지 않는다. v8은 현재 규칙 묶음의 개발 기준선으로 보존한다. v8 결과를 확인한 뒤에도 같은 holdout8 실패 사례를 보고 규칙을 다시 조정하지 않고, 새 독립 holdout으로 다음 변경을 평가한다.

## 과적합 가능성이 높은 부분 5개

### 1. HCX 출력에 종속된 선행 READY 게이트

관련 파일:

- `prepare_kosis_mapping_input.py`
- `extract_hcx.py`
- `kosis_scope_gate.py`

현행 구조는 `measurement_usage`, `claim_domain_scope`, `measurement_binding_source`, `measurement_role`, 기간·주기·단위·semantic type을 검색 전에 검사한다. 특히 `claim_domain_scope != 국내공식통계`이면 명시적인 다른 분류는 검색 없이 REJECT될 수 있다.

`kosis_scope_gate.py`가 내용 기반 거부를 추가해 HCX 자기 신고를 그대로 믿는 문제를 일부 줄였지만, HCX가 실제 KOSIS 통계를 해외·기업·기타 통계로 잘못 분류한 경우를 KOSIS 후보 존재 여부로 복구하는 구조는 아니다.

구조 개선:

1. 명백한 비대상만 `REJECT`한다.
2. 애매한 scope·binding 오류는 `SCOPE_REVIEW`로 보존한다.
3. `SCOPE_REVIEW` 행에는 저비용 표 검색을 허용한다.
4. 공식 KOSIS 후보가 존재해도 즉시 READY로 올리지 않고, scope 재판정의 근거로만 사용한다.
5. 게이트 재현율과 검색 비용 증가를 함께 측정한다.

### 2. 수작업 가중치 중심 TBL_ID 검색 점수

관련 파일:

- `kosis_match_claims_to_index.py`
- `kosis_semantic_search.py`

현재 표 검색에는 국가·지역·연령·성별 축 감점, 주기 가점, anchor·품목 계열 가감점 등 사람이 정한 절대 점수가 누적된다. 이 점수는 확률이 아니며, 서로 다른 도메인에서 동일한 의미를 갖는다고 보장할 수 없다.

구조 개선:

1. 각 가감점을 `feature` 열로 분리해 평가 결과에 저장한다.
2. 총점만 남기지 말고 lexical rank, dense rank, reranker score, axis mismatch, periodicity match를 각각 기록한다.
3. 독립 validation에서 Top-1 정확도와 Recall@3/5/10, score margin을 기준으로 가중치와 cutoff를 보정한다.
4. 반도체·자동차·화장품 같은 품목명별 예외는 검색 코드에서 제거하고 공식 메타 alias/codebook 데이터로 이동한다.
5. 새 규칙은 독립 표본 여러 건에서 반복되는 오류일 때만 추가한다.

### 3. 확률처럼 보이는 2차 `mapping_confidence`

관련 파일:

- `kosis_validate_mapping_candidates.py`

`mapping_confidence`는 확률이 아니라 semantic score에서 unit·period·default penalty를 뺀 ranking score다. 그런데 기본 `ready_threshold=0.01`, `margin_threshold=0.10`을 사용해 READY 여부를 결정한다. 숫자의 통계적 의미가 명확하지 않다.

구조 개선:

1. 출력명을 `mapping_score`로 변경하고 기존 이름은 호환 alias로만 유지한다.
2. READY threshold는 독립 validation에서 정밀도 목표를 먼저 정한 뒤 선택한다.
3. threshold별 coverage–precision 곡선과 selective risk를 보고한다.
4. score margin도 고정값이 아니라 표본 분포에서 보정한다.
5. 보정 전에는 자동 READY 대신 `NEEDS_CONFIRMATION`을 기본값으로 둔다.

### 4. API 기술 유효성과 좌표 의미 일치의 잔여 혼합

관련 파일:

- `kosis_validate_mapping_candidates.py`
- `kosis_chroma_hybrid_search.py`
- `select_mcp_gold_200_two_stage_coordinates.py`
- `evaluate_mcp_gold_200_mapping.py`

현행 코드는 API 성공만으로 정답이라고 보지 않는 방향은 맞다. 그러나 metadata·response code·unit·period가 유효하고 semantic score가 높으면 READY가 될 수 있다. 전체 수출액과 ICT 수출액, 소비자물가와 근원물가처럼 모두 API가 정상 응답하는 의미 오매핑은 별도 exact gold 없이는 검출하기 어렵다.

구조 개선:

1. TBL_ID, ITEM, OBJ, period를 별도 단계로 채점한다.
2. `table_correct`, `item_correct`, `obj_correct`, `period_correct`, `full_coordinate_correct`를 독립 지표로 유지한다.
3. 2차 READY 정밀도는 full coordinate exact match를 정답 기준으로 계산한다.
4. API 성공률은 품질 지표가 아니라 운용 지표로 분리한다.
5. ITEM·OBJ 의미 라벨이 없는 행은 READY 정확도 분모에서 제외하고 coverage로 별도 보고한다.

### 5. 수치 유형을 충분히 반영하지 못하는 verdict 허용오차

관련 파일:

- `kosis_verify_claim_values.py`

현행 `judge()`는 주로 절대오차와 상대오차를 결합한다. extreme-error에서 rate-like 값을 %p로 별도 취급하지만, 최종 MATCH/REVIEW/MISMATCH 정책은 금액·인원·비율·증감률·지수의 기사 반올림 방식을 충분히 구분하지 않는다.

구조 개선:

1. `semantic_type × unit_dimension`별 tolerance policy를 분리한다.
2. 비율·증감률은 절대 %p 차이를 우선 사용한다.
3. 금액·인원은 기사 표기 자릿수에서 추정한 반올림 허용폭과 상대오차 상한을 함께 사용한다.
4. 지수는 지수 단위의 절대오차와 상대오차를 별도로 보정한다.
5. tolerance 정책은 locked verdict validation에서 확정하고 이후 변경 이력을 남긴다.

## 평가 구조 개편

새 독립 holdout 100~200건을 기존 규칙을 수정하지 않은 상태로 잠근다. 기존 MCP gold 200과 holdout8은 개발 및 회귀 데이터로 이미 사용됐으므로 최종 일반화 성능의 유일한 근거로 사용하지 않는다.

| 단계 | 독립 평가 지표 |
|---|---|
| HCX extraction | claim detection, value/unit/period/role 정확도 |
| 1차 gate | READY precision, READY recall, exclusion code별 오류율 |
| TBL retrieval | Top-1 accuracy, Recall@3/5/10, MRR |
| coordinate | ITEM exact, OBJ exact, period exact, full-coordinate exact |
| 2차 READY | precision, coverage, selective risk |
| verdict | MATCH/REVIEW/MISMATCH 정확도, 유형별 오차 |
| operation | API success, latency, retry count |

최종 실패는 반드시 다음 중 하나로 귀속한다.

```text
EXTRACTION → GATE → TABLE → ITEM → OBJ → PERIOD → VALUE_COMPARISON
```

## 규칙 추가 중단 기준

새 오류 한 건을 고치기 위한 상품명·표 ID·기사 표현 `if`는 추가하지 않는다. 다음 조건을 모두 만족할 때만 일반 규칙을 변경한다.

1. 서로 다른 기사·지표에서 같은 오류가 반복된다.
2. 원인을 입력 feature 또는 공식 메타 속성으로 설명할 수 있다.
3. 개발셋뿐 아니라 고정 validation에서도 개선된다.
4. 다른 도메인의 recall 또는 precision을 악화시키지 않는다.
5. 규칙보다 데이터 alias·codebook·보정 모델로 표현하는 편이 적절하지 않은지 검토한다.

## 다음 실행 순서

1. 진행 중인 v8을 끝까지 실행하고 결과를 보존한다.
2. v8 실패 사례를 보고 코드를 수정하지 않는다.
3. 새 기사 100~200건을 수집해 독립 holdout ID와 해시를 동결한다.
4. stage별 평가 파일과 지표를 먼저 생성한다.
5. 현행 v8을 그대로 새 holdout에 실행해 일반화 기준선을 만든다.
6. 이후 `retrieval-assisted scope`, score calibration, 유형별 tolerance를 각각 하나씩 A/B 평가한다.

## 멘토에게 설명할 핵심 문장

현재 시스템은 오답을 자동 확정하는 위험을 크게 줄였지만, 개발 사례 기반 규칙이 누적되어 일반화 성능은 아직 입증되지 않았다. 따라서 다음 단계는 규칙을 더 추가하는 것이 아니라 현재 버전을 동결하고, 완전히 새로운 독립 holdout에서 extraction·gate·table·coordinate·verdict를 단계별로 분리 평가하는 것이다.
