# 트러블슈팅 로그 - 2026-07-13

## 1. 프로젝트 폴더가 가상환경 폴더 안에 들어가 있던 문제

- 상황: 처음에는 `venv/NLP_05-Team-Project-3` 경로에서 작업하고 있었음.
- 문제: 가상환경 폴더 안에 프로젝트 코드를 두면 의존성 폴더와 소스코드가 섞여 관리가 어려움.
- 처리: GitHub `develop` 브랜치 기준 프로젝트를 `NLP_05-Team-Project-3` 폴더로 따로 정리하고, 가상환경은 프로젝트 내부 `venv`로 사용하도록 정리함.
- 결과: 코드 경로와 가상환경 경로가 분리되어 이후 실행/관리 기준이 명확해짐.

## 2. GitHub 최신 코드로 덮어쓰기 반복

- 상황: 팀원이 GitHub `develop` 브랜치에 새 코드를 올릴 때마다 로컬 코드와 차이가 생김.
- 문제: 로컬에서 만든 중간 파일과 GitHub 최신 코드가 섞이면 어떤 파일이 최신인지 헷갈림.
- 처리: 필요할 때마다 GitHub `develop` 기준으로 교체/동기화하고, `.env` 같은 민감 파일은 덮어쓰지 않도록 주의함.
- 결과: 코드 기준은 GitHub `develop`, 개인 API 키는 로컬 `.env`에만 보관하는 방식으로 정리함.

## 3. KOSIS API Key 노출 위험

- 상황: KOSIS 메타 API 호출 실패 로그 안에 요청 URL이 그대로 남으면서 `apiKey`가 같이 저장될 가능성이 있었음.
- 문제: `api_params`나 에러 메시지에 API Key가 들어가면 GitHub 업로드 시 키가 노출될 수 있음.
- 처리:
  - `match_claims_to_tables.py`에서 메타 API 실패 시 전체 URL을 저장하지 않고 에러 타입만 저장하도록 수정함.
  - `table_claim_mapping_구정현.csv`, `table_claim_mapping_구정현_reviewed.csv`, `table_claim_mapping_구정현.xlsx` 안의 `apiKey` 흔적을 제거/마스킹함.
- 결과: `rg "apiKey=|apiKey%3D|ZTFiMTMz"`로 확인했을 때 작업 파일에서 실제 API Key가 검색되지 않도록 정리함.

## 4. KOSIS 메타정보 단위가 `확인 불가`로 많이 나온 문제

- 상황: `kosis_metadata_summary.csv`, `kosis_metadata_summary_팀원이름.csv`에서 일부 표의 단위가 `확인 불가`로 표시됨.
- 원인:
  - 메타 API는 분류축/항목 코드는 알려주지만, 단위는 실제 데이터 조회까지 해야 확인되는 경우가 있음.
  - 일부 표는 `obj_l1`, `itm_id`, 시점 파라미터가 정확히 맞지 않으면 실제 데이터가 안 나옴.
- 처리:
  - `ORG_ID`, `TBL_ID`, 분류축, 항목 예시는 메타 API 기준으로 확보함.
  - 단위가 안 나온 표는 무리해서 확정하지 않고 `확인 불가`로 남김.
  - 이후 정확한 `obj_l1`, `itm_id`, `prd_se`를 채운 뒤 실제 데이터 조회로 단위를 확인하기로 함.
- 결과: 단위 미확인은 실패가 아니라 “실제 조회 파라미터 확정 전 상태”로 정리함.

## 5. A팀 데이터에 metric/time/population이 없던 문제

- 상황: A팀에서 전달한 예시 파일에는 claim 문장은 있었지만 `metric`, `time`, `population`이 비어 있거나 부족했음.
- 문제: B팀의 KOSIS 표 매칭은 “무슨 지표인지, 어느 시점인지, 어떤 대상인지”가 있어야 정확히 가능함.
- 처리:
  - A팀에 필요한 입력 컬럼을 정리함.
  - 필요한 형식: `claim_id`, `claim_text`, `metric`, `time`, `population`, `unit`, `keywords` 등.
  - 임시로 rule 기반 매칭을 돌려 `table_claim_mapping.csv`, `metric_review_summary.csv`를 만들었지만, 최종 검증용이 아니라 PoC용으로 구분함.
- 결과: PoC는 가능했지만, 최종 검증은 A팀의 정제 라벨이 필요하다는 점을 확인함.

## 6. 자동 후보표 매칭이 많이 틀리는 문제

- 상황: `candidate_kosis_table`에 여러 후보표가 세미콜론으로 들어왔지만, 일부는 claim과 전혀 맞지 않는 표였음.
- 예시:
  - 농가 고령 비율 주장인데 정보보호 제품/스마트폰 앱 관련 표가 후보로 잡힘.
  - 수출 속보 주장인데 일반 KOSIS 수출 통계표와 직접 매칭하기 어려운 경우가 있음.
- 원인:
  - 검색 키워드 기반 후보 생성이라 문장 안 단어가 우연히 겹치면 엉뚱한 표가 후보로 잡힘.
  - `metric`이 비어 있으면 후보표 선택 기준이 약해짐.
- 처리:
  - 처음에는 자동 후보를 넓게 잡았지만, 엉뚱한 표가 섞이는 것을 확인함.
  - 이후 보수적으로 변경하여 명확한 경우만 `org_id`, `tbl_id`, `prd_se`를 채우고, 애매한 경우는 비워둔 뒤 `reviewer_note`에 사유를 남김.
- 결과: `table_claim_mapping_구정현_reviewed.csv`에서 211건 중 19건만 보수적으로 채우고, 192건은 수동검토 대상으로 분리함.

## 7. 엑셀 파일 변환 시 Python 패키지 누락

- 상황: `/Users/gu/Downloads/table_claim_mapping_구정현.xlsx`를 CSV로 변환하려고 했지만, 가상환경에 `pandas`, `openpyxl`이 없었음.
- 에러:
  - `ModuleNotFoundError: No module named 'pandas'`
  - `ModuleNotFoundError: No module named 'openpyxl'`
- 처리:
  - 엑셀 변환에는 `pandas`까지는 필요 없어서 `openpyxl`만 설치함.
  - 네트워크 제한으로 기본 설치가 실패해, 승인 후 네트워크 허용 상태에서 `venv/bin/pip install openpyxl` 실행함.
- 결과: 엑셀을 읽어 `table_claim_mapping_구정현.csv`로 변환했고, 총 211건을 확인함.

## 8. CSV 재작성 중 원본 CSV가 헤더만 남은 문제

- 상황: `table_claim_mapping_구정현.csv`를 정리하는 과정에서 같은 파일을 읽고 쓰는 순서가 꼬여 원본 CSV가 헤더 1줄만 남음.
- 문제: 원본 CSV가 손상된 것처럼 보였음.
- 처리:
  - 원본 엑셀 `table_claim_mapping_구정현.xlsx`가 남아 있었기 때문에 다시 읽어서 CSV를 복구함.
  - 복구 후 `wc -l`로 `table_claim_mapping_구정현.csv`와 `table_claim_mapping_구정현_reviewed.csv`가 모두 212줄(헤더 1 + 데이터 211)인지 확인함.
- 결과: 원본 CSV 복구 완료. 이후 작업은 `reviewed` 파일 기준으로 진행함.

## 9. `verify_claim.py` 파일럿 결과가 전부 `판단불가`로 나온 문제

- 상황: `verify_claim.py --input table_claim_mapping_구정현_reviewed.csv --output verified_claims_구정현_pilot.csv`를 실행했더니 211건 전부 `판단불가`로 나옴.
- 원인:
  - `verify_claim.py`는 실제 KOSIS 값과 claim 숫자를 비교해야 판정 가능함.
  - 현재 파일에는 `org_id`, `tbl_id` 일부만 있고, 정확한 `obj_l1`, `itm_id`, 실제 조회값이 대부분 없음.
- 처리:
  - 파일럿 결과를 실패로 보지 않고, “표 매칭 이후 실제 파라미터 확정 전 단계”로 기록함.
  - `verified_claims_구정현_pilot.csv`는 현재 한계를 보여주는 파일로 남김.
- 결과: 다음 단계는 `obj_l1`, `itm_id`, `prd_se`를 확정하고 실제 KOSIS 값을 조회하는 것임.

## 10. 현재 남은 작업

- `table_claim_mapping_구정현_reviewed.csv`에서 판단 기준에 따라 채운 30건을 먼저 사람이 확인해야 함.
- `table_claim_mapping_구정현_manual_todo.csv`의 181건은 후보표가 맞는지 직접 검토해야 함.
- 후보 중 답이 없으면 `org_id`, `tbl_id`, `obj_l1`, `itm_id`, `prd_se`는 비워두고 `reviewer_note`에 사유만 적으면 됨.
- 정확한 표가 확정된 행은 KOSIS 메타 API로 `obj_l1`, `itm_id`를 확인해야 함.
- 실제 KOSIS 수치 조회가 가능해진 뒤 `verify_claim.py`로 `일치 / 불일치 / 판단불가` 판정을 다시 수행해야 함.

## 11. 구정현 담당 211건 2차 판단 기준

- 상황: `table_claim_mapping_구정현.csv` 211건에 대해 `candidate_kosis_table` 후보 중 맞는 표를 고르는 작업을 진행함.
- 처리 기준:
  - 후보표 이름과 claim의 핵심 지표가 직접 연결되는 경우만 `org_id`, `tbl_id`, `prd_se`를 채움.
  - 후보표가 조금이라도 애매하면 억지로 고르지 않고 비워둠.
  - 비워둔 행은 삭제한 것이 아니라, `reviewer_note`에 제외 사유를 적어 수동검토 대상으로 남김.
- 결과:
  - `table_claim_mapping_구정현_reviewed.csv`: 211건 전체 유지
  - 표 후보 확정: 30건
  - 수동검토/제외 사유 기록: 181건
  - `table_claim_mapping_구정현_manual_todo.csv`: 181건만 따로 분리

## 12. 후보표를 비워둔 근거

- 고용동향 취업자 수:
  - 기사 문장은 전국 월별 취업자 수인데 후보표가 시군구/등록취업자/직업훈련 등으로 잡힌 경우가 많았음.
  - 근거: claim의 대상 범위와 후보표의 모집단이 다름.
  - 처리: `후보표 부적합 가능성: 고용동향 취업자 수 주장이나 후보가 전국 월별 취업자 표와 직접 일치하지 않음`으로 기록.
- 관세청 단기 수출 속보:
  - `1~10일`, `1~20일`, `일평균 수출`, `조업일수` 같은 표현은 관세청 속보성 자료에 가까움.
  - 근거: KOSIS 일반 수출 통계표와 시점/공표 단위가 다를 가능성이 큼.
  - 처리: `관세청 단기 속보성 수출 자료: 현재 KOSIS 후보표와 직접 매칭 어려움`으로 기록.
- 기업/증권/시장 자료:
  - 클리오 실적 전망, 삼성전자 R&D 비중, 고려아연 부채비율, 코스피/나스닥/다우 지수 등은 KOSIS 공식통계 검증 대상이 아님.
  - 근거: 개별 기업 자료, 증권시장 데이터, 전망치/컨센서스는 KOSIS 통계표에서 직접 검증하기 어려움.
  - 처리: `KOSIS 공식통계 직접 검증 대상 아님`으로 기록.
- 소득/가계 문장:
  - 가계소득, 소득분위, 흑자액 등은 가계동향조사 세부 항목 코드가 필요함.
  - 근거: 후보표가 있어도 `소득`, `소비지출`, `흑자액`, `분위` 항목 코드가 정확히 맞아야 검증 가능함.
  - 처리: 일부 명확한 표만 채우고, 나머지는 `가계동향 세부 항목 코드 확인 필요`로 기록.
- 출생/사망 문장:
  - 출생아 수와 직접 관련 없는 `출생아 부모 육아휴직자` 같은 후보는 제외함.
  - 자살 사망자 수는 단순 사망자수 표가 아니라 사망원인/자살 항목이 필요함.
  - 근거: 후보표의 항목 정의가 claim의 통계값과 다름.
  - 처리: 직접 검증표가 아닌 후보는 비워두고 사유를 기록.

## 13. 2차 판단 후 `verify_claim.py` 결과

- 실행: `venv/bin/python verify_claim.py --input table_claim_mapping_구정현_reviewed.csv --output verified_claims_구정현_pilot.csv`
- 결과: 211건 모두 `판단불가`
- 해석:
  - 이 결과는 실패가 아님.
  - 현재는 `org_id`, `tbl_id`, `prd_se` 일부만 채운 상태이고, 실제 비교에 필요한 `obj_l1`, `itm_id`, 실제 KOSIS 값이 아직 없음.
  - 따라서 다음 단계는 30건부터 KOSIS 메타 API로 항목 코드를 확정하는 것임.
- 후속 처리:
  - `verified_claims_구정현_pilot.csv`는 전부 `판단불가`인 임시 파일이라 현재 단계에서는 제거함.
  - 나중에 `obj_l1`, `itm_id`, 실제 KOSIS 값이 채워지면 다시 생성하면 됨.

## 14. PoC 중복 파일 제거

- 상황: 이전에 샘플/PoC 용도로 만든 `metric_review_summary.csv`, `table_claim_mapping_reviewed.csv`가 남아 있었음.
- 문제: 구정현 담당 실제 파일(`table_claim_mapping_구정현.csv`)과 이름이 비슷해서 어떤 파일을 봐야 하는지 혼동될 수 있음.
- 처리:
  - 실제 담당 파일은 유지함.
    - `table_claim_mapping_구정현.csv`
    - `table_claim_mapping_구정현_reviewed.csv`
    - `table_claim_mapping_구정현_manual_todo.csv`
  - 샘플/PoC 중복 파일은 제거함.
    - `metric_review_summary.csv`
    - `table_claim_mapping_reviewed.csv`
- 결과: 앞으로는 구정현 담당 211건 파일 기준으로만 검토하면 됨.

## 15. 구정현 211건 이전 배치 파일 제거

- 상황: A팀/B팀에서 데이터를 다시 받을 예정이라 기존 `table_claim_mapping_구정현` 211건 배치 파일이 더 이상 기준 파일이 아니게 됨.
- 문제: 새 데이터를 받을 예정인데 이전 원본/검토본이 남아 있으면 어떤 파일이 최신인지 혼동될 수 있음.
- 처리: 이전 배치 산출물을 제거함.
  - `table_claim_mapping_구정현.xlsx`
  - `table_claim_mapping_구정현.csv`
  - `table_claim_mapping_구정현_reviewed.csv`
  - `table_claim_mapping_구정현_manual_todo.csv`
- 남긴 것:
  - 코드 파일
  - KOSIS 메타/통계표 요약 파일
  - 작업 및 트러블슈팅 로그
- 결과: 새로 받는 데이터 파일을 기준으로 다시 변환/검토를 시작할 수 있는 상태가 됨.

## 16. 새 metric 포함 claim 데이터 수신 및 분할

- 상황: A팀/B팀 기준 데이터가 `claim_df_with_metric_v2.csv`로 변경됨.
- 처리:
  - `/Users/gu/Downloads/claim_df_with_metric_v2.csv`를 프로젝트 폴더로 복사함.
  - 전체 행 수와 컬럼을 확인함.
- 확인 결과:
  - 전체: 20,486건
  - `is_claim=True`: 7,385건
  - KOSIS 검토 우선 대상: 6,404건
- KOSIS 검토 우선 대상에서 제외한 metric:
  - `날짜·시간`
  - `증시지표`
  - `기업실적`
  - `정책·제도`
  - `환율`
  - `인명피해`
- 생성 파일:
  - `claim_df_with_metric_v2.csv`
  - `claim_df_with_metric_v2_is_claim.csv`
  - `claim_df_with_metric_v2_kosis_like.csv`
  - `claim_df_with_metric_v2_kosis_like_part1.csv`
  - `claim_df_with_metric_v2_kosis_like_part2.csv`
- 분할 결과:
  - part1: 3,202건 (`C00009 ~ C10355`)
  - part2: 3,202건 (`C10356 ~ C20484`)
- 추가 문서:
  - `docs_bteam_pipeline.md`
  - A팀에 공유할 B팀 KOSIS 검증 파이프라인을 정리함.

## 17. 반반 분할 취소 및 단일 작업 파일 생성

- 상황: 처음에는 B팀 2명이 반반 검토할 계획이라 `part1`, `part2` 파일을 만들었음.
- 변경: 구정현이 전체 KOSIS 검토 대상 6,404건을 직접 보기로 함.
- 처리:
  - 분할 파일 제거
    - `claim_df_with_metric_v2_kosis_like_part1.csv`
    - `claim_df_with_metric_v2_kosis_like_part2.csv`
  - 단일 작업 파일 생성
    - `bteam_kosis_review_all.csv`
- `bteam_kosis_review_all.csv` 구성:
  - 원본 claim 컬럼 유지
  - B팀 검토용 컬럼 추가
    - `candidate_kosis_table`
    - `api_params`
    - `calculation`
    - `verifiable`
    - `org_id`
    - `tbl_id`
    - `obj_l1`
    - `itm_id`
    - `prd_se`
    - `reviewer_note`
- 결과: 앞으로는 `bteam_kosis_review_all.csv` 하나를 기준으로 KOSIS 표 매칭을 진행하면 됨.

## 18. `bteam_kosis_review_all.csv` 전체 1차 자동 매핑

- 상황: 구정현이 전체 KOSIS 검토 대상 6,404건을 직접 보기로 했고, 처음부터 가능한 데까지 자동 처리하기로 함.
- 문제:
  - 6,404건을 사람이 한 줄씩 바로 검토하면 시간이 너무 오래 걸림.
  - KOSIS 표 목록은 96,018건이라, 각 claim마다 전체 표를 매번 검색하면 처리 속도가 매우 느림.
- 1차 시도:
  - 각 claim마다 전체 KOSIS 표를 순회해 후보표를 찾는 방식으로 실행함.
  - 처리 시간이 과도하게 길어져 중단함.
  - 파일은 마지막에 저장하는 구조였기 때문에 중간 손상은 없었음.
- 개선:
  - KOSIS 표 목록을 토큰 기반 인덱스로 먼저 만들고, claim 키워드로 빠르게 후보표를 찾는 방식으로 변경함.
  - 물가, 무역, 고용, 인구, 가계소득, 소매, 부동산, 농림어업 등은 규칙 기반으로 대표 후보표를 우선 배정함.
  - 확실하지 않은 행은 억지로 `tbl_id`를 채우지 않고 `reviewer_note`에 사유를 남김.
- 결과:
  - 전체 처리 대상: 6,404건
  - `tbl_id` 자동 채움: 2,001건
  - 수동검토/판단불가: 4,403건
- 생성/갱신 파일:
  - `bteam_kosis_review_all.csv`
    - 전체 6,404건에 후보표/사유 반영
  - `bteam_kosis_review_filled.csv`
    - `tbl_id`가 채워진 2,001건
  - `bteam_kosis_review_manual_todo.csv`
    - 수동검토가 필요한 4,403건
  - `bteam_kosis_review_summary.csv`
    - metric별/사유별 처리 요약
- 해석:
  - 6,404건 전체에 대해 1차 판별은 완료됨.
  - 자동 채움 비율은 2,001 / 6,404 = 약 31.2%.
  - 나머지 68.8%는 후보표가 애매하거나 KOSIS 직접 검증 대상이 아니어서 수동검토로 남김.
- 다음 단계:
  - `bteam_kosis_review_filled.csv` 2,001건부터 검토한다.
  - 그중 대표 분야별로 10~30건을 골라 `obj_l1`, `itm_id`를 메타 API로 확정한다.
  - 이후 실제 KOSIS 값을 조회하고 `verify_claim.py`로 검증한다.

## 19. KOSIS 메타 API로 `obj_l1`, `itm_id` 자동 후보 입력

- 상황: `tbl_id`만 붙어 있으면 실제 KOSIS API 조회가 불가능함.
- 이유:
  - `tbl_id`는 통계표 ID일 뿐이고, 실제 값 조회에는 표 안의 분류 코드(`obj_l1`)와 항목 코드(`itm_id`)가 필요함.
  - 예를 들어 같은 수출입 표라도 `수출액/수입액`, `총액/국가별/품목별` 코드가 다름.
- 처리:
  - `bteam_kosis_review_filled.csv`에 등장한 고유 `tbl_id` 19개에 대해 KOSIS 메타 API를 호출함.
  - 호출 결과를 `bteam_kosis_tbl_meta_candidates.csv`에 저장함.
  - 메타 API 성공: 19개 표 전부 성공.
- 자동 입력 결과:
  - `tbl_id`가 채워진 행: 2,001건
  - `obj_l1`과 `itm_id` 둘 다 자동 후보가 들어간 행: 1,795건
  - `tbl_id`는 있지만 `obj_l1` 또는 `itm_id`가 비어 있는 행: 206건
- 비워둔 근거:
  - 반도체, 자동차, 선박, 화장품 등 품목별 수출 주장은 `품목별` 세부 코드가 필요함.
  - 이 경우 총액 코드를 넣으면 오히려 잘못된 검증이 되므로 `obj_l1`을 비워두고 `reviewer_note`에 `품목 세부 코드 필요`라고 남김.
- 결과 파일:
  - `bteam_kosis_review_all.csv`
  - `bteam_kosis_review_filled.csv`
  - `bteam_kosis_tbl_meta_candidates.csv`
  - `bteam_kosis_review_summary.csv`
- 해석:
  - 이제 단순 표 매칭을 넘어서, 실제 API 조회 직전 단계까지 상당 부분 진행됨.
  - 다만 자동 입력된 `obj_l1`, `itm_id`는 “후보”이므로 대표 사례 검증 전에 샘플 확인이 필요함.

## 20. 세부 코드북 기반으로 `obj_l1`, `itm_id` 추가 자동 입력

- 상황: `tbl_id`는 채워졌지만 `obj_l1` 또는 `itm_id`가 비어 있는 행이 206건 남아 있었음.
- 문제:
  - `tbl_id`만 있으면 KOSIS API 조회가 불가능함.
  - 품목별 수출입/소매판매처럼 표 안에 세부 코드가 많은 경우, 총액 코드를 넣으면 잘못된 검증이 될 수 있음.
- 처리:
  - KOSIS 메타 API로 추가 코드북을 생성함.
  - 생성 파일: `bteam_kosis_codebook_needed.csv`
  - 반도체, 자동차, 선박, 화장품, 의약품, 석유, 철강 등 품목 키워드와 KOSIS 품목 코드를 연결함.
  - 소매판매 표(`DT_1K41012`)는 KOSIS 메타에서 확인한 상품군 코드를 사용함.
    - 전체 소매판매: `G0`
    - 승용차/자동차: `G11`
    - 가전제품: `G12`
    - 의복: `G21`
    - 음식료품: `G31`
    - 의약품: `G32`
    - 화장품: `G33`
    - 차량연료: `G35`
- 결과:
  - `tbl_id`가 채워진 행: 2,001건
  - `obj_l1`과 `itm_id` 둘 다 자동 후보가 들어간 행: 1,998건
  - 아직 코드 확정이 어려운 행: 3건
- 3건을 남긴 근거:
  - 고등어/닭고기 수입 관련 문장은 KOSIS 품목별 수출입 표 후보는 있으나, 정확한 HS/품목 코드가 자동 확정되지 않음.
  - `쉬었음` 인구 문장은 고용보조지표 후보표가 붙었지만, 해당 표에 `쉬었음` 항목이 직접 포함되는지 불확실함.
  - 틀린 코드를 억지로 채우는 것보다 `reviewer_note`에 사유를 남기고 수동 확인 대상으로 두는 것이 더 안전함.
- 갱신 파일:
  - `bteam_kosis_review_all.csv`
  - `bteam_kosis_review_filled.csv`
  - `bteam_kosis_review_summary.csv`
  - `bteam_kosis_codebook_needed.csv`

## 21. 작업 파일 폴더 정리

- 상황: 루트 폴더에 CSV, 엑셀, 문서, 파이썬 파일이 섞여 있어 현재 산출물과 예전 입력 파일을 구분하기 어려웠음.
- 원칙:
  - 실행 코드(`*.py`)와 핵심 기준 파일은 루트에 남김.
  - A팀 입력 데이터는 `data/claims/`로 이동.
  - 예전 입력/드랍 전후 파일은 `data/archive/`로 이동.
  - B팀 현재 산출물은 `outputs/bteam_review/`로 이동.
  - 문서/템플릿은 `docs/`로 이동.
  - Python 캐시(`__pycache__`)는 재생성 가능한 임시 파일이라 삭제.
- 이동한 파일:
  - `data/claims/claim_df_with_metric_v2.csv`
  - `data/claims/claim_df_with_metric_v2_is_claim.csv`
  - `data/claims/claim_df_with_metric_v2_kosis_like.csv`
  - `outputs/bteam_review/bteam_kosis_review_all.csv`
  - `outputs/bteam_review/bteam_kosis_review_filled.csv`
  - `outputs/bteam_review/bteam_kosis_review_manual_todo.csv`
  - `outputs/bteam_review/bteam_kosis_review_summary.csv`
  - `outputs/bteam_review/bteam_kosis_tbl_meta_candidates.csv`
  - `outputs/bteam_review/bteam_kosis_codebook_needed.csv`
  - `docs/docs_bteam_pipeline.md`
  - `docs/kosis_param_guide.md`
  - `docs/templates/통계표_관찰_템플릿.xlsx`
  - `data/archive/claim_candidates_from_xlsx.csv`
  - `data/archive/검증대상_기사드랍후.csv`
  - `data/archive/검증대상_기사드랍후.xlsx`
  - `data/archive/kosis_table_summary_p2_b.csv`
  - `data/archive/kosis_metadata_summary_팀원이름.csv`
  - `data/archive/뉴스_노이즈_제거_파이프라인 (1).ipynb`
- 루트에 남긴 핵심 파일:
  - `kosis_table_summary.csv`: 96,018개 KOSIS 표 인덱스, 여러 스크립트 기본 입력
  - `kosis_metadata_summary.csv`: 주요 후보표 메타 요약
  - `kosis_api_test.py`, `kosis_table_search.py`, `match_claims_to_tables.py`, `verify_claim.py` 등 실행 코드
- 삭제한 파일:
  - `__pycache__/`
- 삭제 근거:
  - `__pycache__`는 Python 실행 시 자동 생성되는 캐시라 보관할 필요가 없음.
  - 데이터 파일은 삭제하지 않고 폴더로 이동해 추적 가능하게 유지함.
