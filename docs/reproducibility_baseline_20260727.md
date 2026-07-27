# 재현 기준선 v1

2026-07-27부터 아래 버전을 실전2 결과의 재현 기준으로 사용한다.

## 고정 버전

| 구분 | 브랜치 | 커밋 | 역할 |
|---|---|---|---|
| 공식 기준선 | `Poc` | `6ceb3ff8f71946267c8105bcce8dbf61bb26f47a` | 최신 전처리, 구조화, 게이트, 검색 실험, locked gold |
| 좌표 검증 확장 | `mapping-end` | `db31b61423930f4b7b07f1b387bc5e8f21cec25a` | 사람이 확정한 ITEM/OBJ 좌표의 KOSIS API 검증 |

`mapping-end` 전체를 `Poc`에 덮어쓰지 않는다. 해당 브랜치는 최신 `Poc`의 코드북,
Top-K 실험, locked gold 파일을 포함하지 않으므로 독립적인
`verify_gold_coordinates.py`와 좌표 표본만 가져온다.

기계 판독용 전체 기준은 `repro/baseline_v1.json`에 있다.

## 골드셋 기준

- 입력: `outputs/gold/gold_measurement_scopefix.csv`
- 게이트 통과 입력: `outputs/gold/gold_measurement_scopefix_kosis_ready.csv`
- 정답 기준: `outputs/gold/gold_measurement_v1_locked.csv`
- 라벨 버전: `v1`
- 게이트 버전: `trade_scope_v1`
- 총 109 measurement, `gold_verifiable=Y` 32건, READY 39건
- 게이트 precision 74.4%, recall 90.6%, READY 추출 정확도 84.6%

과거 발표 자료의 게이트 recall 59.5% 또는 69.0%는 기준 정렬 전 수치다.
현재 비교에는 locked v1의 90.6%를 사용한다.

## 재현 방법

Python 3.12 기준이다.

```powershell
pip install -r requirements-dev.txt
.\scripts\reproduce_baseline.ps1
```

위 명령은 전체 단위 테스트, 골드 동결 재생성, 추적 중인 locked gold와의 SHA-256
비교를 수행한다. KOSIS API 키가 설정돼 있으면 좌표 검증까지 실행할 수 있다.

```powershell
$env:KOSIS_API_KEY = "발급받은 키"
.\scripts\reproduce_baseline.ps1 -IncludeApi
```

산출물은 `outputs/runs/repro_baseline_v1/`에 생성되며 Git에는 포함하지 않는다.

## 확인 결과

- `Poc@6ceb3ff`: 117 tests passed
- `mapping-end@db31b61`: 125 tests passed
- locked CSV, 라벨 audit CSV, metrics JSON: 기존 파일과 SHA-256 동일
- 보고서 Markdown: 텍스트 동일, Windows 줄바꿈만 다름
- 골드 좌표 API 재검증: 12건 중 일치 8, 불일치 3, 판정보류 1

이 결과는 자동 매핑 전체 정확도를 뜻하지 않는다. 마지막 항목은 사람이 확정한
12개 좌표가 현재 KOSIS API에서도 같은 값을 반환하는지 확인한 회귀 표본이다.

## 다음 통합 기준

1. 모든 평가는 `gold_measurement_v1_locked.csv`의 `claim_measurement_id`를 키로 한다.
2. 검색 후보는 lexical 운영 기준과 BGE 재현 기준을 분리해 보고한다.
3. 사람이 확정한 좌표와 자동 추천 좌표를 섞지 않는다.
4. `MATCH`, `MISMATCH`는 API 응답과 단위·기간·ITEM·OBJ가 모두 확정된 행만 부여한다.
5. 코드셋 합산이나 계산식이 필요한 행은 규칙 버전을 기록하고 별도 회귀 테스트를 둔다.
