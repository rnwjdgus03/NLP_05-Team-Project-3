# Top50 문맥 보존형 in_ready 비교 실험

## 고정 입력

- 파일: `뉴스_데이터_규칙기반정제Top50.csv`
- 행 수: 기사 50건
- SHA-256: `A8C0BF5036D2ABF3BEE8ACBD8F49DD711BED4B0FE885BEC8B800863925372A69`
- 컬럼: `기사제목`, `작성일`, `URL`, `기사 본문(정제)`, `검색 구분 레이블`

이 파일은 정제 본문의 문단 줄바꿈이 대부분 제거되어 있다. 따라서 첫 문단을
추정해서 만들지 않고 첫 3문장을 `fallback_first_sentences`로 명시해 기사 공통
문맥에 사용한다.

## 우리 팀 실행 조건

방법 ID는 `context_v2_kss_8x3`으로 고정한다.

| 설정 | 값 |
|---|---:|
| 문장 분리 | KSS |
| chunk 크기 | 8문장 |
| chunk 중첩 | 3문장 |
| 기사 공통 lead | 첫 3문장 |
| claim 주변 문맥 | 앞뒤 3문장 |
| 기사 내 관련 문장 | 최대 3문장 |
| BGE 후보 | Top-20 |
| HCX 제공 후보 | Top-5 |
| 종료 단계 | gate (`in_ready`) |

로컬 정규식 분리 미리보기에서는 50개 기사가 1,008문장, 193개 chunk로
나왔다. 같은 데이터에서 `5문장/2문장 중첩`은 320개 chunk이므로, `8/3`은
문맥을 늘리면서 span 탐지 API 호출량을 약 40% 줄인다. 최종 팀 비교 결과는
정규식 미리보기가 아니라 노트북의 KSS 결과를 사용한다.

## 문맥 구성

모든 chunk에 같은 기사 공통 문맥을 붙인다.

```text
제목
발행일(메타데이터, measurement period 기본값으로 사용 금지)
첫 3문장 fallback
주요 대상 후보
```

claim span 탐지 후에는 원문 sentence ID를 이용해 다음 문맥을 다시 만든다.

```text
기사 공통 문맥
+ claim 앞뒤 3문장
+ 같은 기사에서 기간·대상 관련도가 높은 문장 최대 3개
+ claim evidence span
```

주요 대상 후보는 제목, 첫 3문장, 기사 전체의 단어 점수로 만든 검색
힌트다. 숫자, 문장 ID, 조사, 일반 서술어를 제거하며 최종 ITEM을 확정하지
않는다.

## 실행

Colab에서
[`notebooks/contextual_top50_in_ready_colab.ipynb`](../notebooks/contextual_top50_in_ready_colab.ipynb)를
실행한다. 입력 파일은 아래 위치에 둔다.

```text
MyDrive/NLP_05-Team-Project-3/inputs/뉴스_데이터_규칙기반정제Top50.csv
```

`CLOVA_API_KEY`만 Colab 보안 비밀에 등록한다. KOSIS 실제값 검증 전 단계에서
중단하므로 `KOSIS_API_KEY`는 필요하지 않다. BGE-M3 인덱스는 아래 경로를
사용한다.

```text
MyDrive/NLP_05-Team-Project-3/indexes/kosis_bge_m3
```

## 비교 파일

팀에 전달할 기본 파일은 다음 하나다.

```text
runs/contextual_top50_context_v2_8x3/06_in_ready_all.csv
```

모든 measurement가 들어 있으며 `in_ready=Y/N`, `mapping_gate`,
`mapping_exclusion_code`를 함께 확인할 수 있다.

보조 파일은 다음과 같다.

- `06_mapping_ready.csv`: `in_ready=Y`
- `06_mapping_enrich.csv`: 기간·scope·binding 보강 대상
- `06_mapping_reject.csv`: 명확한 범위 밖
- `03_claim_contexts.csv`: 각 claim에 사용된 문맥과 sentence ID 감사

## 방법 선택 기준

`in_ready=Y` 개수만 가장 많은 방법을 고르지 않는다. 같은 50개 기사에서
아래 지표를 함께 비교한다.

1. 사람이 확인한 수치 claim span 회수율
2. measurement 값·단위·기간·대상 정확도
3. `in_ready=Y` 중 실제 매핑 가능한 비율
4. `PERIOD_MISSING`, `BINDING_NOT_CONFIRMED` 감소량
5. 잘못 READY로 통과한 false positive 수

최종 방법은 READY 양과 정확도의 균형으로 정한다.
