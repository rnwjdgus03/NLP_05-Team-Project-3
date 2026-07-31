# ChromaDB 메타 좌표 검색 + BGE-M3/reranker 하이브리드 (2026-07-31)

- 목적: 1차 READY 이후 **ITEM/OBJ 좌표 후보 검색**을 개선한다. 2차 READY 숫자를 늘리는 것 자체가 목표가 아니다.
- 원칙: **임베딩·리랭커는 후보 생성과 순위에만 쓴다.** READY 는 공식 메타 + KOSIS API 응답으로만 확정한다.
- 평가 대상 고정: 1차 READY **177 measurement**, 동일 KOSIS 메타 스냅샷.

## 왜 좌표 단위인가

메타 CSV 한 행(축 값 하나)을 그대로 벡터화하면 검증 단위와 어긋난다. KOSIS API 가 요구하는
최소 단위는 `org_id + tbl_id + itm_id + obj 경로` 이므로 그 조합 하나를 document 로 만든다.

```
통계표: 전산업생산지수(계절조정지수)
분류 경로: 생산·산업
항목: 계절조정지수
산업별: 전산업생산지수
단위: 2020=100
수록주기: M
기관: 101
```

`coordinate_id` 는 `sha1(org|tbl|itm|objL1..objL8)` 기반 결정적 ID 라 재생성해도 동일하다
(축 dict 순서에 영향받지 않음 — 테스트로 고정).

## 검색 순서 (구현된 그대로)

1. 상류 통계표 검색 결과에서 **TBL_ID Top-5** 확보
2. **검색 전에** Chroma metadata hard filter 적용
   - `tbl_id ∈ Top-5`
   - `unit_dimension` 호환 — 단 **주장 차원이 파생값(rate/증감폭)이면 배제하지 않는다**
     (수준값에서 계산하므로). `person_count`↔`count` 처럼 이름만 다른 차원은 정규화해 통합한다.
   - `prd_se` 는 **hard filter 에서 제외**한다. 좌표의 `prd_se` 는 표당 하나만 채워지는데
     KOSIS 표는 월·분기·연 주기를 동시에 갖는 경우가 많다. 배제 대신 **순위 강등**으로만 쓴다.
3. BGE-M3 dense Top-50
4. lexical Top-50 (동일 필터를 통과한 좌표 풀 대상, 표별 최대 4,000개로 균등 수집)
5. dense + lexical 합치기 → **coordinate_id 로 중복 제거**
6. RRF 결합 (`kosis_semantic_search.reciprocal_rank_fusion` 재사용)
7. BGE reranker 로 Top-20 재정렬
8. 주기 불일치 후보를 **뒤로 강등**(정렬 키 1순위, 점수 곱셈 아님 — 리랭커 로짓은 음수가 될 수 있다)
9. **Top-10 만** KOSIS API 조합 검증으로 전달

Chroma 경로에서는 `--strict-seeded-coordinate`를 사용해 각 후보가 제시한
`selected_itm_id + selected_obj_l<n>` 좌표를 그대로 1회 검증한다. 검증기가
lexical ITEM/OBJ 조합을 다시 만들어 다른 좌표를 확인하는 일은 허용하지 않는다.

query 는 `claim_text` 만 쓰지 않고 지표·품목·영역·값유형·역할·단위·단위차원·시점·주기·지역·연령·성별·출발국·도착국을
필드명이 드러나는 형태로 합친다(빈 값 제외).

## 상태 기준

| 상태 | 조건 |
|---|---|
| READY | 메타 코드 존재 + API 응답 + 요청·응답 코드 일치 + 기간 존재·일치 + 단위 호환 + 의미 일치 + 상위 후보 명확 + 고위험 default 없음 |
| PROVISIONAL | API·기간·단위·좌표 유효하고 의미 유사도도 높지만 1·2위 차이가 작거나 OBJ 범위가 약간 모호 → **자동 verdict 미사용, 수동 검토** |
| NEEDS_CONFIRMATION | 단위·범위·기간·ITEM/OBJ 중 하나가 불확실 |
| MAPPING_FAILED | 유효 조합 없음 / API 응답 없음 / 기간 데이터 없음 / 코드 불일치 |
| NOT_EVALUATED | Top-K 밖 저순위 후보 |

`--allow-provisional`을 켜면 메타·API·기간·단위가 유효하면서 ITEM/OBJ 조합
1·2위 점수차가 작은 rank-1 후보만 `PROVISIONAL`로 분리한다. 의미 게이트 또는
상류 통계표 확정 조건을 통과하지 못하면 `NEEDS_CONFIRMATION`으로 유지된다.
`kosis_verify_claim_values.py`는 `READY`만 읽으므로 `PROVISIONAL`은 자동 verdict에 쓰이지 않는다.

## 실행

```bash
# 1) Chroma 좌표 인덱스 (Colab GPU)
python kosis_build_chroma_meta_index.py \
  --meta-index 05_hcx_measurements_kosis_meta_index.csv \
  --persist-dir data/indexes/kosis_meta_chroma \
  --collection kosis_meta_coordinates \
  --embedding-model BAAI/bge-m3 --device cuda --reset

# 2) 하이브리드 검색 + reranking
python kosis_chroma_hybrid_search.py \
  --claims 05_hcx_measurements_kosis_ready.csv \
  --table-candidates 05_hcx_measurements_kosis_table_candidates.csv \
  --persist-dir data/indexes/kosis_meta_chroma \
  --collection kosis_meta_coordinates \
  --output 05_hcx_measurements_kosis_chroma_candidates.csv \
  --dense-top-k 50 --lexical-top-k 50 --rerank-top-k 20 --final-top-k 10 \
  --reranker-model BAAI/bge-reranker-v2-m3 --device cuda

# 3) 기존 KOSIS API 검증 (스키마 호환)
python kosis_validate_mapping_candidates.py \
  --input 05_hcx_measurements_kosis_chroma_candidates.csv \
  --meta-index 05_hcx_measurements_kosis_meta_index.csv \
  --output 05_hcx_measurements_kosis_chroma_validated.csv \
  --evaluate-all-ranks \
  --strict-seeded-coordinate \
  --item-top-k 1 --obj-top-k 1 --max-combinations 1 \
  --allow-provisional

# 4) 동일 표본 A/B/C 평가
python evaluate_chroma_hybrid_mapping.py --label C_chroma_hybrid \
  --measurements 05_hcx_measurements_kosis_ready.csv \
  --candidates 05_hcx_measurements_kosis_chroma_candidates.csv \
  --validated 05_hcx_measurements_kosis_chroma_validated.csv \
  --verified 05_hcx_measurements_kosis_chroma_verified.csv \
  --stats chroma_search_stats.csv --output eval_C.json
```

GPU/Chroma 가 없는 로컬에서는 `--meta-index` 를 주면 **lexical 전용 fallback**(dense 없음)으로 동작한다.

Colab 노트북: `notebooks/kosis_chroma_hybrid_second_ready_colab.ipynb` (셀 1~10 순서대로).

## manifest

`data/indexes/kosis_meta_chroma/chroma_manifest.json` 에 기록:
`schema_version`, `embedding_model`, `embedding_dimension`, `normalized`, `created_at`,
`source_meta_file`, `source_meta_sha256`, `document_count`, `collection`,
`axis_value_limit`, `max_coordinates_per_table`.

검색 시 manifest 의 `embedding_model` 과 요청 모델이 다르면 오류로 중단한다.

## 평가 지표와 골드 요구사항

`evaluate_chroma_hybrid_mapping.py` 가 계산: measurement 수, table/ITEM/OBJ recall@1·3·5,
API-valid 수·비율, READY/PROVISIONAL/NEEDS_CONFIRMATION/MAPPING_FAILED/NOT_EVALUATED,
verdict 도달 수·비율, 평균 검색·리랭킹 시간, KOSIS API 호출 수와
골드 좌표 기준 READY end-to-end precision/recall.

**현재 골드가 없다.** recall 을 임의로 만들지 않고 `gold_required` 로 표시한다.
추가로 필요한 골드(177 measurement 기준):

| 컬럼 | 내용 |
|---|---|
| `gold_tbl_id` | 정답 통계표 ID (없으면 "없음") |
| `gold_itm_id` | 정답 ITEM 코드 |
| `gold_obj_l1` (~`gold_obj_l3`) | 정답 분류 코드 |

`READY 수동 검수 Precision` 도 골드나 사람 검수 없이는 산출하지 않는다.

## 1차 Colab 실행 결과 (2026-07-31, 골드 없음)

동일 177 measurement. **개선을 주장할 수 없는 결과다.**

| 지표 | A 베이스라인 | C Chroma 하이브리드 |
|---|---|---|
| 후보가 생긴 measurement | 177 | 168 |
| API-valid measurement | **105 (59.3%)** | **89 (50.3%)** |
| 2차 READY | 2 | 0 |
| KOSIS API 호출 | 813 | 1,670 |
| 평균 검색 / 리랭킹 | — | 0.238s / 0.021s |

주의해서 읽을 것:

- **READY 2 vs 0 은 비교 지표가 아니다.** 양쪽 다 `--trust-downstream-validation` 없이
  돌아 상류 rank-1 게이트에 눌렸다. 진단상 `TOP1_GATE_ONLY 18 + RANK_ONLY 17` 이 대기 중이다.
- `recovery_class` 분포가 A 와 거의 같다(ITEM_OBJ_FIXABLE 72→73, UNIT_FIX_ONLY 41→41).
  좌표를 2배 넓게 던지고도 **실패 구조가 바뀌지 않았다.**
- **`api_valid` 는 정확도 지표가 아니다.** 둘 다 api-valid 인 79건 중 좌표가 일치하는 건 31건뿐.
  나머지 48건은 서로 다른 좌표인데 둘 다 KOSIS 가 값을 돌려줬다. 어느 쪽이 맞는지는 골드로만 판정된다.

### 실패 원인 분해 (정답 좌표 110개 기준)

A 가 API 로 코드 일치까지 확인한 좌표가 C 의 Top-10 에 들어 있었는지로 측정했다
(골드 대용 프록시). 좌표 재현율 Top-10 = **29.5%**(느슨) / 19.0%(엄격).

| 원인 | 건수 | 성격 |
|---|---|---|
| `PASSED_FILTER` | 47 (43%) | 필터·인덱스 모두 통과 → **검색·순위 실패** |
| `UNIT_DIM_FILTER` | 25 (23%) | 버그 (아래) |
| `NOT_IN_INDEX` | 21 (19%) | 축 상한 40 절단 |
| `PRD_SE_FILTER` | 17 (15%) | 표 단위 `prd_se` 의 한계 |

후보가 0개였던 12건은 **PRD_SE 8 + UNIT_DIM 4 = 100% 필터** 때문이었다.
인덱스 커버리지는 문제가 아니었다(ITEM 165/165, 표 상한 도달 1/74).

### 적용한 수정 3건

1. **rate 예외 복구** — 예외를 `mapping_type` 에만 걸어 둔 게 잘못이었다.
   `mapping_type` 은 `item_mapping_type(claim, meta_unit, item_name)` 이 KOSIS 아이템 단위를
   봐야 정해지는 (주장, 좌표) 쌍의 값이라 검색 단계의 주장 레코드에는 **항상 비어 있었다**.
   즉 예외가 한 번도 작동하지 않았다. 이제 주장 차원이 파생값이면 무조건 허용한다. (~18건)
2. **`prd_se` hard filter 제거 → 순위 강등** (17건)
3. **`person_count` → `count` 차원 정규화** (3건)

`(currency, rate)` 3건과 `(count, currency)` 1건은 **완화하지 않았다.** 주장이 수준값인데
좌표가 %면 그 좌표에서 금액을 얻을 수 없고, `response_code_valid` 는 코드 일치만 보증할 뿐
값의 정당성을 보증하지 않는다. 실측 4건에 맞추려고 필터를 무력화하지 않는다.

회귀 테스트: `tests/test_hard_filter_relaxation.py` (완화가 '전부 통과'로 번지지 않는지 함께 고정).

### 이 수정으로도 남는 것

최대 회수 가능은 110건 중 **63건**이고, **47건(43%)은 그대로 남는다.**
필터도 인덱스도 통과했는데 BGE-M3 + reranker 가 Top-10 에 못 올린 건들이다.
이건 임베딩 검색 자체의 한계이며, 원 저장소의 이전 실험(lexical recall@5 62.5% >
BGE-M3 58.3%, 임베딩 단독 히트 0건)과 방향이 일치한다.

## 한계 (정직한 기록)

1. **성능 개선을 아직 주장할 수 없다.** 로컬에는 GPU·Chroma 가 없어 fixture 단위 검증만 했다.
   A/B/C 비교는 Colab 실행 결과가 나온 뒤에 판단한다.
2. `PROVISIONAL`은 1·2위 ITEM/OBJ 조합 점수차가 작은 경우만 구현했다.
   별도 OBJ 범위 모호성 판정은 아직 수동 검토 대상이다.
3. 좌표 조합은 축별 상한(`--axis-value-limit`, 기본 40)과 표별 상한(기본 4000)으로 잘린다.
   집계값(계/전체/총계/전국)을 앞으로 정렬해 총계 좌표가 남도록 했지만, 축이 매우 많은 표는 커버리지가 제한된다.
4. lexical 은 토큰 겹침 기반의 가벼운 구현이다. 상류 통계표 검색의 도메인 규칙과는 별개다.

## 다음 실험

1. 수정 3건 반영 후 재실행 → 좌표 재현율이 29.5% 에서 얼마나 오르는지 실측
2. 177 measurement 골드 좌표(`gold_tbl_id/gold_itm_id/gold_obj_l1`) 확보 → recall 실측.
   **좌표가 서로 다른데 둘 다 api-valid 인 48건이 골드가 필요한 직접적 근거다.**
3. `--axis-value-limit` 40 → 300 (좌표 76,916 → 117,880, +53%) 로 `NOT_IN_INDEX` 21건 회수
4. C 를 `--trust-downstream-validation` 으로 재실행해 회수판 13건과 like-for-like 비교
5. PROVISIONAL 승격 규칙 구현 및 수동 검수 Precision 측정

진단 재현 스크립트: `colab_cell11_why_chroma_missed.py`(원인 분류),
`colab_cell12_index_coverage.py`(인덱스 커버리지), `colab_cell13_which_filter.py`(술어 특정).
셋 다 KOSIS API 호출 없이 기존 CSV 만 읽는다.
