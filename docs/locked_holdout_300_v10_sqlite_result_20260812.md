# 잠금 홀드아웃 300 v10 SQLite 실행 결과

## 실행 무결성

- 결과 ZIP: `locked_holdout_300_v10_sqlite_gpu_results.zip`
- SHA-256: `b22ca3f10d3204adff91e629c25c4d9bd5af22218de0b9e375d0404f98f98357`
- freeze: `locked300-v10-sqlite-20260811`
- 기사: 300건
- gold 접근: 없음
- 좌표 Chroma 사용: 없음
- 구조: 표 벡터 검색 → SQLite exact resolver → KOSIS API
- BGE-M3 표 인덱스: 107,138개 표, 1,024차원
- SQLite 메타데이터: 표 107,138개, ITEM 3,466개, 축 1,625개, 축 값 97,748개

파이프라인은 중단 없이 마지막 결과 ZIP 생성까지 완료됐다. 이 결과는 v10의 gold-blind 예측 동결본이다.

## 단계별 결과

| 단계 | 건수 | 기준 대비 비율 |
|---|---:|---:|
| 기사 | 300 | 100% |
| claim context | 1,489 | 기사당 평균 4.96개 |
| HCX measurement | 3,303 | claim당 평균 2.22개 |
| KOSIS READY 입력 게이트 통과 | 178 | measurement의 5.39% |
| SQLite 좌표 선택 | 178 | 게이트 통과 입력의 100% |
| API 이후 READY | 9 | 좌표 입력의 5.06% |
| NEEDS_CONFIRMATION | 37 | 좌표 입력의 20.79% |
| MAPPING_FAILED | 132 | 좌표 입력의 74.16% |
| 최종 verdict 생성 | 9 | 전체 measurement의 0.27% |
| READY가 하나 이상인 기사 | 8 | 전체 기사의 2.67% |

기사 상태는 `NO_READY` 270건, `HAS_READY` 8건, `NO_MEASUREMENT` 22건이다. 전체 measurement 상태는 `NOT_READY` 3,125건, `MAPPING_FAILED` 132건, `NEEDS_CONFIRMATION` 37건, `READY` 9건이다.

## 최종 verdict

| verdict | 건수 |
|---|---:|
| 일치 | 0 |
| 불일치 | 2 |
| 판단불가 | 7 |

이 숫자는 정확도 평가 결과가 아니다. 잠금 기사 300건에 대한 별도 실제 좌표 골드가 아직 없기 때문에 Recall@1/5/10, ITEM exact, OBJ exact, full-coordinate exact, READY precision, verdict accuracy를 계산할 수 없다.

또한 `불일치` 2건은 기사 오류의 증거로 사용할 수 없다. 두 건 모두 잘못된 표 선택과 `만원 → 원` 환산 오류가 섞여 있다.

## 확인된 병목

### 1. API 응답 성공이 의미적으로 올바른 표를 보장하지 않는다

API가 실제 행을 반환하고 단위·기간 형식이 맞으면 잘못된 표도 READY로 진입했다.

- `1인당 PGDI` → 건강보험 `급여비용` 표
- `1인당 국민소득` → 건강보험 `급여비용` 표
- `우리나라 총인구` → `인구밀도` 표
- `자기 집을 소유한 가구의 평균 자산` → `가구의 연간 경상소득 평균` 표

따라서 SQLite/API exact validation은 코드 조합의 존재 여부는 확인하지만 통계 개념의 동일성까지 보장하지 않는다.

### 2. OBJ 축의 strict match가 READY 필수조건이 아니다

READY 9건 모두 `sqlite_obj_strict_match=N`이었다.

- `남편이 연상` 주장에 남편·아내 연령 축 모두 `계`가 선택됐다.
- `영아돌연사증후군 사망자 수` 주장에 사망원인 축 `계`가 선택됐다.

대상 개념이 indicator 문장 안에 포함된 경우에도 실제 OBJ 축 값으로 강제 연결해야 한다.

### 3. 단위 호환과 환산에 구현 결함이 있다

- SQLite 좌표 선택에서는 claim 단위 `명`과 ITEM 단위 `명/㎢`가 호환으로 통과했다.
- 값 검증기의 `unit_factor('만원', '원')`은 현재 `1.0`을 반환한다. 올바른 값은 `10,000.0`이다.
- `천원 → 원`은 `1,000.0`으로 정상 처리된다.

현재의 금액 불일치 verdict는 단위 환산 수정 전에는 사용할 수 없다.

### 4. READY 이후 값 검증 경로가 완결되지 않았다

9건의 verdict code는 다음과 같다.

- `MAPPING_TYPE_UNSUPPORTED`: 2건
- `ACTUAL_DERIVATION_FAILED`: 4건
- `LIKELY_MISMAPPING`: 1건
- `VALUE_MISMATCH`: 2건

API validation 단계의 `selected_combination`에는 실제 `matching_rows`가 있는데도, 값 검증 단계가 다시 조회한 결과에서 4건은 `조회 데이터 없음`이 됐다. 검증 단계가 이미 검증된 API 응답을 재사용하지 않고 재조회하면서 좌표·요청 파라미터가 달라지는지 점검해야 한다.

### 5. 결과 provenance 표기가 잘못됐다

결과 manifest의 `pipeline_version`이 `locked300-v9-20260810`으로 기록됐다. 실제 freeze와 실행 구조는 v10이다. 원인은 `export_locked_holdout_300_predictions.py`의 버전 상수가 v9로 고정돼 있기 때문이다. 결과 해시는 그대로 보존하되 다음 실행부터 버전을 CLI 인자로 전달해야 한다.

## 판정

v10의 성과는 Chroma 좌표 DB를 제거하고 SQLite exact resolver와 KOSIS API를 연결한 전체 경로가 300개 기사에서 실제로 완주했다는 점이다. 그러나 최종 자동판정 커버리지는 measurement 기준 0.27%이고 READY 의미 정밀도에도 명확한 문제가 있다.

따라서 v10은 **아키텍처 통합 성공, 자동 팩트 판정 성능 미달** 단계다. `불일치` 2건을 기사 오보로 표시하거나 현재 결과를 프론트엔드 최종 verdict로 노출하면 안 된다.

## 다음 변경 순서

1. v10 ZIP과 prediction SHA를 변경하지 않고 동결한다.
2. `만원` 등 단위 배율과 복합단위 차원 검사를 수정한다.
3. READY 전 `indicator ↔ tbl_name/ITEM` 개념 완전성 게이트를 강화한다.
4. indicator 안의 성별·연령·사망원인·지역·품목 표현을 OBJ target으로 승격하고 strict axis match를 READY 필수조건으로 둔다.
5. 검증된 `matching_rows`를 값 비교에 직접 전달해 중복 API 재조회를 제거한다.
6. exporter의 pipeline version을 인자로 바꾸고 v10/v11 provenance 테스트를 추가한다.
7. 잠금 300건은 코드 조정에 재사용하지 않고, 별도 개발 세트로 위 수정들을 검증한 후 새 미사용 홀드아웃에서 다음 버전을 평가한다.
