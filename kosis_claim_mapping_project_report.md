# 뉴스 기사 통계 주장 → KOSIS 매핑 파이프라인 구축 보고서

## 1. 개요

**목표**: 뉴스 기사 원문에서 통계적 주장(claim)을 자동으로 찾아내고, 그 안의 수치를
구조화된 컬럼(지표·값·단위·시점 등)으로 추출한 뒤, 실제 KOSIS(국가통계포털) 통계표와
매칭하여 "이 기사의 주장이 공식 통계로 검증 가능한가"를 자동으로 판별하는 데이터
파이프라인을 구축했다.

**전체 흐름**:
```
기사 원문(CSV)
  → [1] claim 추출 + 구조화 (HCX)
  → [2] KOSIS 매핑 준비도(ready) 판별
  → [3] claim ↔ KOSIS 통계표 후보 매칭 (임베딩 검색)
  → [4] 실제 KOSIS API로 최종 검증
  → 검증된 매핑 결과
```

---

## 2. 단계별 작업 내역

### 2.1 claim 추출 + 구조화 (문장 단위 → 기사 통합 방식으로 전환)

- **1차 접근**: 기사를 문장 단위로 미리 쪼갠 뒤(`article_to_claims.py`), 문장마다
  `is_claim_filter_hcx.py`로 검증 가능 여부를 판별하고, `extract_hcx.py`로 수치를
  추출하는 4단계 파이프라인을 구성했다.
  - 초기에는 "숫자가 있는 문장만" 후보로 걸렀으나, 숫자 없는 추세 주장("실업률이
    올랐다")을 놓치는 문제가 있어 **모든 문장을 후보로 통과시키고 HCX가 직접
    판별하도록 수정**했다.
- **2차 접근(기사 통합 방식)**: `extract_article_claims_hcx.py`를 새로 만들어, 기사
  전체를 한 번에 HCX에 주고 "검증 가능한 문장 판별"과 "수치 추출"을 동시에 하도록
  구조를 바꿨다. 문장 단위 방식보다 앞뒤 한 문장이 아니라 **기사 전체 맥락**(제목,
  다른 문단)을 보고 시점(period)을 판단할 수 있다는 장점이 있다.
- **시행착오 - claim_text 환각 문제**: 기사 통합 방식 초기 버전은 HCX에게 근거
  문장을 "원문 그대로 베껴 써라"고 시켰는데, 공백/오탈자 차이로 실제로 있는 문장인데도
  원문에서 못 찾아 버려지는 손실(`claim_grounded=N`)이 발생했다. → **해결**: 문장을
  미리 번호를 매겨 보여주고, HCX는 `sentence_indices`(번호)만 고르게 하는 방식으로
  전환. 텍스트는 항상 실제 문장에서 직접 조립하므로 원천적으로 100% grounded되고,
  진짜 환각(존재하지 않는 번호)만 정확히 걸러진다.

### 2.2 KOSIS 매핑 준비도(ready) 판별

- `prepare_kosis_mapping_input.py`로 measurement 단위 결과를 검사해, 값·지표·시점·
  단위가 다 채워져 있고 HCX가 직접 확정한 값(규칙 fallback 아님)이며 국내 공식
  통계 범위인 것만 "ready"로 분류했다. 단순 `is_claim=True`보다 훨씬 엄격한 기준이다.
- **시행착오 - readiness 기준 불일치**: 별도로 만들어진 `in_ready` 플래그 파일(293건
  전부 `Y`)을 검증해보니, `prepare_kosis_mapping_input.py`의 엄격한 기준을 통과하는
  건 172건뿐이었다 (`OUT_OF_KOSIS_SCOPE` 58건, `ROLE_NOT_DIRECT_TARGET` 33건,
  `PERIOD_MISSING` 21건 등). 두 기준이 다르다는 걸 확인하고, 최종적으로는 필터링을
  강제하지 않고 파생 컬럼만 채우는 `--keep-all` 옵션을 추가해 293건을 그대로 유지하되
  하위 단계에서 필요한 `comparison_period` 등을 보강했다.

### 2.3 claim ↔ KOSIS 통계표 매칭

- **1차: 어휘 기반 매칭** (`match_claims_to_kosis_tables.py`) - claim의 indicator/
  keywords와 KOSIS 테이블 카탈로그(37개, 사람이 뉴스 주제를 보고 손으로 고른 목록)의
  이름/분류/단위 텍스트를 토큰 겹침으로 비교. "총 수출액" 같은 명확한 경우는 잘
  맞았지만, 단어가 안 겹치는 주제("로봇 밀도" 등)는 찾지 못했다.
- **2차: 임베딩 기반 검색으로 전환** - Naver Cloud Platform의 HCX 임베딩v2 API로
  claim과 테이블을 벡터화하고 코사인 유사도로 검색하는 방식(RAG의 "Retrieval" 단계와
  동일한 기법)으로 바꿨다.
  - 처음엔 NCP **Cloud DB for PostgreSQL + pgvector**로 구현했으나, Public 도메인/
    ACG 설정 등 NCP 콘솔 작업이 필요해 진입장벽이 있었다.
  - **시행착오 - DB 없이도 충분함**: 지금 규모(수십~수백 개 테이블)에서는 진짜
    벡터DB가 필요 없다는 걸 확인하고, 임베딩을 CSV 파일에 저장해두고 검색 시 넘파이로
    직접 코사인 유사도를 계산하는 **DB 없는 버전**(`embed_kosis_catalog_local.py`,
    `search_kosis_catalog_local.py`)으로 전환했다. `CLOVA_API_KEY`만 있으면 되고
    NCP 콘솔 설정이 전혀 필요 없다.

### 2.4 실제 KOSIS API 최종 검증

- `kosis_validate_mapping_candidates.py`(외부 제공 스크립트)가 검색으로 찾은 후보
  테이블 안에서 실제 항목(ITM)/분류(OBJ) 코드 조합을 찾아 KOSIS 통계자료 API로 직접
  조회해 값·단위·시점이 실제로 맞는지 검증한다.
- **시행착오 - mapping_type 고정 문제**: 검색 단계에서 `mapping_type`을 항상
  `"direct"`로 고정해서 보냈는데, "물가 상승률"(%) claim이 소비자물가**지수**
  (2020=100, 지수값) 표에 매칭된 경우 단위가 안 맞아 전부 `UNIT_MISMATCH`로 실패했다.
  → **해결**: claim의 `semantic_type`(증감률/증감량 등)과 매칭된 테이블의 실제 단위를
  비교해서, 표가 그 값을 직접 발표하지 않으면 `rate_from_level`/
  `difference_from_level`로 자동 전환하도록 `decide_mapping_type()`을 추가했다.

---

## 3. 시행착오 총정리

| 문제 | 원인 | 해결 |
|---|---|---|
| 숫자 없는 추세 주장 누락 | 규칙 기반으로 "숫자 있는 문장"만 후보로 걺 | 모든 문장을 후보로 통과, HCX가 직접 판별 |
| `claim_grounded=N` 손실 | HCX가 원문을 그대로 베끼다 공백/오탈자 발생 | 문장 번호(`sentence_indices`)를 고르게 하는 방식으로 전환 |
| 파일명 혼동 (`.py`가 `.csv` 자리에 들어감) | 자동 이름 보정 로직이 확장자를 안 가림 | 같은 확장자만 후보로 인정하도록 수정 |
| API 키 오류를 성공으로 착각 | KOSIS API가 인증 오류도 HTTP 200 + 에러 객체로 응답 | 응답에 `err`/`errMsg` 있으면 실패로 감지 |
| `--limit` 값을 안 바꾼 채 다음 단계 실행 | 실행 로그를 확인 안 하고 넘어감 | 매 실행마다 로그(`[N/전체]`) 직접 확인하는 습관화 |
| readiness 기준 불일치 | 별도 스크립트의 `in_ready`와 `mapping_eligible` 기준이 다름 | `--keep-all` 옵션으로 필터링 없이 파생 컬럼만 보강 |
| 카탈로그(37개) 도메인 편향 | 뉴스 주제를 보고 사람이 손으로 고름 | KOSIS 통계목록 API 재귀 크롤러(`crawl_kosis_catalog.py`)로 전체 확장 착수 |
| `mapping_type` 항상 `"direct"` | 표가 값을 직접 발표하는지 미리 반영 안 함 | claim `semantic_type` × 테이블 단위 비교로 자동 결정 |
| 벡터DB 설정 복잡 | NCP Cloud DB Public 도메인/ACG 등 설정 필요 | 소규모에선 DB 없이 CSV+넘파이로 대체 |
| 크롤링 중단 시 데이터 손실 위험 | 200건마다만 저장, 중단 처리 없음 | `KeyboardInterrupt` 시에도 무조건 flush, `--resume` 지원 |

---

## 4. 현재 결과 (업로드하신 파일 기준)

`kosis_validated__2_.csv`(879행, claim 293건 × 후보 최대 3개) 기준:

| mapping_status | 건수 | 비고 |
|---|---|---|
| `READY` | 12 | 최종 확정된 매핑 |
| `NEEDS_CONFIRMATION` | 151 | `UNIT_MISMATCH` 134건 + 문턱값/확신도 미달 17건 |
| `MAPPING_FAILED` | 423 | 대부분 `INVALID_COMBINATION`(표 안에서 항목 코드 못 찾음) |
| `NOT_EVALUATED` | 293 | 3순위 이하 후보(기본 정책상 평가 안 함) |

**도메인별 분포** (READY는 무역 도메인에만 등장):

| metric_domain | READY | NEEDS_CONFIRMATION | MAPPING_FAILED | NOT_EVALUATED |
|---|---|---|---|---|
| 무역 | **12** | 62 | 100 | 87 |
| 물가 | 0 | 32 | 28 | 30 |
| 소매·소비 | 0 | 27 | 39 | 33 |
| 재정·조세 | 0 | 13 | 91 | 52 |
| 고용 | 0 | 2 | 90 | 46 |
| 금융·금리 | 0 | 8 | 24 | 16 |
| 생산·산업 | 0 | 6 | 32 | 19 |
| 보건·복지 | 0 | 1 | 13 | 7 |

**`ready12개.xlsx`의 12건 최종 READY 매핑 내역**: 전부 `국가별 수출액,수입액`
(org_id=360, tbl_id=`DT_1R11006_FRM101`) 표로 매핑됐다. 반도체·화장품 수출액,
전체 수출/수입액, 무역 흑자 등 세부 품목이 달라도 이 표 하나가 폭넓게 커버해서
매칭 확신도(`mapping_confidence` 1.45~1.95)가 높게 나온 것으로 분석된다.

**해석**: 무역 도메인만 성공한 건 "검색이 무역만 잘해서"가 아니라, 카탈로그(37개
표, 사람이 손으로 고름)에 무역 표처럼 폭넓게 커버하는 표가 다른 도메인엔 부족했기
때문으로 보인다. 실제로 `kosis_table_candidates__2_.csv`를 보면 1순위 후보가
`READY` 상태로 확신 있게 잡힌 건 20건뿐이고(`candidate_status` 기준), 나머지는
`NEEDS_CONFIRMATION`/`ALTERNATE`로 애매하게 잡혔다.

---

## 5. 남은 과제

1. **카탈로그 확장**: `crawl_kosis_catalog.py`로 KOSIS 통계목록 전체(국내통계
   주제별)를 재귀적으로 훑어 37개 → 훨씬 많은 표로 확장 중. 시간이 오래 걸려 중단 후
   `--resume`으로 이어가는 방식으로 진행하고 있음.
2. **enrichment 필요**: 크롤러는 표 이름과 분류경로만 모으고, 항목(ITM)/분류(OBJ)/
   단위 같은 세부 메타는 없음 - `mapping_type` 자동 판단과 임베딩 품질을 위해
   `getMeta` 기반 enrichment 단계가 추가로 필요.
3. **항목(ITM) 레벨 매칭 개선**: 표는 맞게 찾았는데 표 안의 세부 항목 코드까지 못
   찾아 `INVALID_COMBINATION`으로 실패하는 케이스(423건 중 상당수)가 남아있음 - 이건
   카탈로그를 넓혀도 해결되지 않는 별도 문제로, `kosis_validate_mapping_candidates.py`
   내부의 항목 매칭 로직을 봐야 함.
4. **문턱값 재조정**: 카탈로그가 커지고 실측 데이터가 쌓이면 `DISTANCE_READY_THRESHOLD`
   등 검색 확신도 문턱값을 다시 튜닝할 필요가 있음.
