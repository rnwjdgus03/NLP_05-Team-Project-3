# 18. 상류(추출) 품질이 검색 실패의 원인인가
#
# 지금까지 진단은 '주장 쪽은 옳다'고 가정하고 검색만 채점했다.
# 주장 텍스트가 잘렸거나, 한 문장을 measurement 여러 개로 쪼갰거나,
# KOSIS 에 없는 대상(개별 브랜드 상품가 등)이면 어떤 검색기도 성공할 수 없다.
!python diagnose_claim_quality.py \
  --measurements {RUN}/05_hcx_measurements_kosis_ready.csv \
  --retrieval {OUT}/why_chroma_missed.csv \
  --output {OUT}/claim_quality_diagnosis.csv
