# KOSIS lexical vs BGE-M3 동일 조건 비교

## 목적

READY 39 measurement와 잠긴 골드셋을 고정하고, lexical과 BGE-M3 hybrid를
Top-1·2·3·5 및 동일한 Mapping-end 조건으로 비교했다. 기존 BGE 결과는 재사용하고
lexical 경로만 추가 실행했다.

## 결과

| 검색 방식 | K | TBL recall | 기술 유효 후보 | READY | ITEM/OBJ 골드 hit |
|---|---:|---:|---:|---:|---:|
| lexical | 1 | 13/24 (54.2%) | 18 | 0 | 0/20 |
| **lexical** | **2** | **15/24 (62.5%)** | 18 | 0 | 0/20 |
| lexical | 3 | 15/24 (62.5%) | 18 | 0 | 0/20 |
| lexical | 5 | 15/24 (62.5%) | 21 | 0 | 0/20 |
| BGE-M3 hybrid | 1 | 12/24 (50.0%) | 11 | 0 | 0/20 |
| BGE-M3 hybrid | 2 | 14/24 (58.3%) | 19 | 0 | 0/20 |
| BGE-M3 hybrid | 3 | 14/24 (58.3%) | 19 | 0 | 0/20 |
| BGE-M3 hybrid | 5 | 14/24 (58.3%) | 21 | 0 | 0/20 |

## 해석

1. lexical과 BGE 모두 Top-2 이후 정답 통계표가 추가되지 않았다.
2. lexical Top-2가 15/24로 BGE Top-2의 14/24보다 한 건 높다.
3. lexical은 임베딩 인덱스, GPU, 리랭커 의존성이 없으므로 같은 성능이면 운영비용도 낮다.
4. 두 방식 모두 READY가 0건이어서 ITEM/OBJ 및 verdict 정확도는 비교할 수 없다.
5. 따라서 검색 방식은 lexical Top-2로 확정하지만 Mapping-end 자동 배포는 보류한다.

lexical Top-2의 주요 보류 사유는 `INVALID_COMBINATION`, 1위 표 후보 비결정,
ITEM/OBJ 후보 점수 동률, 파생값 비교 기준기간 누락이다. 이는 검색 엔진보다
ITEM/OBJ 의미 선택, 코드셋, 비교기간 및 계산식 규칙에서 해결해야 한다.

## 결정

- 운영 통계표 검색: **lexical Top-2**
- BGE-M3와 reranker: 재현·재검토용으로 보존
- Mapping-end: READY 0건이므로 자동 확정 보류
- 다음 작업: 코드북 override, 다중 OBJ 코드셋 합산, 비교기간·파생 계산 규칙 보강

재현 노트북은 `notebooks/kosis_lexical_vs_bge_colab.ipynb`다. 행 단위 골드와 기사
데이터는 공개 집계에 포함하지 않았다.
