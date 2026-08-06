# KOSIS ChromaDB 구축

`kosis_table_summary.csv`의 통계표 1개를 ChromaDB 레코드 1개로 저장합니다.

- 레코드 ID: `ORG_ID::TBL_ID`
- 임베딩 문서: `TBL_NM + path_normalized`
- 메타데이터: `ORG_ID, TBL_ID, STAT_ID, TBL_NM, path_raw, path_normalized`
- 기본 임베딩 모델: `intfloat/multilingual-e5-small`
- 용도: 최종 정답 확정이 아니라 KOSIS 통계표 Top-K 후보 생성

## 1. 설치

Windows PowerShell에서 `lion` 환경을 활성화한 뒤 실행합니다.

```powershell
cd "이 폴더를 저장한 경로\kosis_chromadb"
python -m pip install -r requirements.txt
```

첫 실행에서는 임베딩 모델을 내려받기 때문에 시간이 더 걸립니다.

## 2. 정규화 결과 확인

```powershell
python build_kosis_chromadb.py preview `
  --input "kosis_table_summary.csv" `
  --rows 20 `
  --output "path_normalization_preview.csv"
```

연도만으로 이루어진 경로 단계는 제거하지만 `생산자물가조사(2020=100)`처럼
기준연도가 의미 있는 표현은 보존합니다.

## 3. 1,000행 시험 구축

```powershell
python build_kosis_chromadb.py build `
  --input "kosis_table_summary.csv" `
  --db-path "kosis_chroma_db" `
  --limit 1000
```

GPU를 사용하려면 `--device cuda`를 추가합니다. CUDA가 설정되지 않았다면
기본값 또는 `--device cpu`를 사용합니다.

## 4. 전체 107,138행 구축

시험 구축과 같은 명령에서 `--limit`만 빼면 1,000행 다음부터 이어서 처리합니다.

```powershell
python build_kosis_chromadb.py build `
  --input "kosis_table_summary.csv" `
  --db-path "kosis_chroma_db"
```

중간에 종료해도 완료된 마지막 배치 다음부터 이어받습니다. 입력 CSV나 임베딩
모델을 바꾸려면 새 `--collection` 이름을 쓰는 것을 권장합니다.

처음부터 다시 만들 때만 다음처럼 `--reset`을 사용합니다.

```powershell
python build_kosis_chromadb.py build `
  --input "kosis_table_summary.csv" `
  --db-path "kosis_chroma_db" `
  --reset
```

## 5. 통계표 후보 검색

```powershell
python build_kosis_chromadb.py query `
  --db-path "kosis_chroma_db" `
  --indicator "청년 고용률" `
  --keyword "연령별 고용률" `
  --region "전국" `
  --population "15세부터 29세 청년" `
  --query "2024년 청년 고용률은 46.1%였다." `
  --top-k 20 `
  --output "kosis_candidates.csv"
```

검색문에서는 지표·키워드·지역·모집단·기사 문장을 사용합니다. 실제 숫자, 단위,
기간은 이후 KOSIS API의 표 내부 항목과 값을 확인하는 단계에서 검증하는 편이
안전합니다.

## 결과 해석

`similarity`는 코사인 유사도이며 클수록 검색문과 가까운 통계표입니다. ChromaDB
결과 1위를 바로 정답으로 확정하지 말고, 우선 Top-10 또는 Top-30 안에 정답
`TBL_ID`가 포함되는지를 평가해야 합니다.

초기 평가 지표:

- Recall@10
- Recall@30
- MRR
- 최종 재순위화 후 Top-1 Accuracy
