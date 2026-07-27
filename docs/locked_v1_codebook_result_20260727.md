# Locked v1 코드북·키워드 확장 결과

## 목적

기존 locked v1 평가에서 lexical Top-2가 정답 통계표 24건 중 15건만
찾았고, 자동 READY는 39건 중 4건이었다. 검색에서 놓친 9건과 정답표를
찾고도 확정하지 못한 ITEM/OBJ를 감사 가능한 규칙으로 보완했다.

## 구현

- `data/claims/kosis_table_search_overrides_v1.csv`
  - 조건이 모두 맞을 때만 특정 통계표를 후보에 추가하고 점수를 높인다.
  - 에너지 수입, 연·월간 반도체 수출, 바이오헬스 수출, 항공 정비사 규칙 5개다.
- `data/claims/kosis_mapping_overrides_v1.csv`
  - 공식 메타에 코드가 실제로 존재할 때만 ITEM과 OBJ 축을 seed로 사용한다.
  - 최대 `objL8`까지 실제 축 순서를 보존한다.
- `백만US$` 등 달러 단위와 `2023년말` 같은 기간 표현을 표준화했다.
- 과학 표기 수치 `1.42E+11`을 전체 숫자로 읽도록 verifier를 수정했다.
- KOSIS `err=30`은 `EMPTY_RESPONSE`, 그 밖의 오류는 `API_ERROR`로 구분한다.
- OBJ 문맥에서 `수출액`을 보존해 측정 종류가 OBJ 축인 표도 검색한다.

모든 override는 claim 조건, 기관, 통계표, ITEM, OBJ, 주기와 근거를 CSV에
남긴다. 공식 메타 검증을 통과하지 못한 코드는 API로 보내지 않는다.

## 검색 결과

| K | 수정 전 recall | 수정 후 recall | 후보 row |
|---:|---:|---:|---:|
| 1 | 13/24 (54.2%) | 21/24 (87.5%) | 39 |
| 2 | 15/24 (62.5%) | 23/24 (95.8%) | 76 |
| 3 | 15/24 (62.5%) | 23/24 (95.8%) | 111 |
| 5 | 15/24 (62.5%) | 23/24 (95.8%) | 181 |

누락 9건 중 의미상 유효한 8건을 후보에 복구했다. 남은
`A0006-C007-m1`은 국가 전체 무역수지 claim에 ICT 산업 무역수지 표가
gold로 연결되어 있어 코드북으로 강제하지 않고 `GOLD_SCOPE_REVIEW`로 남겼다.

최고 recall을 처음 달성하는 운영 기본값은 계속 **Top-2**다.

## Mapping-end 결과

| K | 기술 유효 | READY | verified | locked-gold verdict 일치 |
|---:|---:|---:|---:|---:|
| 1 | 24 | 5 | 5 | 3/5 |
| 2 | 34 | 5 | 5 | 3/5 |
| 3 | 42 | 5 | 5 | 3/5 |
| 5 | 57 | 5 | 5 | 3/5 |

READY는 4건에서 5건으로 늘었다. 기존에 잘못 READY였던
`A0006-C006-m1`의 일반 수입표를 제거하고, 공식 연간·월간 반도체 표의
현재값 2건을 새로 READY로 만들었다.

READY 5건의 API 판정은 모두 `MATCH`다. locked gold와 2건이 다른 이유는
다음과 같아 곧바로 모델 오류로 확정할 수 없다.

- `A0006-C001-m1`: claim 6.84e11달러, API 6.83609488e11달러로 차이 0.057%다.
- `A0006-C009-m2`: claim 1.42e11달러, API 1.42086e11달러로 차이 0.061%다.

현행 허용오차에서는 둘 다 MATCH지만 locked gold는 불일치다. 엄격 일치
정책과 반올림 허용 기준을 확정한 뒤 gold verdict를 재검토해야 한다.

ITEM/OBJ 단순 정확도도 gold 표기 문제의 영향을 받는다. 연간 반도체 gold
ITEM은 현재 공식 메타의 `T001`이 아닌 다른 표의 예전 코드이고, 월간 반도체
gold OBJ는 `축 ID + 코드`를 한 셀에 저장하지만 예측은 코드만 저장한다.
locked gold는 수정하지 않고 검토 대상으로 남겼다.

## 남은 판단불가

- 반도체 증감률 2건: 원문에 비교 기준이 명시되지 않아
  `DERIVATION_BASE_PERIOD_MISSING`.
- 에너지 수입표: API 최신 자료가 2021년까지라 2024 값을 조회할 수 없어
  `EMPTY_RESPONSE`.
- 바이오헬스 표: 공식 ITEM/OBJ 메타는 존재하지만 Param API가 값을 제공하지
  않아 `EMPTY_RESPONSE`. 달러 claim과 원화 원자료의 직접 비교도 불가하다.
- 항공 정비사 표: 공식 좌표 조합에서 2023 데이터가 없어 `EMPTY_RESPONSE`.

이 행들은 READY 수를 높이기 위해 강제 확정하지 않는다.

## 재현과 검증

- 골드: `outputs/gold/gold_measurement_v1_locked.csv` 109행
- 검색 입력: READY 39행
- 통계표 인덱스: 107,138개
- Top-K 집계:
  `outputs/runs/locked_v1_codebook_mapping_topk_20260727/topk_summary.csv`
- 공개 집계:
  `docs/results/locked_v1_codebook_topk_summary_20260727.csv`
- 테스트: `126 passed`
- Top-K 집계 SHA-256:
  `21707c4404384a4288d88f4a367d0e9eff5ff3abe9bf4589471dfab626124d5b`
- Top-2 verified SHA-256:
  `99c5e98c5ad20dc987f2d2d4717b9c6e7535cb2a6fa4302abd35f2d7e5553258`

전체 실행 CSV는 원문과 API 응답을 포함하므로 Git에는 넣지 않고 공개 집계만
관리한다.
