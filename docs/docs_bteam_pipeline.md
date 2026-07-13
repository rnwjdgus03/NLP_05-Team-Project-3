# B팀 KOSIS 검증 파이프라인

## 0. 입력 데이터

A팀이 전달하는 claim 데이터는 아래 컬럼이 있어야 한다.

필수 컬럼:
- `claim_id`: 주장 ID
- `article_id`: 기사 ID
- `title`: 기사 제목
- `date`: 기사 날짜
- `url`: 기사 URL
- `claim_text`: 수치가 들어간 주장 문장
- `metric`: 주장 유형 라벨
- `metric_all`: 복수 metric 후보
- `is_claim`: 실제 검증 대상 주장 여부
- `population`: 대상 집단
- `numbers`: 문장 안 숫자
- `units`: 숫자 단위
- `year`: 기준 연도/시점
- `region`: 지역

현재 기준 입력 파일:
- `data/claims/claim_df_with_metric_v2.csv`
- 전체 20,486행
- `is_claim=True`: 7,385행
- KOSIS 검토 우선 대상: 6,404행

실전1 제출 기준:
- KOSIS 통계표 인덱스 최신본: `kosis_table_summary.csv` 107,138건
- 핵심 산출물: `docs/templates/통계표_관찰_템플릿.xlsx`(통계표 관찰 기록 + API 파라미터 참고 + 탐색 경로 예시 + 인덱스 EDA 요약)
- 대표 검증 배치 197건 실행 완료(verified_claims.csv: 일치 5건, 불일치 131건, 판단불가 61건)은 부가 진행 성과로 정리
- 수동 검토 4,403건과 대량 검증은 다음 단계

## 1. B팀 1차 필터링

전체 문장을 바로 KOSIS에 매칭하지 않는다.

우선순위:
1. `is_claim=True`인 행만 사용
2. KOSIS 검증 가능성이 낮은 metric은 후순위 또는 제외
   - `날짜·시간`
   - `증시지표`
   - `기업실적`
   - `정책·제도`
   - `환율`
   - `인명피해`
3. 남은 행을 KOSIS 후보 매칭 대상으로 사용

생성 파일:
- `data/claims/claim_df_with_metric_v2_is_claim.csv`
  - `is_claim=True` 7,385건
- `data/claims/claim_df_with_metric_v2_kosis_like.csv`
  - KOSIS 검토 우선 대상 6,404건

## 2. 작업 파일

현재는 분할하지 않고 한 사람이 전체 KOSIS 우선 대상을 검토한다.

생성 파일:
- `outputs/bteam_review/bteam_kosis_review_all.csv`
  - 6,404건
  - KOSIS 검토 우선 대상 전체
  - 원본 claim 컬럼 뒤에 B팀 검토 컬럼을 추가한 작업용 파일

이 파일에서 KOSIS 후보표를 찾고 매핑한다.

1차 자동 매핑 후 생성 파일:
- `outputs/bteam_review/bteam_kosis_review_all.csv`
  - 전체 6,404건에 후보표/사유 반영
- `outputs/bteam_review/bteam_kosis_review_filled.csv`
  - `tbl_id`가 자동으로 채워진 2,001건
  - 이 중 1,998건은 `obj_l1`, `itm_id` 자동 후보까지 입력
- `outputs/bteam_review/bteam_kosis_review_manual_todo.csv`
  - 수동검토가 필요한 4,403건
- `outputs/bteam_review/bteam_kosis_tbl_meta_candidates.csv`
  - 자동 매핑에 사용된 19개 KOSIS 표의 메타정보 요약
- `outputs/bteam_review/bteam_kosis_codebook_needed.csv`
  - 품목별 수출입/소매판매 등 세부 코드 확인용 코드북
- `outputs/bteam_review/bteam_kosis_review_summary.csv`
  - metric별/사유별 처리 요약

## 3. KOSIS 후보표 검색

각 claim에서 아래 정보를 보고 검색 키워드를 만든다.

사용 정보:
- `claim_text`
- `metric`
- `population`
- `numbers`
- `units`
- `year`
- `region`

예시:
- claim: `지난달 소비자물가가 전년 동월 대비 2.1% 상승했다.`
- metric: `물가지표`
- 검색 키워드: `소비자물가`, `등락률`, `월별`, `전년동월`
- 후보표: `월별 소비자물가 등락률`

사용 파일:
- `kosis_table_summary.csv`
  - KOSIS 통계표 목록
- `kosis_metadata_summary.csv`
  - 주요 후보표의 분류축/항목/단위 요약

## 4. 매핑 결과 컬럼

최종 매핑 파일에는 아래 컬럼을 채운다.

필수 작성 컬럼:
- `org_id`: KOSIS 기관 ID
- `tbl_id`: KOSIS 통계표 ID
- `obj_l1`: 분류 코드
- `itm_id`: 항목 코드
- `prd_se`: 주기
  - 연간: `Y`
  - 반기: `H`
  - 분기: `Q`
  - 월간: `M`
- `reviewer_note`: 판단 근거

후보표가 맞지 않으면 `org_id`, `tbl_id`, `obj_l1`, `itm_id`, `prd_se`는 비워두고 `reviewer_note`에 이유만 적는다.

예시 reviewer_note:
- `후보표 부적합: claim 대상과 통계표 모집단이 다름`
- `KOSIS 공식통계 직접 검증 대상 아님: 기업 실적 전망`
- `관세청 단기 속보성 수출 자료라 KOSIS 일반표와 직접 매칭 어려움`
- `후보표는 맞지만 obj_l1/itm_id 추가 확인 필요`

## 5. 메타정보 확인

표를 고른 뒤 KOSIS 메타 API로 실제 파라미터를 확인한다.

확인할 것:
- 분류축 이름
- 분류 코드
- 항목 코드
- 단위
- 시점 주기

예시:
- `org_id=101`
- `tbl_id=DT_1J22042`
- 표 이름: 월별 소비자물가 등락률
- 확인 필요:
  - 지역 코드
  - 품목/지수 항목 코드
  - 월별 시점 코드

## 6. 실제 수치 조회

`org_id`, `tbl_id`, `obj_l1`, `itm_id`, `prd_se`가 확정되면 KOSIS 자료 API로 실제 값을 조회한다.

조회 결과에서 확인할 것:
- `PRD_DE`: 시점
- `DT`: 실제 값
- `UNIT_NM`: 단위
- 분류명/항목명

## 7. 검증 판정

`verify_claim.py`로 뉴스 claim 숫자와 KOSIS 실제 값을 비교한다.

판정 유형:
- `CHANGE_RATE`: 증가율/감소율
- `LEVEL`: 특정 시점 수준값
- `ABS_TO_ABS`: 이전값에서 이후값으로 변화

판정 결과:
- `일치`
- `불일치`
- `판단불가`

현재는 `obj_l1`, `itm_id`, 실제 KOSIS 값이 없으면 `판단불가`가 정상이다.

대표 배치 검증 현황:
- `table_claim_mapping.csv`: 197건
- `verified_claims.csv`: 일치 5건, 불일치 131건, 판단불가 61건
- 이 결과는 실전1 핵심 제출물이 아니라 후속 검증 파이프라인의 실행 예시로 사용한다.

## 8. A팀에 요청할 점

A팀은 claim 문장을 넘길 때 아래 정보를 최대한 채워줘야 한다.

특히 중요:
- `is_claim=True`만 최종 검토 대상으로 넘기기
- `metric`을 너무 넓게 잡지 않기
- `population`을 가능하면 채우기
- `year`와 `region`을 명확히 채우기
- 기자 프로필/수상 이력/기사 설명 문장은 claim에서 제외하기

B팀이 가장 어려운 경우:
- 문장에 숫자는 있지만 통계 주장이 아닌 경우
- 기업 실적/증시/전망치/정책 목표인 경우
- “이 비율”, “같은 기간”처럼 앞 문장 없이는 대상이 불명확한 경우
- 통계표 후보는 있지만 claim의 모집단과 KOSIS 모집단이 다른 경우
