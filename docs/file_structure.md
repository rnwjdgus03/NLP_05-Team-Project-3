# 파일 구조 정리

## 루트

- `*.py`: 실행 코드
- `README.md`: 프로젝트 기본 설명
- `.env`: KOSIS API key 보관 파일, GitHub에 올리면 안 됨
- `kosis_table_summary.csv`: KOSIS 통계표 전체 인덱스
- `kosis_metadata_summary.csv`: 주요 통계표 메타정보 요약
- `integrate_enriched_audit.py`: 원격 enriched 2,001건과 로컬 수동 감사를 통합하는 최종 감사 스크립트

## `data/`

- `chosun_full.csv`: A팀 원본 조선일보 기사 코퍼스 전체 (용량 문제로 `.gitignore` 처리, 로컬에만 보관)

## `data/claims/`

A팀이 준 최신 claim 데이터와 B팀 필터링 입력 파일.

- `claim_df_with_metric_v2.csv`: 최신 원본 claim 데이터
- `claim_df_with_metric_v2_is_claim.csv`: `is_claim=True`만 필터링한 파일
- `claim_df_with_metric_v2_kosis_like.csv`: KOSIS 검토 우선 대상 파일

## `outputs/bteam_review/`

B팀 KOSIS 매칭/검토 산출물.

- `bteam_kosis_review_enriched.csv`: `target_number`, `target_unit`, `time_basis`, `verifiable`, `claim_type`이 보강된 2,001건 기준 입력
- `final_verified_enriched.csv`: 원격 enriched 자동 실행 기준 파일. 통합 감사의 입력이며 최종 제출 판정이 아님
- `final_verified_enriched_summary.csv`: 원격 enriched 자동 실행 요약
- `submission_enriched_auto_match_candidates_117.csv`: 원격 자동 수치 일치 후보 117건. 수동 확정으로 간주하지 않음
- `submission_enriched_recheck_needed.csv`: 원격 enriched 기준 재검토 1,393건
- `submission_enriched_unverifiable.csv`: 원격 enriched 기준 판단불가 491건
- `submission_enriched_recheck_cause_analysis.csv`: enriched 기준 재검토/판단불가 원인 라벨
- `submission_enriched_recheck_cause_summary.csv`: enriched 기준 재검토/판단불가 원인 요약
- `submission_enriched_bteam_status_report.md`: 통합 감사 전 원격 자동 실행 참고 보고서

통합 감사 후 현재 기준 산출물.

- `final_verified_enriched_audited.csv`: 원격 enriched와 로컬 엄격 감사를 합친 2,001건 전체 기준 파일
- `submission_integrated_verified_matches.csv`: 표·항목·단위·시점·값을 수동 확정한 21건
- `submission_integrated_recheck_needed.csv`: 자동 일치 후보를 포함한 재검토 1,462건
- `submission_integrated_unverifiable.csv`: KOSIS 직접검증 판단불가 518건
- `submission_integrated_local_manual_recovered_4.csv`: 원격 후보에서 빠졌으나 근거를 재확인한 수동 확정 4건
- `submission_integrated_summary.csv`: 통합 전후 건수 요약
- `submission_integrated_bteam_status_report.md`: 현재 팀 공유·발표 기준 보고서

## `outputs/bteam_gold/`, `outputs/bteam_holdout/`

- `outputs/bteam_gold/`: 개발용 골드 100건, 코드북, 1,643건 확대 적용 결과
- `outputs/bteam_holdout/`: 개발 데이터와 겹치지 않는 독립 홀드아웃 100건과 최초 평가 결과

독립 평가의 자동 결정 구간 정확도는 96.2%(25/26)지만, 보류를 포함한 항목·시점 엄격 정확도는 18.2%(6/33)다. 80% 품질 게이트를 통과하기 전에는 자동 후보를 최종 확정하지 않는다.

## `outputs/archive/bteam_poc_20260714/`

초기 197건 PoC, 과거 표본 검증, 4,403건 검토 큐, enriched 통합 전 제출 파일을 보존한다. 현재 제출 기준으로 사용하지 않는다.

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
