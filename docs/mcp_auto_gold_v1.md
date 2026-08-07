# KOSIS MCP 자동 골드셋

## 최신 산출물

- `data/gold/mcp_auto_gold_200.csv`: 200개 확장 골드셋 CSV
- `data/gold/mcp_auto_gold_200_manifest.json`: 확장 행 선정 내역과 입력·출력 해시
- `outputs/gold/mcp_auto_gold_200.xlsx`: 요약·필터가 포함된 검토용 Excel
- `data/gold/mcp_auto_gold_v3.csv`: 파이프라인용 원본 CSV
- `data/gold/mcp_auto_gold_v3_manifest.json`: 건수, 입력·출력 해시, 라벨 정의
- `outputs/gold/mcp_auto_gold_v3.xlsx`: 검토와 필터링을 위한 Excel 사본
- `scripts/gold/build_mcp_auto_gold_v3.py`: 재현 가능한 생성기

## v3 구성

v3는 총 112개 측정값을 포함하며 모든 `gold_*` 필드가 비어 있지 않다.

| 라벨 | 건수 | 의미 |
|---|---:|---|
| `FULL_KOSIS` | 21 | KOSIS 표·좌표·기간·원자료·실제값을 확정한 자동 골드 |
| `MCP_NOT_VERIFIABLE` | 70 | KOSIS 직접 좌표를 확정할 수 없어 `N/A`와 사유를 기록 |
| `MEASUREMENT_ERROR` | 21 | 정의 문구·문맥상 횟수 등을 측정값으로 잘못 추출 |

`gold_verifiable=Y`는 21건이고 `gold_verifiable=N`은 91건이며, 사람 검수는 수행하지 않아 모든 행의 `human_reviewed` 값은 `N`이다.

## v2 대비 변경

v2에서는 12개 행만 실제 KOSIS 좌표와 값이 채워져 있었고 43개 `AUTO_POSITIVE` 행은 좌표가 미확정이었다.

v3에서는 소매판매, 대중 수출, 양곡 소비, 혼인, 합계출산율, 취업자, 농가 고령인구 비중 등 9개 측정값을 추가로 직접 검증해 `FULL_KOSIS`를 21건으로 늘렸다.

나머지 행도 빈칸으로 두지 않고 좌표·원자료·오차 필드에는 `N/A`, 판정 필드에는 `판단불가`, 사유 필드에는 제외 근거를 기록했다.

## 재생성

```powershell
python scripts/gold/build_mcp_auto_gold_v3.py
```

생성기는 112개 고유 측정값, `AUTO_POSITIVE` 후보 전체 처리, 모든 `gold_*` 필드의 무빈칸 조건을 검사한 뒤 CSV와 매니페스트를 기록한다.

## 사용상 주의

이 데이터는 사람 확인 없이 KOSIS MCP 검색·메타데이터 검증·값 조회 결과와 자동 제외 규칙으로 만든 자동 골드다.

모델 개발과 회귀 테스트에는 사용할 수 있지만, 최종 연구 성능 보고 전에는 `FULL_KOSIS`와 `MCP_NOT_VERIFIABLE` 경계 표본을 별도로 표본 검수하는 것이 바람직하다.

## 200개 확장판

200개 확장판은 v3의 112개를 유지하고 잠긴 `context_top50_common_gold_v1`에서 기존 측정과 겹치지 않는 88개를 추가했다.

| 라벨 | 건수 | 의미 |
|---|---:|---|
| `FULL_KOSIS` | 21 | KOSIS 세부 좌표와 실제값까지 확정 |
| `CODEBOOK_KOSIS` | 82 | 측정·검증 가능 판정과 KOSIS 통계표를 확인했으나 세부 항목·분류·실제값은 대기 |
| `MCP_NOT_VERIFIABLE` | 73 | KOSIS 직접 검증 범위 밖 |
| `MEASUREMENT_ERROR` | 24 | 기사 문맥에서 측정값 추출이 잘못됨 |

전체 200행은 `article_id`, `title`, `date`, `url` 및 모든 `gold_*` 필드를 포함하며 빈 필드는 없다.
