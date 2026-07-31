# 2차 READY 회수 · 개정 빈티지 정책 (2026-07-31)

- 대상: `outputs/runs/contextual_top50_rolefix/` (진성 방식 contextual_top50_context_v2_8x3 / 07_mapping_jinsung)
- 입력: 443 measurement → 1차 READY 177 → 통계표 후보 885행(measurement당 Top-5)
- 원칙: **2차 READY 숫자를 무조건 늘리지 않는다.** 왜 자동 확정할 수 없는지 구분하고, 안전하게 회수 가능한 것만 살린다.
- 26분 전체 파이프라인 재실행 없음. 기존 validated 결과 재사용 + 소량 verify(13~20행)만 호출.

## 1. 진단 — 885 후보행을 177 measurement로 축약

`diagnose_validated_mappings.py` (노트북 진단 셀 로직 재사용 + 보강)

| mapping_status | 건수 |
|---|---:|
| MAPPING_FAILED | 90 |
| NEEDS_CONFIRMATION | 85 |
| READY | 2 |

| next_action | 건수 |
|---|---:|
| REVIEW_ITEM_OBJ_PERIOD | 77 |
| REVIEW_TABLE_RANKING | 51 |
| REVIEW_UNIT_OR_TABLE | 34 |
| ENRICH_PERIOD | 13 |
| VERIFY_ACTUAL_VALUE | 2 |

**후보행 사유(885)를 measurement 실패로 오독하면 안 된다**: NOT_EVALUATED 531 = 정확히 177×3 — 설계상 rank 3~5는 평가하지 않는다(LOW_PRIORITY). 실제 평가된 건 rank1~2의 354행뿐이다.

### 회수 유형 분류 (recovery_class)

| 유형 | 건수 | 의미 |
|---|---:|---|
| ITEM_OBJ_FIXABLE | 72 | 빈 응답·코드 불일치 → 조합/기간 수정 또는 저순위 폴백으로 회수 가능 |
| TOP1_GATE_ONLY | 38 | 실측 전부 통과 + rank1인데 상류 랭킹 게이트만 실패 |
| UNIT_FIX_ONLY | 30 | 단위 정규화만 실패 |
| RANK_ONLY | 19 | 순위만 애매 |
| PERIOD_FIX_ONLY | 18 | 기간 보강 필요 |

## 2. READY가 2건이었던 진짜 원인 — 이중 게이트

`kosis_validate_mapping_candidates.py`는 자체적으로 **공식 메타 코드 검증 + 실제 API 응답 + 단위·기간 정합**을 확인한다. 그런데 그 뒤에 상류(`kosis_match`)의 `candidate_status == READY`인 rank-1이 아니면 READY를 무조건 NEEDS_CONFIRMATION으로 강등한다.

실측: rank1 177건 중 상류 `candidate_status`가 READY인 건 **14건뿐**(REVIEW 72 / REJECT 91). 즉 하류 실측이 통과해도 상류의 보수적 판단이 덮어쓰는 **중복 게이트**가 병목이었다.

## 3. 안전 회수 — 기준 완화가 아니라 중복 제거 + 의미 가드

`recover_downstream_validated.py` (API 호출 0회)

**회수 조건(모두 필요)**
1. `mapping_status=NEEDS_CONFIRMATION` && 사유 = "not decisive rank-1"
2. `candidate_rank == 1`
3. 상류 `candidate_status != REJECT` (의미 실패는 존중)
4. item/obj 메타 유효 + `response_code_valid` + `unit_valid` + `period_valid` 전부 True
5. 상류 1·2위 점수차 ≥ max(5, 1%) (동점 표는 사람 확인 유지)
6. **의미 가드**: claim의 품목이 있는데 선택된 OBJ/ITEM 이름과 무관하면 회수 금지

**의미 가드가 필요했던 이유(실측)** — 기술적으로 유효(API 응답 정상)한데 의미가 전혀 다른 좌표가 선택된 사례:

| claim 품목 | 선택된 OBJ |
|---|---|
| 농수산식품 수출 | 건조기(농산물용의 것) |
| 반도체 수출 | 인산에스테르 및 그 염(락토포스페이트 포함)… |
| 석유화학 수출 | 기타 화학제품 및 조제품 |

가드 없이는 20건이 회수됐지만 그중 7건이 이런 오매핑이었다 → 가드 적용 후 **13건**.

| 단계 | measurement READY |
|---|---:|
| 원본 | 2 |
| 회수 v1 (중복 게이트 제거) | 20 |
| **회수 v2 (+의미 가드)** | **13** |

## 4. 개정 빈티지 정책 (REVISION_VINTAGE_RISK)

`kosis_verify_claim_values.py`에 추가. **모든 불일치를 자동 보류하지 않기 위해 4조건을 모두 요구한다.**

1. 파생 증감률 판정 (`rate_from_level` 또는 `value_type=증감률`) — 수준값 개정이 계산된 증감률을 크게 바꾸므로 개정 민감도가 가장 높다
2. 기사 작성일 파싱 가능
3. **판정에 사용된 KOSIS 행의 `LST_CHN_DE`(개정일) > 기사일**
4. 관측 시점이 기사 시점보다 과거 또는 동월 (미래 기간은 별개 문제)

충족 시 `불일치` → `판정보류`, `verdict_code=REVISION_VINTAGE_RISK`, 감사 컬럼 `kosis_lst_chn_de` 기록.

**주의(실행 중 발견)**: `candidates_with_meta.csv`에는 `date`(기사일) 컬럼이 없어 정책이 발동하지 않는다. `05_hcx_measurements_kosis_ready.csv`에서 기사일을 조인해 verify 입력에 넣어야 한다.

## 5. verdict 결과 비교

| 실행 | 행 | 일치 | 불일치 | 판정보류 | 판단불가 |
|---|---:|---:|---:|---:|---:|
| 원본 (Drive) | 2 | 0 | 2 | 0 | 0 |
| 회수 v1 (기사일 없음) | 20 | 3 | 13 | 0 | 4 |
| 회수 v1 + 기사일 | 20 | 3 | 5 | **8** | 4 |
| **최종 v2 (의미 가드 + 기사일)** | **13** | **3** | **2** | **5** | 3 |

최종 verdict_code: MATCH 3 / REVISION_VINTAGE_RISK 5 / VALUE_MISMATCH 2 / ACTUAL_DERIVATION_FAILED 3

**요청된 산업생산지수 2건**(DT_1JH20202, 기사일 2025-01-02, 개정일 2026-02-25)은 의도대로 `판정보류(REVISION_VINTAGE_RISK)`로 전환되어, 뉴스가 틀렸다고 확정하지 않는다.

## 6. 남은 개선 지점

| 지점 | 근거 | 조치 |
|---|---|---|
| ITEM_OBJ_FIXABLE 72건 | rank1~2 빈 응답, rank3~5 미평가 | `--fallback-ranks` 실행 (API 필요) |
| UNIT_FIX_ONLY 30건 | 단위 정규화만 실패 | 단위 별칭 보강 |
| PERIOD_FIX_ONLY 18~19건 | 기간 미충족 | 기간 보강 |
| 상류 OBJ 선택 품질 | 품목 claim에 무관한 세부 품목 선택 | match 단계 품목 매칭 강화 (의미 가드는 하류 방어일 뿐) |

## 7. 산출물 · 코드 · 테스트

**결과 파일** (`outputs/runs/contextual_top50_rolefix/`)
- `05_hcx_measurements_kosis_validated_mappings.csv` (Drive 원본 885행)
- `05_hcx_measurements_kosis_validated_recovered.csv` / `_recovered_v2.csv` (회수 v1/v2)
- `diagnosis_before.csv` / `diagnosis_after_recovery.csv` / `diagnosis_after_recovery_v2.csv` (177행 진단)
- `verify_input_recovered20.csv` / `_dated.csv` / `verify_input_recovered_v2.csv`
- `05_hcx_measurements_kosis_verified_recovered.csv` / `_dated.csv` / `_final.csv`

**코드**
- 신규: `diagnose_validated_mappings.py`, `recover_downstream_validated.py`
- 수정: `kosis_verify_claim_values.py` (개정 정책 + `kosis_lst_chn_de` 컬럼)
- 수정: `kosis_validate_mapping_candidates.py` — `--trust-downstream-validation`, `--fallback-ranks` (**둘 다 기본 off**, 기존 재현성 보존)

**테스트**: 신규 5파일 25개 추가, 전체 **212 passed**
- `test_diagnose_validated_mappings.py`, `test_revision_vintage_risk.py`,
  `test_validate_fallback_ranks.py`, `test_recover_downstream_validated.py`,
  `test_recover_item_semantics.py`
