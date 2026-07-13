# 파일 구조 정리

## 루트

- `*.py`: 실행 코드
- `README.md`: 프로젝트 기본 설명
- `.env`: KOSIS API key 보관 파일, GitHub에 올리면 안 됨
- `kosis_table_summary.csv`: KOSIS 통계표 전체 인덱스
- `kosis_metadata_summary.csv`: 주요 통계표 메타정보 요약

## `data/claims/`

A팀이 준 최신 claim 데이터와 B팀 필터링 입력 파일.

- `claim_df_with_metric_v2.csv`: 최신 원본 claim 데이터
- `claim_df_with_metric_v2_is_claim.csv`: `is_claim=True`만 필터링한 파일
- `claim_df_with_metric_v2_kosis_like.csv`: KOSIS 검토 우선 대상 파일

## `outputs/bteam_review/`

B팀 KOSIS 매칭/검토 산출물.

- `bteam_kosis_review_all.csv`: 전체 6,404건 작업 파일
- `bteam_kosis_review_filled.csv`: `tbl_id`가 자동 매칭된 2,001건
- `bteam_kosis_review_manual_todo.csv`: 후보표 확정이 어려운 4,403건
- `bteam_kosis_review_summary.csv`: 처리 현황 요약
- `bteam_kosis_tbl_meta_candidates.csv`: 자동 매칭 표의 메타정보
- `bteam_kosis_codebook_needed.csv`: 세부 코드 확인용 코드북

## `data/archive/`

현재 기준으로 직접 작업하지 않는 예전 입력/참고 파일.

- `검증대상_기사드랍후.*`: 이전 A팀 전달본
- `claim_candidates_from_xlsx.csv`: 이전 변환본
- `kosis_table_summary_p2_b.csv`: 과거 부분 크롤링 산출물
- `kosis_metadata_summary_팀원이름.csv`: 팀원별 메타 요약 파일
- `뉴스_노이즈_제거_파이프라인 (1).ipynb`: 참고용 노트북

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
