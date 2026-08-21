# v31b 평가 결과

## 동결 식별자

- Freeze: `v31b_20260821_r1`
- Code SHA-256: `3d2b7ebf51ec456ba9bf23525539b6e2e37bb3a9d28e5e90ac2ff1ced10bc8bf`
- 동결 전 회귀 테스트: `75 passed`

## 개발 30건

| 지표 | 결과 |
|---|---:|
| Stage A 표 Top-10 | 80.0% |
| 표·ITEM Top-5 | 80.0% |
| 좌표 Top-5 | 76.7% |
| Full Top-5 | 76.7% |
| 잘못된 VALUE_MISMATCH | 0 |

## 미사용 좌표 블라인드 30건

동결 이후에 선정·잠금한 KOSIS 좌표 식별 가능 READY 주장 30건입니다.

| 지표 | Top-1 | Top-3 | Top-5 | Top-10 |
|---|---:|---:|---:|---:|
| 표 | 83.3% | 93.3% | 96.7% | 96.7% |
| ITEM | 83.3% | 93.3% | 96.7% | 96.7% |
| 좌표 | 76.7% | 90.0% | 93.3% | 93.3% |
| Full | 76.7% | 90.0% | 93.3% | 93.3% |

- 최종 claim 상태: `VERIFIED_MATCH 26`, `UNRESOLVED 4`
- 잘못된 자동 `VALUE_MISMATCH`: `0`
- 사전 등록한 6개 통과 기준: 모두 PASS

이 평가는 임의 뉴스 전체가 아니라 KOSIS 좌표가 존재하고 식별 가능한 층화 표본입니다. 따라서 수치는 검색·좌표 선택 성능을 나타내며, 서비스 전체 coverage나 언론사별 본문 수집률을 나타내지 않습니다.

## 실제 기사 E2E

3개 실제 기사에서 수동으로 선택한 5개 raw claim을 넣은 smoke test 결과:

- HCX measurements 12
- READY 5, ENRICH 6, REJECT 1
- MATCH 2, UNRESOLVED 10
- 잘못된 VALUE_MISMATCH 0

URL 자동 수집을 포함한 단일 기사 테스트에서는 제목·날짜·수치 주장 1개를 자동 추출했고, 2024년 수출액을 KOSIS 공식값과 비교해 MATCH로 완료했습니다.

## 해석

현재 강점은 좌표가 확인되는 주장에 대한 Top-5 검색과 오답 MISMATCH 억제입니다. 남은 과제는 기사 수집 성공률, HCX READY coverage, 세부 산업·대상 OBJ binding입니다. 새로운 개선 규칙은 이 블라인드 30건에 재튜닝하지 않고 별도 개발셋에서 만든 뒤 새로운 홀드아웃으로 평가해야 합니다.
