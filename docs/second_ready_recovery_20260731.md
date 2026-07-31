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

---

# 후속 (2026-07-31 오후) — 평가 집합 정정과 이중 게이트 해제

앞 절의 수치는 **1차 READY 177 건** 위에서 잰 것이다. 그 집합에 KOSIS 로 검증할 수
없는 주장이 섞여 있었음이 이후 확인되어, 집합을 다시 짜고 게이트를 고쳤다.

## 1. 평가 집합 정정 (177 → 134)

실버 대조(후보 좌표 5~12개를 전부 KOSIS 조회)에서 값이 재현된 건은 8건뿐이었고,
`NO_MATCH` 다수가 비트코인 시세·나스닥 지수·롤렉스 판매가·정부 전망치·세율처럼
**KOSIS 에 존재할 수 없는 값**이었다.

원인은 게이트가 `measurement_usage` / `claim_domain_scope` 라는 **HCX 자기 신고
라벨만** 보고 독립 검증이 없었던 것. `kosis_scope_gate` 로 주장 내용을 직접 판정해
43건을 제외했다(**오탐 0** — 값이 재현된 12건은 모두 유지).

집합은 `evaluation_set_v2_manifest.json` 에 입력·출력 sha256 과 규칙 스냅샷을 박아
잠갔다. 규칙을 고치면 manifest 가 달라지므로 "어떤 집합에서 잰 숫자냐"를 추적할 수 있다.

## 2. 이중 게이트 해제

validate 는 공식 메타 코드 + 실제 API 응답 + 단위·기간을 **이미 독립 검증**하는데,
그 뒤에 상류 표 후보가 rank-1 READY 가 아니라는 이유로 다시 강등했다.
같은 불확실성을 두 번 요구하는 중복 게이트였다.

기본 동작을 뒤집고 `--require-upstream-ready` 로 옛 동작을 복원할 수 있게 했다.
안전 조건(rank1 · 상류 REJECT 제외 · 실측 전항목 통과 · 의미 가드 · 점수 마진)은 그대로다.

## 3. 해제 직후 드러난 오매핑과 이중 방어

READY 12건을 검수하니 4건이 오매핑이었고 **2건이 자동 '불일치'까지 갔다.**
팩트체크에서 맞는 기사를 틀렸다고 하는 것이 최악이므로 두 겹으로 막았다.

| 방어 | 내용 |
|---|---|
| ① 집계 규칙 (확정 단계) | 주장이 세부 대상을 말하지 않으면 좌표도 집계값이어야 한다. `무역수지→objL1=건설`, `물가 상승률→objL1=자가주거비` 차단 |
| ② 극단 오차 (판정 단계) | 차이가 비상식적이면 `불일치` 대신 `LIKELY_MISMAPPING`(판단불가). 무역흑자 518억달러를 수입액 6320억달러에 대면 1,120% |

**②의 기준을 값 종류별로 갈랐다.** 증감률은 분모가 작아 상대오차가 쉽게 폭발하므로
(8.2% vs 42.5% = 418%) 상대오차 대신 **절대 %p** 로 본다. 실제로 계절조정지수
증감률 2건이 차이율 253%·472% 였지만 절대 차이는 1.01%p·0.94%p 로 작아
`REVISION_VINTAGE_RISK` 판정 기회를 지켰다.

또한 의미 가드가 `recover_downstream_validated.py` 에 **복사돼 있어** validate 쪽만
고쳤을 때 회수 경로에 반영되지 않았다. 구현을 하나로 합치고, 두 경로가 어긋나면
실패하는 테스트를 넣었다(`test_recovery_path_uses_the_same_guard_as_validate`).

## 4. 최종 결과 (확정 집합 134 기준)

| | 해제 전 | 해제 후 |
|---|---|---|
| READY | 2 | **9** |
| NEEDS_CONFIRMATION | 72 | 65 |
| MAPPING_FAILED | 60 | 60 |
| API-valid | 88 | 88 |

verdict 9건: **일치 3 / 판정보류 5(전부 REVISION_VINTAGE_RISK) / 판단불가 1(LIKELY_MISMAPPING) / 불일치 0**

일치 3건의 차이율은 0.028% · 0.037% · 0.131% 로 정밀하다.

## 5. 남은 한계

1. **골드가 없다.** 위 9건이 '맞는 좌표'라는 보증은 없다. 실버로 값까지 재현된 건은 1건뿐이다.
2. 확정 집합 134 에도 오염이 남아 있다. tier 별 좌표 재현율이
   `NEAR_MISS 61.5%` vs `NO_MATCH 28.9%` 로 갈리므로, 기업별 실적·일별 시세·부처 백서 등
   범위 밖 주장이 더 있다.
3. 게이트는 문장 단위라 전망 문장에 섞인 실적치가 함께 제외될 수 있다(실측 오탐은 0).
4. READY 9/134 = 6.7%. 자동 확정률 자체는 여전히 낮다.

**테스트**: 전체 **398 passed**
- 신규: `test_kosis_scope_gate.py`, `test_prepare_scope_gate_wiring.py`,
  `test_lock_evaluation_set.py`, `test_dual_gate_release.py`, `test_mismapping_guards.py`,
  `test_build_silver_coordinates.py`, `test_export_labeling_packet.py`,
  `test_diagnose_claim_quality.py`

---

## 6. 최종 상태 (DERIVED_INDICATOR 게이트 반영 후)

무역흑자 오매핑의 원인을 추적한 결과 **능력의 공백**이 드러났다.

- 관세청 수출입 통계(`DT_1R11001_FRM101`)에는 **수출액·수입액만 있고 무역수지 항목이 없다**(메타 조회).
- 그런데 표 이름에 '무역수지'가 든 표는 대부분 **기술무역수지**라, 문자열이 겹쳐
  `기관유형별 산업별 기술무역수지 / objL1=건설` 로 오매핑됐다.
- 무역수지 = 수출액 − 수입액. **두 항목의 연산**이 필요한데 우리 구조는 '한 좌표 = 한 값'이라
  표현할 수 없다(`difference_from_level` 은 같은 항목의 *시점 간* 차이다).

→ `DERIVED_INDICATOR` 게이트를 추가해 범위 밖으로 분류했다.
   **판정은 `claim_text` 가 아니라 measurement 의 지표 필드로만 한다.**
   문장으로 막으면 같은 문장의 정상 매핑(수입액·수입 증감률)까지 버리기 때문이다.

| 지표 | 값 |
|---|---|
| 확정 집합 | **130** (177 → 게이트 47건 제외, 오탐 0) |
| 2차 READY | **8** (해제 전 2) |
| verdict | **일치 3 / 판정보류 5 / 불일치 0 / 판단불가 0** |
| 자동 확정 정확도 | **7/8** (남은 1건은 WTO 1~9월 누적 vs KOSIS 연간 기간 정의 차이) |
| 오매핑 | **0** |

일치 3건의 차이율은 0.028% · 0.037% · 0.131%.
판정보류 5건은 전부 `REVISION_VINTAGE_RISK` 이며, 잠정치 구간·설명 가능한 개정폭 조건을
모두 통과한 건들이다.

### 이날 검수에서 LLM 판단이 뒤집힌 사례 (기록)

| 초기 판단 | 실제 | 어떻게 밝혀졌나 |
|---|---|---|
| "검증기가 +0.61 로 계산했다" | -0.61 로 정확. **claim 부호가 빠졌다** | `kosis_actual_raw` 컬럼 직접 조회 |
| "부호 반전은 개정으로 설명 불가" | 계절조정은 재추정으로 과거가 바뀐다. **보류 타당** | KOSIS 지수 시계열 직접 계산 |
| "한 문장 measurement 들이 같은 좌표를 공유" | **73% 가 정상 구분.** 무역흑자 건도 지표·Top-5 모두 달랐다 | 문장별 지표/Top-5 교차 집계 |

셋 다 **역산 추측**이었고 실제 데이터 조회로 뒤집혔다.
→ 원칙: 추측으로 판정하지 말고 남아 있는 컬럼을 먼저 열 것.

**테스트: 440 passed**
