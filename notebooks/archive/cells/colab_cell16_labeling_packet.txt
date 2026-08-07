# 16. 라벨링 근거 시트 뽑기 (실버가 자동 확정 못 한 measurement)
#
# 라벨러가 prior 가 아니라 '증거'를 보고 고르게 한다:
#   후보 좌표 + KOSIS 메타 이름/단위 + 실제 조회값 + 판정
# 후보는 파이프라인 순위가 아니라 코드 사전순으로 섞어 낸다(앵커링 방지).
!python export_labeling_packet.py \
  --silver {OUT}/silver_coordinates.csv \
  --review {OUT}/needs_human_review.csv \
  --measurements {RUN}/05_hcx_measurements_kosis_ready.csv \
  --output {OUT}/labeling_packet.csv \
  --markdown {OUT}/labeling_packet.md

# 채팅에 붙여넣을 배치 (한 번에 30건씩)
import pandas as pd
pk = pd.read_csv(f'{OUT}/labeling_packet.csv', dtype=str, keep_default_na=False)
print(f"\n라벨 필요 {len(pk)}건 → 30건씩 {-(-len(pk)//30)}배치")
print(pk['tier'].value_counts().to_string())
print("\n--- 배치 1 미리보기 ---")
md = open(f'{OUT}/labeling_packet.md', encoding='utf-8').read()
print(md[:1500])
