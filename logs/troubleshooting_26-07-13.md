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
  - KOSIS 표 목록은 107,138건이라, 각 claim마다 전체 표를 매번 검색하면 처리 속도가 매우 느림.
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
  - `kosis_table_summary.csv`: 107,138개 KOSIS 표 인덱스, 여러 스크립트 기본 입력
  - `kosis_metadata_summary.csv`: 주요 후보표 메타 요약
  - `kosis_api_test.py`, `kosis_table_search.py`, `match_claims_to_tables.py`, `verify_claim.py` 등 실행 코드
- 삭제한 파일:
  - `__pycache__/`
- 삭제 근거:
  - `__pycache__`는 Python 실행 시 자동 생성되는 캐시라 보관할 필요가 없음.
  - 데이터 파일은 삭제하지 않고 폴더로 이동해 추적 가능하게 유지함.

## 22. 2,001건 filled 검증 산출물 정리

- 상황: `bteam_kosis_review_filled.csv` 2,001건에 대해 KOSIS 실제값 조회와 `verify_claim.py` 판정을 수행한 뒤, 최종 제출 파일과 중간 산출물이 함께 섞여 있었음.
- 최종 제출용으로 남긴 파일:
  - `outputs/bteam_review/final_verified_filled_2001.csv`
  - `outputs/bteam_review/final_verified_filled_2001_summary.csv`
  - `outputs/bteam_review/final_verified_filled_2001_review_samples.csv`
- 중간 산출물로 이동한 파일:
  - `outputs/bteam_review/archive_intermediate/table_claim_mapping_filled_2001.csv`
  - `outputs/bteam_review/archive_intermediate/verified_claims_filled_2001.csv`
  - `outputs/bteam_review/archive_intermediate/table_claim_mapping_manual_todo_197.csv`
  - `outputs/bteam_review/archive_intermediate/verified_claims_manual_todo_197.csv`
- 삭제한 파일:
  - `__pycache__/`
- 정리 기준:
  - 최종 제출/검토에는 `final_verified_filled_2001.csv`를 사용함.
  - `table_claim_mapping_*`, `verified_claims_*`는 재현과 디버깅용 중간 파일이므로 archive로 보관함.

## 23. 2,001건 제출용 검증 보정 및 원인분석

- 상황:
  - `bteam_kosis_review_filled.csv` 2,001건을 KOSIS API로 조회한 뒤 `verify_claim.py`를 돌렸으나, 불일치가 1,600건 이상으로 과도하게 많았음.
  - 샘플 확인 결과, 뉴스가 틀렸다는 의미가 아니라 자동 검증 로직의 단위/시점/항목 매칭 한계가 많이 섞여 있었음.
- 확인한 주요 오류:
  - 무역 통계는 KOSIS 값이 `천달러` 단위인데, 기사 claim은 `억달러` 단위로 표현되어 직접 비교 시 전부 불일치처럼 보임.
  - `작년`, `지난달` 같은 상대 시점이 있는데 A팀 `year` 컬럼에는 비교 기준 연도만 들어가 검증 대상 시점이 밀리는 경우가 있었음.
  - 월별/분기별 증감률 claim은 최근 30개 시점만 가져오면 전년동월/전년동기 비교값이 부족할 수 있었음.
  - 반도체/자동차/화장품 등 품목별 수출 claim이 전체 수출입 항목으로 비교되는 경우가 많았음.
  - 전망/목표/예상 문장, 개별 가격 문장처럼 KOSIS 공식 통계와 직접 비교하기 어려운 claim이 섞여 있었음.
- 처리:
  - `fetch_kosis_actual_values.py` 수정:
    - `--period-count` 옵션 추가.
    - 월/분기/상대 시점(`작년`, `지난달`) 추정 로직 추가.
    - 한 문장에 여러 연도가 있을 때 최신 검증 대상 연도를 우선하도록 보정.
  - `refine_filled_verification.py` 추가:
    - 무역 `천달러 -> 억달러/만달러` 단위 변환.
    - 증감률 claim인데 `actual_change_pct`가 없으면 수준값과 억지 비교하지 않고 판단불가 처리.
    - claim 문장에서 단위가 붙은 숫자를 우선 선택하도록 보정.
  - `build_bteam_submission_package.py` 추가:
    - 전체 2,001건을 `일치`, `재검토 필요`, `판단불가` 제출 큐로 분리.
  - `analyze_refined_recheck_causes.py` 추가:
    - 재검토/판단불가 행에 원인 라벨을 붙여 A팀/B팀 공유가 가능하게 함.
- 최종 결과:
  - 전체: 2,001건
  - 바로 제출 가능한 일치: 70건
  - 재검토 필요: 1,621건
  - 판단불가: 310건
- 재검토 원인 상위:
  - 기타 수동확인 필요: 710건
  - 시점 기준 재확인(증감률): 372건
  - 무역 세부품목 코드 불일치 가능성: 251건
  - API 조회 실패: 184건
  - 전망/정책 문장: 163건
  - 증감 계산값 없음: 123건
  - 개별 가격 문장: 117건
- 최종 산출물:
  - `outputs/bteam_review/final_verified_filled_2001_refined_v3.csv`
  - `outputs/bteam_review/submission_verified_matches.csv`
  - `outputs/bteam_review/submission_recheck_needed.csv`
  - `outputs/bteam_review/submission_unverifiable.csv`
  - `outputs/bteam_review/submission_recheck_cause_analysis.csv`
  - `outputs/bteam_review/submission_recheck_cause_summary.csv`
  - `outputs/bteam_review/submission_bteam_status_report.md`
- 판단:
  - 2,001건 전체를 최종 정답으로 제출하는 것은 위험함.
  - 현재 제출 가능한 것은 `submission_verified_matches.csv` 70건이며, 나머지는 재검토 큐와 원인분석 파일로 함께 제출하는 것이 안전함.

## 24. 제출용 파일 최종 정리

- 상황:
  - v1, refined v1, refined v2, mismatch 원인분석 등 중간 실험 파일이 `outputs/bteam_review/`에 함께 있어 제출 파일이 잘 안 보였음.
- 처리:
  - 최종 제출 기준은 `refined_v3`와 `submission_*` 파일로 고정함.
  - v3 이전 실험 파일은 삭제하지 않고 `outputs/bteam_review/archive_intermediate/`로 이동함.
- 최종적으로 직접 보면 되는 파일:
  - `outputs/bteam_review/final_verified_filled_2001_refined_v3.csv`
  - `outputs/bteam_review/final_verified_filled_2001_refined_v3_summary.csv`
  - `outputs/bteam_review/final_verified_filled_2001_refined_v3_review_samples.csv`
  - `outputs/bteam_review/submission_verified_matches.csv`
  - `outputs/bteam_review/submission_recheck_needed.csv`
  - `outputs/bteam_review/submission_unverifiable.csv`
  - `outputs/bteam_review/submission_recheck_cause_analysis.csv`
  - `outputs/bteam_review/submission_recheck_cause_summary.csv`
  - `outputs/bteam_review/submission_bteam_status_report.md`
- 정리 근거:
  - `refined_v3`는 KOSIS 실제값 재조회, 상대 시점 보정, 무역 단위 보정, 재검토 원인 라벨링까지 반영한 최신 결과임.
  - 이전 파일은 결과 비교와 재현을 위해 보관하되, 제출 기준으로 혼동되지 않게 archive에 둠.

## 25. 제출용 외 산출물 삭제

- 상황:
  - 사용자가 "딱 필요한 것만 놔두고 다 지워달라"고 요청함.
  - `outputs/bteam_review/` 안에 이전 작업 파일과 중간 실험 파일이 많아 최종 제출 파일 식별이 어려웠음.
- 삭제한 항목:
  - `__pycache__/`
  - `outputs/bteam_review/archive_intermediate/`
  - `outputs/bteam_review/final_verified_filled_2001_refined_v3_review_samples.csv`
  - `outputs/bteam_review/manual_selection_summary.csv`
  - `outputs/bteam_review/oversized_candidates_filtered.csv`
  - `outputs/bteam_review/bteam_kosis_codebook_needed.csv`
  - `outputs/bteam_review/bteam_kosis_review_all.csv`
  - `outputs/bteam_review/bteam_kosis_review_manual_todo.csv`
  - `outputs/bteam_review/bteam_kosis_review_summary.csv`
  - `outputs/bteam_review/bteam_kosis_tbl_meta_candidates.csv`
- 남긴 항목:
  - `outputs/bteam_review/bteam_kosis_review_filled.csv`
  - `outputs/bteam_review/final_verified_filled_2001_refined_v3.csv`
  - `outputs/bteam_review/final_verified_filled_2001_refined_v3_summary.csv`
  - `outputs/bteam_review/submission_verified_matches.csv`
  - `outputs/bteam_review/submission_recheck_needed.csv`
  - `outputs/bteam_review/submission_unverifiable.csv`
  - `outputs/bteam_review/submission_recheck_cause_analysis.csv`
  - `outputs/bteam_review/submission_recheck_cause_summary.csv`
  - `outputs/bteam_review/submission_bteam_status_report.md`
- 삭제 근거:
  - 최종 제출/공유에는 `submission_*` 파일과 `final_verified_filled_2001_refined_v3.csv`만 필요함.
  - `bteam_kosis_review_filled.csv`는 최종 결과를 재생성할 때 필요한 원본 입력이라 보존함.
  - 나머지는 이전 실험 결과, 수동검토 보류 파일, 샘플/임시 파일이므로 현재 제출 기준에서는 제외함.

## 26. target 컬럼 보강 파일 추가

- 상황:
  - `/Users/gu/Downloads/bteam_kosis_review_enriched.csv` 파일을 전달받음.
  - 기존 `bteam_kosis_review_filled.csv`에 부족했던 검증 대상 숫자/단위/시점/검증 가능 여부/claim 유형 컬럼이 반영된 파일임.
- 추가 위치:
  - `outputs/bteam_review/bteam_kosis_review_enriched.csv`
- 확인 결과:
  - 전체 행 수: 2,001건
  - 전체 컬럼 수: 30개
  - 추가 확인한 핵심 컬럼:
    - `target_number`
    - `target_unit`
    - `time_basis`
    - `verifiable`
    - `claim_type`
  - `target_number`, `target_unit`은 1,985건 채워져 있고 16건은 비어 있음.
  - `time_basis`, `verifiable`, `claim_type`은 2,001건 모두 채워져 있음.
- 판단:
  - 앞으로 재검증을 돌릴 때는 `bteam_kosis_review_filled.csv`보다 `bteam_kosis_review_enriched.csv`를 우선 입력으로 사용하는 것이 좋음.
  - 16건의 target 값 공백은 판단불가 또는 수동보완 대상으로 처리하면 됨.

## 27. 기존 filled 입력 파일 삭제

- 상황:
  - `bteam_kosis_review_enriched.csv`가 기존 `bteam_kosis_review_filled.csv`와 같은 2,001건을 포함하면서, 추가로 `target_number`, `target_unit`, `time_basis`, `verifiable`, `claim_type`까지 보강함.
- 처리:
  - `outputs/bteam_review/bteam_kosis_review_filled.csv` 삭제.
- 삭제 근거:
  - enriched 파일이 filled 파일의 상위 버전이므로 두 파일을 동시에 두면 이후 검증 입력 파일을 헷갈릴 수 있음.
  - 앞으로 기준 입력은 `outputs/bteam_review/bteam_kosis_review_enriched.csv`로 통일함.

## 28. enriched 기준 재검증

- 상황:
  - `bteam_kosis_review_enriched.csv`에는 `target_number`, `target_unit`, `time_basis`, `verifiable`, `claim_type`이 보강되어 있음.
  - 기존 검증 스크립트는 한국어 `claim_type`(`수준값`, `증감률`, `전망·예측`, `순위`, `개별상품가격`)을 그대로 내부 타입으로 해석하지 못했음.
- 처리:
  - `verify_claim.py` 수정:
    - 한국어 `claim_type`을 내부 타입(`LEVEL`, `CHANGE_RATE`, `UNVERIFIABLE`)으로 변환.
    - `verifiable=False` 또는 비검증 타입은 억지 비교하지 않고 판단불가 처리.
  - `refine_filled_verification.py` 수정:
    - `target_number`를 우선 사용.
    - `target_unit` 기준으로 무역 통계 단위 변환(`천달러 -> 달러/억달러/만달러`) 처리.
    - `전망·예측`, `순위`, `개별상품가격`은 `판단불가_검증대상아님`으로 분리.
  - `build_bteam_submission_package.py`, `analyze_refined_recheck_causes.py` 수정:
    - `--input`, `--prefix` 옵션을 추가해 enriched 결과를 별도 파일명으로 생성 가능하게 함.
- 실제값 처리:
  - `fetch_kosis_actual_values.py`로 `table_claim_mapping_enriched.csv`를 이어받아 조회했으나 중간 파일이 1,440건으로 저장되어 누락 발생.
  - 해결: 기존 2,001건 실제값 조회 결과를 `bteam_kosis_review_enriched.csv`에 `claim_id` 기준으로 병합해 enriched 기준 검증 파일을 생성.
- enriched 최종 결과:
  - 전체: 2,001건
  - `검증완료_일치`: 117건
  - `재검토필요_증감률불일치`: 1,345건
  - `재검토필요_수준값불일치`: 48건
  - `판단불가_증감계산값없음`: 240건
  - `판단불가_검증대상아님`: 217건
  - `판단불가_API조회실패`: 31건
  - `판단불가_파라미터미확정`: 3건
- 해석:
  - enriched 결과는 `target_number`, `target_unit`, `time_basis`, `verifiable`, `claim_type`을 반영한 현재 기준 결과임.
  - 기존에는 수준값/날짜 숫자 혼동이 있었고, enriched에서는 대부분이 증감률 claim으로 명확히 분류되어 `증감률 기준 재검토`를 별도 라벨로 분리함.
  - `검증대상아님` 217건이 분리된 것은 개선임. 전망/예측/순위/개별상품가격은 KOSIS 실제값과 직접 비교하면 안 됨.
- 최종 enriched 산출물:
  - `outputs/bteam_review/final_verified_enriched.csv`
  - `outputs/bteam_review/final_verified_enriched_summary.csv`
  - `outputs/bteam_review/submission_enriched_verified_matches.csv`
  - `outputs/bteam_review/submission_enriched_recheck_needed.csv`
  - `outputs/bteam_review/submission_enriched_unverifiable.csv`
  - `outputs/bteam_review/submission_enriched_recheck_cause_analysis.csv`
  - `outputs/bteam_review/submission_enriched_recheck_cause_summary.csv`
  - `outputs/bteam_review/submission_enriched_bteam_status_report.md`
- 정리:
  - 중간에 생성된 `table_claim_mapping_enriched.csv`, `verified_claims_enriched.csv`는 1,440건짜리 불완전 파일이라 삭제함.
  - 이후 AI 모델/제출 기준은 `outputs/bteam_review/final_verified_enriched.csv`로 통일함.

## 29. AI 모델 입력 기준 파일 정리

- 상황:
  - 이후 AI 모델에는 300건 샘플이 아니라 2,001건 전체 파일을 넣기로 함.
  - 따라서 `submission_enriched_probable_matches_300.csv`, timefix 실험 파일, old filled 기준 산출물, 중간 full 파일은 현재 기준에서 불필요함.
- 삭제한 항목:
  - `outputs/bteam_review/submission_enriched_probable_matches_300.csv`
  - `outputs/bteam_review/submission_enriched_comparison_report.md`
  - `outputs/bteam_review/final_verified_enriched_timefix.csv`
  - `outputs/bteam_review/final_verified_enriched_timefix_review_samples.csv`
  - `outputs/bteam_review/final_verified_enriched_timefix_summary.csv`
  - `outputs/bteam_review/final_verified_filled_2001_refined_v3.csv`
  - `outputs/bteam_review/final_verified_filled_2001_refined_v3_summary.csv`
  - `outputs/bteam_review/submission_bteam_status_report.md`
  - `outputs/bteam_review/submission_verified_matches.csv`
  - `outputs/bteam_review/submission_recheck_needed.csv`
  - `outputs/bteam_review/submission_unverifiable.csv`
  - `outputs/bteam_review/submission_recheck_cause_analysis.csv`
  - `outputs/bteam_review/submission_recheck_cause_summary.csv`
  - `outputs/bteam_review/table_claim_mapping_enriched_full.csv`
  - `outputs/bteam_review/table_claim_mapping_enriched_timefix.csv`
  - `outputs/bteam_review/verified_claims_enriched_full.csv`
  - `outputs/bteam_review/verified_claims_enriched_timefix.csv`
  - 루트의 불완전 중간 파일 `table_claim_mapping_enriched.csv`
- 남긴 기준 파일:
  - `outputs/bteam_review/bteam_kosis_review_enriched.csv`
  - `outputs/bteam_review/final_verified_enriched.csv`
  - `outputs/bteam_review/final_verified_enriched_summary.csv`
  - `outputs/bteam_review/submission_enriched_verified_matches.csv`
  - `outputs/bteam_review/submission_enriched_recheck_needed.csv`
  - `outputs/bteam_review/submission_enriched_unverifiable.csv`
  - `outputs/bteam_review/submission_enriched_recheck_cause_analysis.csv`
  - `outputs/bteam_review/submission_enriched_recheck_cause_summary.csv`
  - `outputs/bteam_review/submission_enriched_bteam_status_report.md`
- 판단:
  - AI 모델 메인 입력은 `final_verified_enriched.csv`로 통일함.
  - split 파일들은 학습/평가 보조용으로 유지함.

## 30. tbl_id 자동매핑 이상치 확인 후 재매핑

- 상황:
  - `final_verified_enriched.csv`를 샘플 확인한 결과, 일부 뉴스 문장에 다른 분야 `tbl_id`가 붙어 있었음.
  - 특히 `verifiable=False` 또는 검증대상아님으로 분리해야 할 문장에도 `tbl_id`가 남아 있어, 실제 매칭된 것처럼 오해될 수 있었음.
  - `무역지표`가 `국가별 수출액, 수입액(DT_1R11006_FRM101)` 또는 `품목별 수출액, 수입액(DT_1R11001_FRM101)`로 과도하게 몰림.
  - GDP/국내총생산 문장에 무역표가 붙거나, 가격/물가 문장에 무역표가 붙는 등 도메인 불일치가 일부 확인됨.
  - 정책/제도 숫자(관세, LTV, DSR, 소득 130%, 금리 등), 전망/추정 문장, 기간 숫자(4개월 연속, 46개월 만 등)가 KOSIS 직접 검증 대상으로 남아 있었음.
  - 전체 수출액/수입액 문장인데 특정 품목 코드가 붙는 행도 확인됨.
- 처리:
  - 임시 진단 CSV는 산출물로 남기지 않고 삭제함.
  - `remap_enriched_review.py`를 추가해 명백한 `tbl_id` 오염 규칙을 자동 보정함.
  - `verifiable=False`, 전망/추정/순위/개별상품가격 등 KOSIS 직접 검증 대상이 아닌 행은 `org_id`, `tbl_id`, `obj_l1`, `itm_id`, `prd_se`를 비움.
  - 정책/제도 숫자, 전망/추정 문장, 기간/순서 숫자는 `verifiable=False` 및 `판단불가_검증대상아님`으로 빠지도록 정리하고 `tbl_id` 제거.
  - GDP/국내총생산 문장은 `국내총생산과 지출(DT_200Y113)`로 보정하되, 세부 항목 코드는 추가 확인 대상으로 남김.
  - 가격/물가 문장인데 무역표가 붙은 경우 소비자물가 표로 보정.
  - 해외/시장 지표(미국/일본/중국/독일 지표, 독일 국채 10년물, PCE, 생산자물가, 원유 채굴량 등)에 국내 KOSIS 표가 붙은 경우 `tbl_id`를 제거.
  - 연간 물가 상승률 문장(`2022년 물가 상승률 5.1%` 등)은 월별 소비자물가 등락률(`DT_1J22042`)이 아니라 연도별 소비자물가 등락률(`DT_1J22041`)로 보정.
  - 전체/국가 수출입 문장은 품목별 세부 코드 대신 `국가별 수출액, 수입액(DT_1R11006_FRM101)`의 전체/국가 코드로 보정.
  - 품목 수출입 문장은 `품목별 수출액, 수입액(DT_1R11001_FRM101)`로 남기되, 세부 품목 코드는 추가 확인 대상으로 남김.
  - `검증완료_일치` 108건을 재점검해 독일 국채, 해외 CPI/PCE, 생산자물가, 전망 문장 등 오탐을 제거.
  - 최종 점검 기준에서 `검증완료_일치` 중 해외/전망/시장지표 패턴 오탐은 0건으로 정리됨.
- 재매핑 결과:
  - 전체: 2,001건
  - `검증완료_일치`: 87건
  - `재검토필요_증감률불일치`: 667건
  - `재검토필요_수준값불일치`: 31건
  - `판단불가_검증대상아님`: 834건
  - `판단불가_증감계산값없음`: 336건
  - `판단불가_파라미터미확정`: 27건
  - `판단불가_API조회실패`: 20건
- 해석:
  - 일치 건수는 87건으로 줄었지만, 잘못된 `tbl_id`를 억지로 남기지 않게 하여 매핑 품질은 개선됨.
  - `tbl_id`가 비어 있는 행은 "KOSIS 후보가 아예 없다"가 아니라, 현재 자동 규칙으로 확정하면 오매칭 위험이 커서 후보 재검색/수동확인이 필요한 행임.
  - 이 결과는 "뉴스가 틀렸다"가 아니라, 자동매핑 기준에서 바로 검증 가능한 claim과 제외/재검토해야 할 claim을 더 엄격히 분리한 베이스라인임.

## 31. 불필요 파일 정리

- 상황:
  - 최종 기준 파일은 `outputs/bteam_review/final_verified_enriched.csv`와 `submission_enriched_*` 산출물로 정리됨.
  - 이후 제출/공유 기준에서 사용하지 않는 실험 파일과 실행 캐시가 남아 있어 파일 구조가 복잡해짐.
- 삭제한 항목:
  - `__pycache__/`
  - `.DS_Store`
  - `outputs/.DS_Store`
  - `analyze_claim_schema_v3_pilot.py`
  - `config/`
  - `data/claims/claim_schema_v3_pilot100.csv`
  - `docs/kosis_claim_schema_redesign.md`
  - `outputs/bteam_review/claim_schema_v3_pilot100_analysis.md`
  - `outputs/bteam_review/claim_schema_v3_pilot100_issues.csv`
- 삭제 기준:
  - `.DS_Store`, `__pycache__`는 OS/파이썬 실행 캐시라 재생성 가능함.
  - `claim_schema_v3_pilot100` 계열은 현재 최종 제출 파이프라인(`bteam_kosis_review_enriched.csv` -> `final_verified_enriched.csv` -> `submission_enriched_*`)에 포함되지 않는 별도 실험 파일이라 제거함.
- 유지한 항목:
  - KOSIS 인덱스: `kosis_table_summary.csv`
  - KOSIS 메타 요약: `kosis_metadata_summary.csv`
  - B팀 최종 입력: `outputs/bteam_review/bteam_kosis_review_enriched.csv`
  - B팀 최종 검증 결과: `outputs/bteam_review/final_verified_enriched.csv`
  - 제출용 분할 결과: `outputs/bteam_review/submission_enriched_verified_matches.csv`, `submission_enriched_recheck_needed.csv`, `submission_enriched_unverifiable.csv`
  - 상태 보고서/원인 분석: `submission_enriched_bteam_status_report.md`, `submission_enriched_recheck_cause_analysis.csv`, `submission_enriched_recheck_cause_summary.csv`

## 32. claim_schema_v3_pilot100 기준 재정리 및 검증

- 상황:
  - 기존 2,001건 enriched 파일은 자동매핑 오탐이 많아 기준 파일이 계속 헷갈렸음.
  - 이후 작업은 `claim_schema_v3_pilot100.csv`만 기준으로 진행하기로 함.
  - 해당 파일은 문장 단위가 아니라 measurement 단위로 숫자가 분리되어 있어 `value`, `unit`, `indicator`, `period`, `prd_se`, `verifiable_kosis`를 직접 활용할 수 있음.
- 처리:
  - `/Users/gu/Downloads/claim_schema_v3_pilot100.csv`를 `data/claims/claim_schema_v3_pilot100.csv`로 복사함.
  - `outputs/bteam_review/`에 있던 기존 2,001건 enriched 산출물을 삭제함.
  - pilot100 전용 검증 스크립트 `verify_claim_schema_v3_pilot.py`를 추가함.
  - 자동 검증 가능한 반복 지표만 KOSIS 표와 연결함.
    - 출생아수/합계출산율/혼인건수: 인구동향조사
    - 소비자물가지수/소비자물가상승률/생활물가지수: 소비자물가조사
    - 실업률/고용률/취업자수: 경제활동인구조사
  - 품목별 물가, 지역별 고용률, 금융·금리, 부동산, 개별 산업/품목처럼 세부 코드가 필요한 항목은 억지 매핑하지 않고 판단불가로 분리함.
- 결과:
  - 입력: `data/claims/claim_schema_v3_pilot100.csv`
  - 전체 행: 94건
  - `verifiable_kosis=Y`: 60건
  - `verifiable_kosis=N`: 34건
  - 출력: `outputs/bteam_review/claim_schema_v3_pilot100_verified.csv`
  - 요약: `outputs/bteam_review/claim_schema_v3_pilot100_summary.csv`
  - 판정 결과:
    - 일치: 15건
    - 불일치: 9건
    - 판단불가: 70건
- 해석:
  - 판단불가 70건 중 34건은 원본에서 이미 `verifiable_kosis=N`인 행임.
  - 나머지는 KOSIS로 검증 가능성이 있어도 현재 자동 코드북에 품목/지역/세부 분류 코드가 없어서 보류한 행임.
  - pilot100 기준에서는 target 숫자가 명확해졌기 때문에, 2,001건 enriched보다 검증 설계가 훨씬 안정적임.

## 33. 자동매핑 방식 변경: 키워드 매칭에서 indicator 코드북 매핑으로 전환

- 문제:
  - 기존 2,001건 방식은 `claim_text`, `metric` 키워드로 KOSIS 통계표명을 검색해 후보 `tbl_id`를 붙였음.
  - `claim_schema_v3_pilot100.csv`는 컬럼 구조가 달라져 기존 방식이 맞지 않음.
  - 새 파일은 `indicator`, `value`, `unit`, `value_type`, `period`, `prd_se`, `region`, `age_group`, `gender`, `industry_or_item`이 이미 분리되어 있음.
- 변경한 방식:
  - `claim_text` 키워드 검색 중심 자동매핑을 사용하지 않음.
  - `indicator`를 1차 키로 사용하고, `prd_se`, `unit`, `value_type`, `region`, `age_group`을 함께 보아 KOSIS 코드북을 적용함.
  - 코드북 파일을 새로 생성함: `data/claims/kosis_indicator_codebook_pilot100.csv`
- 예시:
  - `indicator=출생아수`, `prd_se=M` -> `DT_1B8000G`, `obj_l1=00`, `obj_l2=10`, `itm_id=T1`
  - `indicator=소비자물가지수`, `unit=지수` -> `DT_1J22003`, `obj_l1=T10`, `itm_id=T`
  - `indicator=소비자물가상승률`, `prd_se=M` -> `DT_1J22042`, `obj_l1=0`, `itm_id=T03`
  - `indicator=실업률`, `age_group=20~29세` -> `DT_1DA7002S`, `obj_l1=20`, `itm_id=T80`
- 처리 결과:
  - `verify_claim_schema_v3_pilot.py`에 indicator 코드북 방식 반영.
  - 결과 파일 `claim_schema_v3_pilot100_verified.csv`에 `mapping_source` 컬럼 추가.
  - 새 기준으로 재검증 후 결과는 `일치 15건`, `불일치 9건`, `판단불가 70건`.
- 판단:
  - 이제 `tbl_id` 값은 이전 자동 키워드 후보와 달라질 수 있음.
  - 새 기준에서는 “비슷한 표 후보”가 아니라 “indicator에 대응하는 공식 표/분류/항목 코드”를 넣는 것이 맞음.
  - 코드북에 없는 항목은 억지로 `tbl_id`를 붙이지 않고 판단불가로 남기는 것이 오탐을 줄이는 방향임.

## 34. `a_team_005_100.csv` 기준 재실행 및 자동매핑 판단

- 상황:
  - 새 A팀 파일 `/Users/gu/Downloads/a_team_005_100.csv`를 전달받음.
  - 기존 pilot100 기준 파일과 결과는 혼선을 줄이기 위해 삭제하고, 새 파일만 기준으로 진행함.
- 처리:
  - 새 입력 파일을 `data/claims/a_team_005_100.csv`로 복사함.
  - 기존 `outputs/bteam_review/claim_schema_v3_pilot100_verified.csv`, `claim_schema_v3_pilot100_summary.csv` 삭제.
  - 코드북 이름을 `data/claims/kosis_indicator_codebook.csv`로 변경해 pilot100 전용처럼 보이지 않게 정리.
  - `verify_claim_schema_v3_pilot.py`에 `--input`, `--output`, `--summary` 옵션을 추가해 새 파일에도 실행 가능하게 수정.
  - `a_team_005_100.csv` 기준 자동매핑/검증 실행.
- 입력 구조:
  - 전체 111건
  - `verifiable_kosis=N`: 92건
  - `verifiable_kosis=Y`: 19건
  - 주요 신규 indicator:
    - 정부 연간 누적 대출액
    - 수출량
    - 외국인 직접투자 금액
    - 예대금리차
    - 경제성장률
    - 청년층 고용률
    - 소비자심리지수
- 결과:
  - 출력: `outputs/bteam_review/a_team_005_100_verified.csv`
  - 요약: `outputs/bteam_review/a_team_005_100_summary.csv`
  - 판정 결과:
    - 일치: 0건
    - 불일치: 0건
    - 판단불가: 111건
  - `tbl_id` 매핑:
    - `DT_1DA7002S`: 2건(청년층 고용률)
    - 공백: 109건
- 판단불가 사유:
  - 92건: 원본에서 이미 `verifiable_kosis=N`
  - 17건: 현재 코드북에 자동 매핑 룰 없음
  - 2건: 청년층 고용률로 `tbl_id`는 붙었으나 `period=작년5월`, `prd_se=Y` 형태라 KOSIS 월간 시점으로 바로 변환 불가
- 결론:
  - 기존 pilot100 코드북/자동매핑을 그대로 사용하면 안 됨.
  - 새 파일은 경제성장률, 수출량, FDI, 예대금리차, 정부 대출액 등 기존 코드북에 없는 지표가 많아 코드북 확장이 필요함.
  - 특히 `period` 값이 `작년5월`, `2025.01~06`, `2024년12월`처럼 들어와 있어 KOSIS용 `YYYYMM`, `YYYY`, `YYYYQn` 형식으로 정규화하는 전처리도 추가해야 함.
  - 따라서 다음 작업은 `a_team_005_100.csv`의 `verifiable_kosis=Y` 19건부터 대상으로 indicator별 KOSIS 표/코드북을 새로 확장하는 것임.

## 35. `hcx_extracted.csv` 기준 자동매핑 재설계 및 검증

- 상황:
  - 새 파일 `/Users/gu/Downloads/hcx_extracted.csv`를 전달받음.
  - 이전 `a_team_005_100` 결과는 삭제하고, `hcx_extracted.csv`만 기준으로 진행하기로 함.
- 처리:
  - 새 입력 파일을 `data/claims/hcx_extracted.csv`로 복사함.
  - 기존 `outputs/bteam_review/*.csv` 결과를 삭제하고 hcx 기준 결과만 생성함.
  - `verify_claim_schema_v3_pilot.py`의 자동매핑 방식을 hcx 구조에 맞춰 수정함.
- 자동매핑 변경 사항:
  - `indicator` 띄어쓰기/표기 차이를 정규화함.
    - `출생아 수` -> `출생아수`
    - `취업자 수` -> `취업자수`
    - `소비자물가 상승률`, `물가상승률` -> `소비자물가상승률`
    - `고령층 고용률` -> 65세 이상 고용률 코드
  - `period` 형식 정규화 추가.
    - `2025M04` -> `202504`
    - `2025년 10월` -> `202510`
    - `2024M11` -> `202411`
    - `2024Q2` -> `202402`
  - `증감값`, `%포인트`, `포인트` 단위도 증감 비교 대상으로 처리.
  - 수입물가지수, 생산자물가지수 기본분류 총지수 코드 일부 추가.
  - 코드북 `data/claims/kosis_indicator_codebook.csv`에도 hcx에서 쓰인 indicator 별칭을 반영함.
- 결과:
  - 입력: `data/claims/hcx_extracted.csv`
  - 전체 행: 122건
  - `verifiable_kosis=Y`: 50건
  - `verifiable_kosis=N`: 72건
  - 출력: `outputs/bteam_review/hcx_extracted_verified.csv`
  - 요약: `outputs/bteam_review/hcx_extracted_summary.csv`
  - 판정 결과:
    - 일치: 12건
    - 불일치: 4건
    - 판단불가: 106건
  - `tbl_id` 매핑:
    - `DT_1DA7001S`: 7건
    - `DT_1J22042`: 6건
    - `DT_1DA7002S`: 2건
    - `DT_1J22003`: 2건
    - `DT_404Y014`: 2건
    - `DT_1B8000G`: 2건
    - `DT_1B8000F`: 1건
- 판단:
  - 기존 2,001건 키워드 자동매핑 방식은 사용하면 안 됨.
  - schema v3/hcx 계열 파일은 `indicator`, `period`, `prd_se`, `value_type`, `region`, `age_group`, `industry_or_item` 기반 코드북 매핑으로 가는 것이 맞음.
  - 이번 수정으로 `tbl_id` 매핑 가능한 행은 늘었지만, 산업별 취업자/품목별 물가/지역별 고용률/생활물가-소비자물가 차이처럼 세부 코드북이 필요한 항목은 계속 판단불가로 남김.
