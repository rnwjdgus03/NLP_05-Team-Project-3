# [32] NEAR_MISS 30건이 왜 정확히 안 맞았나 — 산술 분류 (API 0회, 즉시)
#
# NEAR_MISS 는 '값이 오차밴드까지 갔는데 정확히는 안 맞은' 건이라 좌표는 맞을 가능성이 높다.
# 실제로 산업활동동향 건은 좌표가 처음부터 맞았고 우리 부호 처리가 틀렸었다.
# 계통적 원인이 더 있으면 사람이 라벨하는 대신 버그를 고쳐서 골드를 늘릴 수 있다.
!python diagnose_near_miss.py \
  --silver {OUT}/silver_coordinates.csv \
  --review {OUT}/needs_human_review.csv \
  --output {OUT}/near_miss_diagnosis.csv

print("\n판단 기준:")
print("  SIGN/SCALE 이 있으면      → 버그 수정 → 재실행 → 골드 자동 증가")
print("  DISPLAY_ROUNDING 이 많으면 → 판정 허용오차 재검토 (기사 반올림을 불일치로 세는 중)")
print("  LARGE_GAP 만 남으면        → 좌표가 실제로 틀린 것 → 사람 라벨 필요")
