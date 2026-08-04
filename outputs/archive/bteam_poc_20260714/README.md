# B팀 KOSIS Legacy PoC Archive

이 폴더는 2026-07-14 enriched 통합 이전에 사용한 PoC·표본 검증 산출물을 보존한다.

현재 제출 기준 파일이 아니며, 실행 이력과 판단 변화 추적에만 사용한다.

## 구성

- `table_claim_mapping.csv`: 초기 197건 KOSIS 매핑 입력
- `verified_claims.csv`: 초기 PoC 결과 197건(일치 5, 불일치 131, 판단불가 61)
- `bteam_verification/`: 24건 표본, 70건 재실행, 4,403건 수동검토 큐 등 기존 검증 산출물
- `legacy_review/`: enriched 통합 전에 사용한 2,001건 기준 파일·분할 제출 파일·상태 보고서
- `scripts/archive/bteam_poc_20260714/`: 기존 PoC와 검토 큐 생성 스크립트

## 현재 기준

- 원격 보강 기준: `outputs/bteam_review/final_verified_enriched.csv`
- 통합 감사 기준: `outputs/bteam_review/final_verified_enriched_audited.csv`
- 수동 확정 제출: `outputs/bteam_review/submission_integrated_verified_matches.csv`
- 골드 평가: `outputs/bteam_gold/`
- 독립 홀드아웃 평가: `outputs/bteam_holdout/`

