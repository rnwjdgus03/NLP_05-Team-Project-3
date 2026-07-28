# KOSIS feature/model 로직 리뷰

검토 기준 브랜치와 커밋:

```text
origin/feature/model
837cc4b84f101158b7a6c9eb04e734e965770048
```

## 결론

동적 통계표 목록 조회와 메타 API 조회 방향은 맞다. 다만 기존 로직은 구형 claim-level CSV를 전제로 하므로 현행 measurement-first 결과를 그대로 넣으면 잘못된 후보를 만든다. `candidate_rank=1`을 바로 실제값 검증에 사용하기 때문에 후보 오류가 거짓 불일치로 이어질 수 있다.

판단불가를 줄이는 것보다 **일치·불일치를 말할 수 있는 조건을 엄격하게 만드는 것**이 먼저다.

## 확인된 문제

1. `measurement_indicator`, `measurement_item`, `measurement_period`보다 구형 `indicator`, `industry_or_item`, `period`를 사용했다.
2. `is_claim=True` 100행이 모두 KOSIS 대상이라고 가정해 정책값·조건값·문맥값·placeholder도 후보 검색에 들어갔다.
3. 표 후보 점수가 문자열 부분 일치 중심이라 반도체가 화장품 표, 국제선 여객이 무역 표에 연결됐다.
4. 표 이름의 종료 연도와 claim 기간을 비교하지 않아 2024 claim에 2003~2009 표가 선택됐다.
5. ITEM 단위가 없거나 알 수 없으면 호환 가능한 것으로 처리했다.
6. 증감률을 수준값과 직접 비교하거나 일반 비율 ITEM을 증감률로 사용했다.
7. 첫 OBJ에 데이터가 없으면 의미가 다른 OBJ까지 바꿔 조회했다.
8. 연간 claim에서 월·분기 자료를 지표의 flow/stock 성격과 무관하게 합산했다.
9. `change_base=전년`만 사용해 “2023년은 2019년보다 13% 증가”를 2022년과 비교했다.
10. 항공사 한 곳을 LCC 전체 또는 대형 항공사 전체로 대표하는 등 모집단·집계 범위를 확인하지 않았다.

## 개선된 실행 계약

```text
v1.5 전체 measurement 100행
→ 구조·단위·기간 정규화
→ KOSIS 입력 게이트
→ eligible measurement 22행
→ 통계표 후보 검색
→ 상위 표 메타 조회
→ READY / REVIEW / REJECT
→ READY만 실제 데이터 API 호출
→ 일치 / 불일치 / 판단불가 + 사유 코드
```

추가된 표준 필드:

```text
canonical_unit
unit_dimension
semantic_type
entity_type
comparison_period
mapping_eligible
mapping_exclusion_code
candidate_status
candidate_status_code
mapping_type
verdict_code
verdict_stage
```

## 100행 재실행 결과

### 입력 게이트

| 항목 | 결과 |
|---|---:|
| 전체 행 | 100 |
| KOSIS 후보 measurement | 22 |
| 사전 제외 | 78 |
| 정책·조건·문맥값 | 41 |
| KOSIS 범위 밖 | 21 |
| 기간 없음 | 9 |
| placeholder | 4 |
| 역할 제외 | 2 |
| 순위 | 1 |

기존 실행은 100행에서 후보 488개를 생성했다. 개선 실행은 22행에서 표 후보 94개를 생성하고, 실제 메타를 조회한 뒤 1위 후보를 엄격하게 판정했다.

### 메타 판정

| 상태 | 건수 | 의미 |
|---|---:|---|
| READY | 1 | 표·ITEM·OBJ·단위·기간 확정 |
| REVIEW | 17 | 코드셋·계산식·후보·모집단 확인 필요 |
| REJECT | 4 | 의미가 맞는 KOSIS ITEM 없음 |

### 실제값 검증

| verdict | 건수 |
|---|---:|
| 일치 | 1 |
| 불일치 | 0 |
| 판단불가 | 21 |

판단불가 사유:

| 사유 코드 | 건수 | 후속 조치 |
|---|---:|---|
| `CODESET_REQUIRED` | 14 | 반도체·석유화학·바이오헬스·농수산식품·화장품 및 항공사 그룹 코드셋 정의 |
| `NO_COMPATIBLE_ITEM` | 4 | 정비사 ITEM이 KOSIS 표에 존재하는지 재검색, 없으면 다른 공식 출처 사용 |
| `FORMULA_REQUIRED` | 1 | 수출액-수입액으로 무역수지 계산 |
| `AMBIGUOUS_TABLE` | 1 | 국제선 여객 표 1·2위 메타 비교 |
| `POPULATION_DEFINITION_MISMATCH` | 1 | 로봇 도입 기업과 로봇산업 사업체를 동일 모집단으로 보지 않음 |

일치한 1건은 총수출액이다. KOSIS 값과 뉴스 값의 차이율은 약 0.0279%였다.

## 실행

```powershell
python run_kosis_measurement_pipeline.py `
  --input "outputs\runs\hcx_extracted_handoff_100_v15.csv" `
  --table-index "kosis_table_summary.csv" `
  --out-dir "outputs\runs\kosis_v2" `
  --top-tables 5 `
  --top-rank-for-meta 2 `
  --min-score 10
```

후보 CSV에서 `candidate_status=READY`를 확인한 뒤에만 `--verify`를 추가한다.

```powershell
python run_kosis_measurement_pipeline.py `
  --input "outputs\runs\hcx_extracted_handoff_100_v15.csv" `
  --table-index "kosis_table_summary.csv" `
  --out-dir "outputs\runs\kosis_v2" `
  --verify
```

## 담당 경계

진성님 쪽은 원문부터 measurement 구조화, 표준 단위, 기간·비교기간, KOSIS 입력 게이트까지 담당한다. 정현님 쪽의 동적 목록·메타 조회 아이디어는 유지하되, 후보 상태와 사유 코드 계약을 함께 사용한다.

tbl_id, ITEM, OBJ, 코드셋, 계산식이 확정되지 않은 행은 실제값 검증으로 넘기지 않는다. 판단불가가 많아도 사유가 위 코드로 명확하면 정상 동작이다.
