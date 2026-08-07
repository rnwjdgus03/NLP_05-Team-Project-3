# KOSIS 코드북 v2 새 독립 표본 검토 준비

## 상태

- 골드100과 첫 홀드아웃100의 claim_id·article_id 중복 0건
- 표본: 100건, 분야별 {'물가': 20, '고용': 20, '무역': 20, '인구': 20, '소매': 20}
- 모집단 출처: {'outputs\\bteam_review\\final_verified_filled_2001_remapped_v6.csv': 53, 'outputs\\archive\\bteam_poc_20260714\\bteam_verification\\bteam_kosis_review_manual_prioritized_4403.csv': 47}
- 코드북 v2 자동 결정: {'보류': 65, '검증불가': 29, '검증가능': 6}
- 자동 매핑 API 결과: {'Y': 6}
- 현재 파일의 gold_* 컬럼은 비어 있으며 사람이 확정하기 전까지 품질 게이트를 계산하지 않는다.

## 수동 확정 순서

1. KOSIS 검증 가능 여부와 판단불가 사유를 확정한다.
2. 검증 가능하면 올바른 기관·통계표·분류·항목·주기를 입력한다.
3. 목표 수치와 정확 시점·비교 시점을 입력한다.
4. KOSIS 값과 최종 판정 및 근거를 기록한다.
5. 100건을 모두 확정한 뒤 코드북 v2를 수정하지 않은 상태로 80% 게이트를 계산한다.

## 파일

- `holdout2_100_selection.csv`: 새 독립 표본
- `holdout2_100_review.csv`: 자동 예측 + 수동 골드 입력용
- `holdout2_auto_api_cache.json`: 자동 매핑 API 캐시
