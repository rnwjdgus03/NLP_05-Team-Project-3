# HCX 자동매핑 실행 가이드

## 기준 파일

- 입력: `data/claims/hcx_extracted.csv`
- 코드북: `data/claims/kosis_indicator_codebook.csv`
- 실행 코드: `verify_claim_schema_v3_pilot.py`
- 결과: `outputs/bteam_review/hcx_extracted_verified.csv`
- 요약: `outputs/bteam_review/hcx_extracted_summary.csv`

## 실행 명령

```bash
cd /Users/gu/myproject/NLP_05-Team-Project-3

source venv/bin/activate

pip install -r requirements.txt

python verify_claim_schema_v3_pilot.py \
  --input data/claims/hcx_extracted.csv \
  --output outputs/bteam_review/hcx_extracted_verified.csv \
  --summary outputs/bteam_review/hcx_extracted_summary.csv
```

## 현재 자동매핑 방식

기존 `claim_text` 키워드 검색 방식이 아니라, schema v3 구조화 컬럼을 사용한다.

사용 컬럼:

- `indicator`
- `value`
- `unit`
- `value_type`
- `direction`
- `change_base`
- `period`
- `prd_se`
- `region`
- `age_group`
- `industry_or_item`
- `verifiable_kosis`

## 현재 결과

`hcx_extracted.csv` 기준:

- 전체: 122건
- 일치: 12건
- 불일치: 4건
- 판단불가: 106건

`tbl_id`가 붙은 주요 표:

- `DT_1DA7001S`: 경제활동인구 총괄
- `DT_1DA7002S`: 연령별 경제활동인구
- `DT_1J22042`: 월별 소비자물가 등락률
- `DT_1J22003`: 소비자물가지수
- `DT_404Y014`: 생산자물가지수
- `DT_1B8000G`: 월/분기/연간 인구동향
- `DT_1B8000F`: 인구동태건수 및 동태율 추이

## 주의

- `obj_l1=0`은 오류가 아니다. KOSIS 메타에서 `0`이 `계`, `총지수`, `전체`를 의미하는 정상 코드인 경우가 있다.
- `tbl_id`, `obj_l1`, `itm_id`가 비어 있는 행은 아직 코드북이 없어서 자동 확정하지 않은 행이다.
- 산업별 취업자, 품목별 물가, 지역별 고용률, 생활물가-소비자물가 차이 등은 세부 코드북 확장이 필요하다.
