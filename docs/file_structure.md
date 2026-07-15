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

A팀이 준 claim 데이터와 현재 검증 기준 입력 파일.

- `claim_df_with_metric_v2.csv`: 최신 원본 claim 데이터
- `claim_df_with_metric_v2_is_claim.csv`: `is_claim=True`만 필터링한 파일
- `claim_df_with_metric_v2_kosis_like.csv`: KOSIS 검토 우선 대상 파일
- `hcx_extracted.csv`: 현재 기준 파일. measurement 단위로 쪼개진 A팀/HCX 추출 검증 입력 122행
- `kosis_indicator_codebook.csv`: `indicator -> KOSIS tbl_id/obj_l1/obj_l2/itm_id` 코드북

## `outputs/bteam_review/`

B팀 KOSIS 매칭/검토 산출물. 현재는 `hcx_extracted.csv` 기준 결과만 유지한다.

- `hcx_extracted_verified.csv`: `hcx_extracted.csv` 기준 KOSIS 실제값 비교 결과
- `hcx_extracted_summary.csv`: `hcx_extracted.csv` 검증 결과 요약

현재 `hcx_extracted.csv` 검증 결과:

- 전체 122건
- 일치 12건
- 불일치 4건
- 판단불가 106건

참고:

- 기존 2,001건 enriched 산출물, pilot100 산출물, `a_team_005_100` 산출물은 현재 기준 혼선을 줄이기 위해 삭제했다.
- 이후 작업 기준은 `hcx_extracted.csv` -> `hcx_extracted_verified.csv`이다.
- 판단불가가 많은 이유는 입력 122건 중 72건이 원본에서 이미 `verifiable_kosis=N`이고, 나머지는 산업별 취업자/품목별 물가/지역별 고용률처럼 세부 코드북이 필요한 항목이기 때문이다.

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
