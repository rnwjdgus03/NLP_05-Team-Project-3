# 베이스라인 기록 - 2026-07-13

## 현재 기준 산출물

- KOSIS 통계표 후보 베이스라인: `kosis_table_summary.csv`
  - 전체 통계표 인덱스 96,018건 확보
  - 주요 분야 및 농림어업 관련 표 후보를 메타정보 조회 대상으로 사용
- KOSIS 메타정보 베이스라인: `kosis_metadata_summary.csv`
  - 표별 ORG_ID, TBL_ID, 분류축, 항목 예시, 단위 확인 결과 정리
  - 일부 표는 실제 데이터 조회 파라미터가 아직 확정되지 않아 단위가 `확인 불가`로 남음
- A팀 전달 데이터 베이스라인:
  - 원본: `검증대상_기사드랍후.xlsx`
  - CSV 변환본: `검증대상_기사드랍후.csv`
  - B팀 입력용 후보 문장 변환본: `claim_candidates_from_xlsx.csv`
  - 원본 2,693행에서 claim 문장을 분리해 20,553개 후보 문장 생성
- 판정 로직 베이스라인: `verify_claim.py`
  - claim 유형을 `CHANGE_RATE`, `LEVEL`, `ABS_TO_ABS`로 분류
  - 유형별 허용 오차 적용
    - 증감률: ±0.3%p
    - 수준값: 상대오차 5%
    - 절대값 변화: 상대오차 2%
  - 실제 KOSIS 값 컬럼이 있으면 `일치 / 불일치 / 판단불가` 판정 가능
  - 실제값이 없거나 파라미터가 부족하면 `판단불가`와 사유를 남기도록 설계

## GitHub 반영 기록

- `b761501 feat: add claim verification skeleton`
  - `verify_claim.py` 판정 로직 및 CSV 일괄 판정 구조 추가
- `b01e19e data: add claim handoff files`
  - A팀 전달 엑셀/CSV, B팀 변환 claim 후보 파일, 메타정보 요약 CSV 반영

## 다음 진행 조건

- A팀에서 `metric`, `time`, `population`, `keywords`가 포함된 정제 claim 데이터를 받으면 바로 KOSIS 표 매칭 및 검증 결과 생성 가능
- 사람이 확정한 `org_id`, `tbl_id`, `obj_l1`, `itm_id`, `prd_se`, 실제값 또는 조회 파라미터가 들어오면 `verify_claim.py`로 `verified_claims.csv` 생성 가능
