# 17. KOSIS 에러코드 분포 (분기 전략을 짜기 전에 '실제로 뭐가 나오는지' 먼저 센다)
#
# 현재 코드는 err:30 만 빈응답으로 처리하고 나머지는 전부 조합을 포기한다.
#   err:20 세부항목 누락  → objL 차원을 단계적으로 열면 회수 가능
#   err:31 응답 too large → 요청을 좁혀야 함
# 이 둘이 실제로 얼마나 나오는지 확인하고 나서 구현한다.
import re
from collections import Counter

import pandas as pd

frames = {
    "A_baseline": f"{RUN}/05_hcx_measurements_kosis_validated_mappings.csv",
    "C_chroma": f"{OUT}/05_hcx_measurements_kosis_chroma_validated.csv",
}

for label, path in frames.items():
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    except FileNotFoundError:
        print(f"[{label}] 파일 없음: {path}")
        continue

    col = "api_error" if "api_error" in df.columns else None
    print(f"\n=== {label} | 행 {len(df):,} ===")
    if col is None:
        print("  api_error 컬럼 없음 → 컬럼:", ", ".join(list(df.columns)[:25]))
        continue

    errors = df[df[col].str.strip() != ""][col]
    print(f"  KOSIS 에러가 기록된 행: {len(errors):,} ({len(errors)/max(len(df),1):.1%})")

    codes = Counter()
    for value in errors:
        found = re.search(r"KOSIS_ERROR\[([^\]]*)\]", value)
        if found:
            for code in found.group(1).split(","):
                codes[code.strip()] += 1
        else:
            codes["(형식 불명)"] += 1
    if codes:
        print("  에러코드별:")
        for code, n in codes.most_common():
            print(f"    err:{code} → {n:,}")

    # 메시지 표본 (코드별 1건씩)
    seen = set()
    for value in errors:
        found = re.search(r"KOSIS_ERROR\[([^\]]*)\]", value)
        key = found.group(1) if found else "?"
        if key not in seen:
            seen.add(key)
            print(f"    예시[{key}]: {value[:160]}")

    # 에러 말고 '빈 응답'은 몇 건인가 (분기 대상 규모 비교용)
    if "validation_reason" in df.columns:
        reasons = df["validation_reason"].str.strip()
        print("  validation_reason 상위:")
        for reason, n in Counter(r for r in reasons if r).most_common(8):
            print(f"    {reason}: {n:,}")

print("\n판단 기준:")
print("  err:20 이 유의미하게 나오면 → objL 단계적 확장 구현 (ITEM_OBJ_FIXABLE 회수 기대)")
print("  err:20/31 이 거의 없으면   → 분기 전략은 우리 데이터에선 효과 없음. 구현하지 말 것")
