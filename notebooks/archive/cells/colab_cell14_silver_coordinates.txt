# 14. 실버 좌표 라벨 만들기 (골드 아님 — 검색 비교 전용)
#
# A/C 양쪽 후보 좌표를 KOSIS 실제값으로 대조해 '기사 숫자를 재현하는 좌표'를 찾는다.
# 좌표는 고정한 채(use_pinned_item) 조회하므로 A 후보 vs C 후보 비교가 성립한다.
#
# 한계(반드시 함께 읽을 것):
#   기사 숫자가 틀린 주장에서는 어떤 좌표도 재현하지 못해 라벨이 안 생긴다.
#   → 실버는 '참인 주장' 쪽으로 편향된다. 검색 비교에만 쓰고 판정 정확도엔 쓰지 말 것.
!python build_silver_coordinates.py \
  --measurements {RUN}/05_hcx_measurements_kosis_ready.csv \
  --candidates-a {RUN}/05_hcx_measurements_kosis_validated_mappings.csv \
  --candidates-c {OUT}/05_hcx_measurements_kosis_chroma_validated.csv \
  --output {OUT}/silver_coordinates.csv \
  --review-output {OUT}/needs_human_review.csv \
  --max-coordinates-per-measurement 12 \
  --delay 0.12
