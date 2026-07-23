# KOSIS BGE Top-K Mapping-end 결과

## 목적

READY 39 measurement를 BGE-M3와 `BAAI/bge-reranker-v2-m3`로 다시 검색하고,
최종 통계표 후보 Top-1·2·3·5를 공식 KOSIS ITEM/OBJ 메타 및 실제 API 응답까지
검증해 BGE 경로에서 사용할 최소 후보 수를 정한다.

이 실험은 lexical, BGE, KURE 중 운영 검색엔진을 다시 고르는 실험이 아니다. 검색
엔진 3자 비교에서는 lexical recall@5가 62.5%, BGE/KURE가 58.3%였으므로 운영
기본은 계속 lexical이다.

## 실행 조건

- 실행일: 2026-07-23
- 입력: scope 수정 후 READY 39 measurement
- 평가: 잠긴 measurement 골드, 정답 TBL_ID 24건, ITEM/OBJ 동시 라벨 20건
- 통계표 인덱스: 107,138개
- dense 검색: `BAAI/bge-m3`, Top-50
- reranker: `BAAI/bge-reranker-v2-m3`, Top-20
- 최종 비교: Top-1, Top-2, Top-3, Top-5
- 검증: 공식 메타 코드 확인, bounded ITEM/OBJ 조합, 기간·단위, 실제 API 응답 코드
- 재현 코드 기준: `f1f03f5`

## 결과

| BGE 후보 수 | 후보 행 | TBL recall | 기술 유효 후보 | READY | 기술 ITEM/OBJ 골드 hit |
|---:|---:|---:|---:|---:|---:|
| Top-1 | 39 | 12/24 (50.0%) | 11 | 0 | 0/20 |
| **Top-2** | 78 | **14/24 (58.3%)** | 19 | 0 | 0/20 |
| Top-3 | 117 | 14/24 (58.3%) | 19 | 0 | 0/20 |
| Top-5 | 195 | 14/24 (58.3%) | 21 | 0 | 0/20 |

Top-5 전체 상태는 `MAPPING_FAILED` 169행, `NEEDS_CONFIRMATION` 26행,
`READY` 0행이다. API는 169개 조합을 호출했고 응답 코드가 맞는 조합은 96개였다.
API 오류와 빈 응답은 모두 0건이었다.

주요 Mapping-end 사유는 다음과 같다.

| 사유 | 행 수 | 의미 |
|---|---:|---|
| `INVALID_COMBINATION` | 161 | 요청 조합 또는 응답 코드가 정확히 맞지 않음 |
| `upstream table candidate is not decisive rank-1 READY` | 8 | 표 후보 단계에서 자동 확정 조건 미충족 |
| `PERIOD_MISSING` | 8 | 필요한 기준 시점 데이터 없음 |
| `UNIT_MISMATCH` | 5 | claim과 ITEM 단위 차원 불일치 |
| `top candidates have small margin (0.0000)` | 5 | 동점 후보를 자동 확정할 수 없음 |
| `top candidates have small margin (0.0500)` | 4 | 후보 간 의미 점수 차이가 작음 |
| `DERIVATION_BASE_PERIOD_MISSING` | 4 | 증감률 계산에 필요한 비교 기준 시점 부족 |

## 해석

Top-2에서 정답 통계표 14개를 찾았고 Top-3·5에서 추가 정답표가 없었다. 따라서
**BGE 재현 경로의 최종 후보 수는 Top-2**가 가장 효율적이다.

반면 API 응답 성공은 의미상 올바른 OBJ를 보장하지 않았다. `선박`, `화장품`처럼
공식 코드명에 직접 표현되는 대상은 가까워졌지만, `반도체`, `자동차`, `바이오헬스`,
`농수산식품`처럼 산업군 표현을 세부 품목 코드 또는 여러 코드의 합으로 바꿔야 하는
대상은 자동 문자열 매칭으로 확정할 수 없었다. 기술 유효 21행이 존재해도 골드
ITEM/OBJ 동시 적중이 0/20인 이유다.

## 결정

1. 운영 기본 검색은 기존 골드 비교 결과에 따라 lexical로 유지한다.
2. BGE-M3 + reranker 경로를 재현할 때는 최종 통계표 후보를 Top-2로 제한한다.
3. Mapping-end 자동 확정은 READY 0건이므로 배포하지 않는다.
4. `NEEDS_CONFIRMATION`을 실패로 숨기지 않고 사유 코드와 함께 유지한다.
5. 다음 구현은 검색 모델 튜닝보다 코드북과 코드셋을 우선한다.

## 다음 작업

- 전체 수출은 공식 `총액/계` OBJ로 제한
- 반도체는 승인된 단일 또는 코드셋 기준 확정
- 농수산식품은 승인 범위의 다중 OBJ 합산
- LCC·대형항공사는 승인된 항공사 코드셋 합산
- 자동차·바이오헬스·석유화학·화장품의 공식 품목 범위 확정
- 증감률은 현재·비교기간 두 수준값을 확보한 경우에만 계산
- 코드북 적용 후 잠긴 골드로 ITEM/OBJ와 verdict를 다시 평가

공개 집계 데이터는 `docs/results/kosis_bge_topk_summary_20260723.csv`에 있다. 행 단위
골드, 기사 원문, API 키, 개인 경로는 이 보고서와 집계 CSV에 포함하지 않는다.
