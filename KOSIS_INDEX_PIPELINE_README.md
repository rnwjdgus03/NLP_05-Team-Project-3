# KOSIS 인덱스 기반 자동매핑 파이프라인

## 왜 만들었나

예전 하드코딩 verifier/codebook 방식은 삭제했고, 현재는 KOSIS API 기반 동적 후보 매핑을 사용한다.
그래서 실제 구조는 "전체 KOSIS 자동매핑"이 아니라 "하드코딩 기반 부분 검증기"에 가까웠다.

이번 보완은 그림에서 말한 KOSIS 파이프라인의 빠진 부분을 채우기 위한 것이다.

```text
claim 입력
→ claim 도메인/indicator 기반 KOSIS statisticsList API 동적 조회
→ 이번 claim용 통계표 인덱스 생성
→ 후보 표 메타 API 조회
→ obj/itm 후보까지 붙인 검토 CSV
```

## 추가된 스크립트

### 1. `kosis_build_table_index.py`

KOSIS statisticsList API를 재귀 호출해서 통계표 목록 인덱스를 만든다.

출력 예:

```text
data/claims/kosis_table_index.csv
```

프로젝트에는 기존에 큰 테이블 인덱스가 있다.

```text
`--table-source cache --table-index <직접 지정한 CSV>`
```

현재 확인 기준 약 107,138행이다.
다만 이 파일은 전체/최신/무누락을 보장하지 않으므로 기본값으로 쓰지 않는다.
새 파이프라인은 API 동적 조회를 기본으로 한다. 캐시는 별도 파일을 직접 지정할 때만 쓴다.

### 2. `kosis_build_meta_index.py`

후보 `tbl_id`에 대해 KOSIS getMeta API를 호출해서 분류축/항목/단위 코드를 long format으로 저장한다.

출력 예:

```text
data/claims/kosis_meta_index.csv
```

### 3. `kosis_match_claims_to_index.py`

claim CSV와 KOSIS table/meta index를 비교해서 후보를 만든다.

결과에는 다음이 포함된다.

```text
claim_id
indicator
candidate_rank
candidate_score
org_id
tbl_id
tbl_name
category_path
meta_candidates
claim_text
```

### 4. `run_kosis_index_pipeline.py`

위 단계를 한 번에 실행하는 러너다.

```text
claim CSV
→ table 후보 생성
→ 상위 후보 tbl_id 추출
→ 해당 tbl_id의 메타 API 조회
→ meta 후보 포함 최종 후보 CSV 생성
```

## 실행 예시

```bash
cd /Users/gu/myproject/NLP_05-Team-Project-3

./venv/bin/python run_kosis_index_pipeline.py \
  --claims /Users/gu/Downloads/hcx005_extracted_del.csv \
  --out-dir /Users/gu/Downloads \
  --table-source api \
  --top-tables 5 \
  --top-rank-for-meta 2 \
  --min-score 10
```

특정 카테고리만 명시해서 조회할 수도 있다.

```bash
./venv/bin/python run_kosis_index_pipeline.py \
  --claims /Users/gu/Downloads/hcx005_extracted_del.csv \
  --out-dir /Users/gu/Downloads \
  --table-source api \
  --api-start-parent S2 \
  --api-start-parent P2
```

기존 로컬 캐시를 빠른 실험용으로 쓰고 싶을 때만:

```bash
./venv/bin/python run_kosis_index_pipeline.py \
  --claims /Users/gu/Downloads/hcx005_extracted_del.csv \
  --out-dir /Users/gu/Downloads \
  --table-source cache \
  --table-index `--table-source cache --table-index <직접 지정한 CSV>`
```

## 이번 hcx005 실행 산출물

```text
/Users/gu/Downloads/hcx005_extracted_del_kosis_index_candidates.csv
/Users/gu/Downloads/hcx005_extracted_del_top_candidate_tables.csv
/Users/gu/Downloads/hcx005_extracted_del_kosis_meta_index.csv
/Users/gu/Downloads/hcx005_extracted_del_kosis_index_candidates_with_meta.csv
```

API 모드에서는 추가로 이번 claim에 맞춰 동적으로 만든 table index도 남는다.

```text
/Users/gu/Downloads/hcx005_extracted_del_kosis_table_index_api.csv
```

## 현재 한계

이 단계는 최종 일치/불일치 판정기가 아니다.

역할은 claim별 KOSIS tbl_id/메타 후보를 만드는 것이다.

```text
KOSIS API 기반 후보 생성
→ 사람이 확인
→ 확정 코드북 승격
→ verify 스크립트에서 실제 API 값 검증
```

## 다음 작업

1. `hcx005_extracted_del_kosis_index_candidates_with_meta.csv`에서 후보 검토
2. rank1 후보를 사람이 검토해 확정 매핑으로 저장
3. 확정 매핑을 바탕으로 실제값 API 조회/판정 단계를 새 파이프라인에 추가
4. 무역수지처럼 계산식이 필요한 지표는 `mapping_type=formula`로 별도 처리
5. 반도체/석유화학/바이오헬스/농수산식품처럼 합산이 필요한 지표는 코드셋으로 관리
