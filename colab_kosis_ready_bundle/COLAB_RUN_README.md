# KOSIS 2차 매핑/검증 Colab 실행 안내

이 폴더는 `/Users/gu/Downloads/kosis_mapping_ready_500_real.csv`를 기준으로 만든 Colab 실행 묶음입니다.

## 핵심 기준

- 입력 CSV는 이미 1차 `verification_input_ready`가 끝난 파일로 봅니다.
- 표 검색은 운영 기준인 `hybrid`를 사용합니다.
- `mapping_status=READY`는 KOSIS API 응답의 `ITM_ID`, `C1~C8`, 기간, 단위가 맞을 때만 부여합니다.
- READY가 아닌 후보는 최종 일치/불일치 검증에 넣지 않는 것이 안전합니다.

## Colab 실행 순서

### 1. 파일 업로드

이 폴더 전체를 Colab `/content` 아래에 업로드하거나, GitHub/Drive에서 복사합니다.

작업 폴더 예시:

```bash
cd /content/colab_kosis_ready_bundle
```

### 2. 의존성 설치

```bash
pip install -r requirements-ml.txt
```

### 3. KOSIS API 키 설정

Colab에서 직접 입력합니다. 키를 코드/깃허브에 저장하지 마세요.

```python
import os
os.environ["KOSIS_API_KEY"] = "여기에_본인_API_KEY"
```

### 4. 표 임베딩 인덱스 생성

```bash
python kosis_build_embedding_index.py \
  --table-index kosis_table_summary.csv \
  --out-dir data/indexes/kosis_bge_m3 \
  --embedding-model BAAI/bge-m3
```

### 5. 메타 후보 생성

```bash
python run_kosis_measurement_pipeline.py \
  --input kosis_mapping_ready_500_real.csv \
  --table-index kosis_table_summary.csv \
  --out-dir outputs/colab_kosis_ready_500 \
  --retrieval-mode hybrid \
  --top-tables 20 \
  --top-rank-for-meta 5 \
  --delay 0.12
```

### 6. Chroma coordinate index 생성

```bash
python kosis_build_chroma_coordinate_index.py \
  --meta-index outputs/colab_kosis_ready_500/kosis_mapping_ready_500_real_kosis_meta_index.csv \
  --persist-dir data/indexes/kosis_chroma_coordinates \
  --batch-size 64 \
  --force
```

### 7. 2차 READY 검증

```bash
python kosis_validate_mapping_candidates.py \
  --input outputs/colab_kosis_ready_500/kosis_mapping_ready_500_real_kosis_candidates_with_meta.csv \
  --meta-index outputs/colab_kosis_ready_500/kosis_mapping_ready_500_real_kosis_meta_index.csv \
  --output outputs/colab_kosis_ready_500/kosis_mapping_ready_500_real_kosis_validated_mappings.csv \
  --item-top-k 3 \
  --obj-top-k 2 \
  --api-candidate-top-k 5 \
  --chroma-coordinate-index data/indexes/kosis_chroma_coordinates \
  --chroma-validation-top-k 20 \
  --delay 0.12
```

### 8. READY만 실제값 검증

```bash
python kosis_verify_claim_values.py \
  --input outputs/colab_kosis_ready_500/kosis_mapping_ready_500_real_kosis_validated_mappings.csv \
  --output outputs/colab_kosis_ready_500/kosis_mapping_ready_500_real_kosis_verified.csv \
  --delay 0.12
```

### 9. 결과 카운트 확인

```python
import csv
from collections import Counter

validated = "outputs/colab_kosis_ready_500/kosis_mapping_ready_500_real_kosis_validated_mappings.csv"
verified = "outputs/colab_kosis_ready_500/kosis_mapping_ready_500_real_kosis_verified.csv"

with open(validated, encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))
print("mapping_status:", Counter(r.get("mapping_status", "") for r in rows))

with open(verified, encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))
print("verdict:", Counter(r.get("verdict", "") for r in rows))
print("verdict_code:", Counter(r.get("verdict_code", "") for r in rows))
```

## 로컬 사전 진단 결과

API 호출 전 기준:

- 입력 135건
- 1차 `verification_input_ready` 134건
- API 전 표 후보 OK 117건
- 이슈 17건

이슈 유형:

- `NO_DIRECT_KOSIS_SALES_TABLE`: 완성차/전기차 판매량 직접표 불명확
- `NO_DIRECT_KOSIS_TABLE_OR_EXTERNAL_SOURCE`: 환율은 KOSIS보다 외부/한국은행 계열 권장
- `FORMULA_REQUIRED_TRADE_BALANCE`: 흑자/무역수지는 수출액-수입액 계산식 필요
- `COMPARISON_PERIOD_MISSING`: 전월/전년 비교기간 구조화 필요
