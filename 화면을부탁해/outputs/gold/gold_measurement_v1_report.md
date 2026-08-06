# Measurement 골드 v1 동결 보고서

## 동결 데이터

- 전체 행: 109
- 고유 measurement ID: 109
- 기준 통일에 따른 라벨 변경: 10
- gold_verifiable: {'N': 77, 'Y': 32}
- gold_measurement_correct: {'Y': 82, 'N': 27}

## 무역 scope 교정 후 게이트 기준선

- READY: 39
- REJECTED: 70
- True positive: 29
- False positive: 10
- False negative: 3
- 게이트 정밀도: 74.4%
- 게이트 재현율: 90.6%
- READY 추출 필드 정확도: 84.6%

## 동결 라벨 기준

- KOSIS_VALUE: 사람이 확정한 gold_verifiable 라벨을 유지한다.
- POLICY_VALUE, CONDITION, CONTEXT: gold_verifiable=N으로 통일한다.
- 원본 gold_measurement_merged.csv는 수정하지 않는다.
- 검색·verdict 지표는 이 동결 입력으로 새로 생성한 실행 산출물만 채점한다.
- 기존 69.0% 재현율은 기준 통일 전 수치이며, v1 동결 기준 재현율은 90.6%다.
