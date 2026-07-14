# 파일 구조 정리

## 루트

- `*.py`: 실행 코드
- `README.md`: 프로젝트 기본 설명
- `.env`: KOSIS API key 보관 파일, GitHub에 올리면 안 됨
- `kosis_table_summary.csv`: KOSIS 통계표 전체 인덱스
- `kosis_metadata_summary.csv`: 주요 통계표 메타정보 요약

## `data/`

- `chosun_full.csv`: A팀 원본 조선일보 기사 코퍼스 전체 (용량 문제로 `.gitignore` 처리, 로컬에만 보관)

## `data/claims/`

A팀이 준 최신 claim 데이터와 B팀 필터링 입력 파일.

- `claim_df_with_metric_v2.csv`: 최신 원본 claim 데이터
- `claim_df_with_metric_v2_is_claim.csv`: `is_claim=True`만 필터링한 파일
- `claim_df_with_metric_v2_kosis_like.csv`: KOSIS 검토 우선 대상 파일

## `outputs/bteam_review/`

B팀 KOSIS 매칭/검토 산출물.

- `bteam_kosis_review_filled.csv`: `tbl_id`가 자동 매칭된 2,001건 원본 입력
- `final_verified_filled_2001_refined_v3.csv`: 시점/단위 후처리까지 반영한 2,001건 최종 검증 상세 파일
- `final_verified_filled_2001_refined_v3_summary.csv`: 최종 검증 결과 요약
- `submission_verified_matches.csv`: 바로 제출 가능한 일치 70건
- `submission_recheck_needed.csv`: 표/항목/시점/단위 재검토 필요 1,621건
- `submission_unverifiable.csv`: API/파라미터/증감 계산 문제로 판단불가 310건
- `submission_recheck_cause_analysis.csv`: 재검토/판단불가 행별 원인 라벨
- `submission_recheck_cause_summary.csv`: 재검토/판단불가 원인 요약
- `submission_bteam_status_report.md`: A팀/팀 공유용 제출 상태 보고서

## `outputs/bteam_verification/`

B팀 표본 검증과 후속 수동검토 산출물.

- `bteam_kosis_review_ready.csv`: 주요 ID 4종이 채워진 1,998건
- `bteam_kosis_review_unresolved.csv`: 메타데이터 확인 후 판단불가 처리한 3건
- `bteam_kosis_review_sample.csv`: 수록주기/통계표를 섞은 24건 표본
- `bteam_kosis_claim_mapping_sample.csv`: 표본 KOSIS 실제값 조회 결과
- `bteam_kosis_verified_sample.csv`: 표본 자동 판정 결과
- `bteam_kosis_mapping_recheck_1998.csv`: 1,998건 의미 매핑 재검토 큐
- `bteam_kosis_review_manual_prioritized_4403.csv`: 4,403건 수동검토 우선순위 큐
- `bteam_kosis_review_manual_batch_001.csv`: 수동검토 1차 100건
- `B팀_KOSIS_검증_진행현황.xlsx`: 판정 근거, 표본 결과, 다음 작업 요약

## `data/archive/`

현재 기준으로 직접 작업하지 않는 예전 입력/참고 파일 + v2 파이프라인 이전(v1, claim_candidates.csv 기반 422건 배치)에 나온 산출물.

- `검증대상_기사드랍후.*`: 이전 A팀 전달본
- `claim_candidates_from_xlsx.csv`: 이전 변환본
- `kosis_table_summary_p2_b.csv`, `kosis_table_summary_a_d.csv`: 과거 부분 크롤링 산출물
- `kosis_metadata_summary_팀원이름.csv`, `kosis_metadata_summary_김진성.csv`: 팀원별 메타 요약 파일
- `뉴스_노이즈_제거_파이프라인 (1).ipynb`: 참고용 노트북
- `candidate_claim_articles.csv`, `claim_candidates_filtered.csv`, `claim_candidates_top.csv`: v1 배치(422건)용 claim 후보 입력 파일
- `table_claim_mapping_v1.csv`, `table_claim_mapping_v1_구정현.csv`: v1 배치(422건) 매칭/검토 결과 (v2 파이프라인으로 대체됨)
- 참고: `table_claim_mapping_김진성.csv`(v1 배치 김진성 몫, 42건 obj_l1/itm_id 수동 선택까지 완료)는 샌드박스 캐시 문제로 아직 정리 못함 — 로컬에서 `data/archive/`로 직접 옮겨주세요

## `docs/`

설명 문서와 템플릿.

- `docs_bteam_pipeline.md`: B팀 전체 파이프라인 설명
- `kosis_param_guide.md`: KOSIS API 파라미터 가이드
- `file_structure.md`: 현재 파일 구조 설명
- `templates/통계표_관찰_템플릿.xlsx`: 표 관찰용 템플릿

## `logs/`

작업 기록과 트러블슈팅 로그.

- `baseline_26-07-13.md`
- `troubleshooting_26-07-13.md`
