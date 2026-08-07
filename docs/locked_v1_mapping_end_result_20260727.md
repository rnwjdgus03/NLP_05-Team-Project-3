# Locked v1 lexical + Mapping-end 재평가

> 이 문서는 코드북 확장 전 기준선이다. 검색·ITEM/OBJ 코드북 적용 후 결과는
> [`locked_v1_codebook_result_20260727.md`](locked_v1_codebook_result_20260727.md)를 본다.

## 평가 기준

- 기준 코드: `Poc@6ceb3ff` 위 재현 브랜치
- 골드: `outputs/gold/gold_measurement_v1_locked.csv`
- 검색 입력: READY 39건
- 통계표 인덱스: `data/reference/kosis_table_summary.csv`, 107,138개 표
- 검색 방식: lexical
- 비교 K: 1, 2, 3, 5
- Mapping-end 조합: ITEM Top-3, OBJ Top-2, 최대 20조합
- KOSIS API 오류: 0건

## 수정 사항

기존 현행 validator는 메타 후보 단계의 `selected_itm_id`와 `selected_obj_l1`을
버리고 ITEM/OBJ를 다시 lexical로만 구성했다. 그 결과 정답 좌표가 이미 후보에
있어도 API 호출 전 `INVALID_COMBINATION`으로 탈락해 READY가 0건이었다.

이번 수정은 upstream 선택을 공식 메타 후보 안의 seed로 재사용한다. seed 코드도
공식 메타 검증을 통과해야 하므로 임의 코드를 확정하지 않는다. 또한 원문에
`전년 대비` 또는 `전년 동월 대비`가 명시된 경우에만 현재 기간에서 비교 기간을
결정적으로 추론한다.

## Top-K 결과

| K | TBL recall | 후보 | 기술 유효 | READY | READY 좌표 정답 | verdict 정답 |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 13/24 (54.2%) | 39 | 25 | 4 | 3/3 | 3/3 |
| 2 | 15/24 (62.5%) | 74 | 26 | 4 | 3/3 | 3/3 |
| 3 | 15/24 (62.5%) | 109 | 28 | 4 | 3/3 | 3/3 |
| 5 | 15/24 (62.5%) | 179 | 33 | 4 | 3/3 | 3/3 |

최고 recall을 처음 달성하는 **Top-2를 운영 기본값**으로 선택한다. Top-3과
Top-5는 정답 통계표를 추가하지 않고 후보와 검토량만 늘린다.

## 해석

- 게이트: precision 74.4%, recall 90.6%
- 검색: recall@2 62.5%
- 자동 READY: 4/39, 10.3%
- READY 중 gold table 정확도: 3/4, 75.0%
- ITEM/OBJ 골드가 모두 있는 READY 정확도: 3/3, 100%
- 골드 ITEM/OBJ 20건 중 end-to-end 도달: 3/20, 15.0%
- 도달한 gold verdict 정확도: 3/3, 100%
- 전체 gold verdict 22건 중 end-to-end 도달: 3/22, 13.6%

따라서 `verdict 100%`는 최종 단계까지 도달한 3건에 대한 조건부 정확도다.
전체 자동 검증 성능을 100%라고 표현하면 안 된다. 현재 핵심 병목은 verdict 비교가
아니라 검색 누락과 Mapping-end의 낮은 READY coverage다.

Top-2의 주요 미확정 원인은 `INVALID_COMBINATION` 39행, 통계표 rank-1 비결정
16행, 파생 비교기간 부족 6행, 기간 부족 5행, 단위 불일치 4행이다.

## 브랜치 비교

- 수정 전 현행 `Poc`: READY 0, API 오류 0
- `mapping-end@db31b61`: READY 2, validator 내부 API 오류 165회
- 선택 통합 후 현행: READY 4, API 오류 0

`mapping-end` 전체를 덮어쓰지 않고 공식 메타 seed 재사용만 현행 코드에 통합한
이유다.

## 산출물

- 공개 집계: `docs/results/locked_v1_lexical_topk_summary_20260727.csv`
- 로컬 전체 결과: `outputs/runs/locked_v1_lexical_topk_20260727/`
- Top-K 집계 SHA-256:
  `b1f7020872d55e5f4cf788d7ecc8ad1aa34033fa64f2d40271ef5e4f1c8417bd`
- Top-2 verified SHA-256:
  `38163b47909ba0bf29158db736f26dda648e40cf655f2f110366642c91fd9dff`

전체 결과 CSV는 API 응답과 원문을 포함하므로 Git에는 넣지 않고 집계만 관리한다.
