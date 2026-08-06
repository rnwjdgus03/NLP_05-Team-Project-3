# KOSIS NumPy 정확 검색

Windows에서 ChromaDB/HNSW 인덱스가 재실행 후 열리지 않는 문제를 피하기 위해
KOSIS 통계표 임베딩을 NumPy `.npy` 파일에 저장하고 코사인 유사도로 Top-K를
정확 검색합니다.

- 입력 컬럼: `ORG_ID, TBL_ID, TBL_NM, STAT_ID, path`
- 레코드 ID: `ORG_ID::TBL_ID`
- 임베딩 문서: `TBL_NM + path_normalized`
- 기본 모델: `intfloat/multilingual-e5-small`
- 저장 파일: `embeddings.npy`, `metadata.csv`, `state.json`
- 검색 방식: 청크 단위 NumPy exact cosine

## 1. 파일 배치와 설치

이 폴더에 `kosis_table_summary.csv`를 넣습니다.

```text
db/
├─ build_kosis_numpy.py
├─ requirements.txt
├─ README.md
└─ kosis_table_summary.csv
```

VS Code PowerShell 터미널에서 `lion` 환경을 활성화하고 실행합니다.

```powershell
cd "위 파일들이 있는 db 폴더"
python -m pip install -r requirements.txt
```

## 2. 정규화 미리보기

한 줄 명령이 가장 안전합니다.

```powershell
python build_kosis_numpy.py preview --input "kosis_table_summary.csv" --rows 20 --output "path_normalization_preview.csv"
```

## 3. CPU로 1,000행 시험 구축

```powershell
python build_kosis_numpy.py build --input "kosis_table_summary.csv" --db-path "kosis_numpy_db" --device cpu --limit 1000
```

`--db-path`는 코드 파일을 넣어둔 `db` 폴더가 아니라, 그 안에 새로 생성할
NumPy 인덱스 전용 폴더입니다.

완료 후 다음 세 파일이 생깁니다.

```text
kosis_numpy_db/
├─ embeddings.npy
├─ metadata.csv
└─ state.json
```

## 4. 터미널을 닫았다 다시 열고 검색 시험

```powershell
python build_kosis_numpy.py query --db-path "kosis_numpy_db" --device cpu --indicator "청년 고용률" --keyword "연령별 고용률" --region "전국" --population "15세부터 29세 청년" --query "2024년 청년 고용률은 46.1%였다." --top-k 20 --output "kosis_candidates_test.csv"
```

1,000행은 원본의 앞부분만 검색하므로 의미상 좋은 결과가 안 나와도 정상입니다.
이 단계에서는 오류 없이 CSV가 생성되는지만 확인합니다.

## 5. 전체 107,138행 이어받기

시험 때 사용한 것과 **같은 `--db-path`**를 사용하고 `--limit`만 제거합니다.

```powershell
python build_kosis_numpy.py build --input "kosis_table_summary.csv" --db-path "kosis_numpy_db" --device cpu
```

중간에 종료되어도 마지막으로 저장된 배치 다음부터 이어받습니다. 진행 상태는
다음 명령으로 확인할 수 있습니다.

```powershell
python build_kosis_numpy.py info --db-path "kosis_numpy_db"
```

## 6. 전체 구축 후 검색

```powershell
python build_kosis_numpy.py query --db-path "kosis_numpy_db" --device cpu --indicator "청년 고용률" --keyword "연령별 고용률" --region "전국" --population "15세부터 29세 청년" --query "2024년 청년 고용률은 46.1%였다." --top-k 30 --output "kosis_candidates.csv"
```

결과 CSV 컬럼은 다음과 같습니다.

```text
rank, similarity, record_id, ORG_ID, TBL_ID, STAT_ID,
TBL_NM, path, path_normalized
```

`similarity`는 코사인 유사도이며 클수록 검색문과 가깝습니다. 이 단계의 목표는
1위를 바로 정답으로 확정하는 것이 아니라 정답 `TBL_ID`가 Top-10 또는
Top-30 후보 안에 포함되도록 하는 것입니다.

## GPU를 나중에 사용할 경우

PyTorch에서 CUDA가 인식되면 구축 명령의 `--device cpu`를 `--device cuda`로
바꿀 수 있습니다. CPU로 일부 만든 인덱스도 같은 모델이라면 GPU로 이어받을 수
있습니다. GPU 메모리 부족 시 `--encode-batch-size 64`를 32 또는 16으로
낮춥니다.

검색은 107,138개 × 384차원 규모에서 CPU로 충분하며, GPU를 써도 체감 차이가
크지 않습니다.

## 처음부터 다시 만들 때

`--reset`은 지정한 인덱스 폴더 안의 `state.json`, `embeddings.npy`,
`metadata.csv`만 삭제하고 다시 만듭니다.

```powershell
python build_kosis_numpy.py build --input "kosis_table_summary.csv" --db-path "kosis_numpy_db" --device cpu --reset --limit 1000
```

입력 CSV나 임베딩 모델을 바꿀 때는 새 `--db-path`를 쓰는 것이 가장 안전합니다.
