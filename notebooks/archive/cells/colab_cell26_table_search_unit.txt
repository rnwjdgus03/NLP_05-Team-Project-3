# 26. 표 검색이 measurement 를 구분하고 있는가 (원인 두 갈래를 가른다)
#
#   (a) indicator 가 같다   → 상류 추출 문제. 한 문장의 measurement 들이 지표를 공유
#   (b) indicator 는 다른데 표가 같다 → 검색 가중치 문제. claim_text 잡음이 지표를 덮음
import pandas as pd

ready = pd.read_csv(f'{RUN}/05_hcx_measurements_kosis_ready.csv',
                    dtype=str, keep_default_na=False)
cand = pd.read_csv(f'{RUN}/05_hcx_measurements_kosis_table_candidates.csv',
                   dtype=str, keep_default_na=False)

# 문장(claim_text)당 measurement 가 2개 이상인 것만 본다
groups = ready.groupby('claim_text')
multi = {t: g for t, g in groups if len(g) >= 2}
print(f"문장 {len(groups)}개 중 measurement 2개 이상인 문장: {len(multi)}개")

top5 = (cand.sort_values('candidate_rank')
            .groupby('claim_measurement_id')['tbl_id']
            .apply(lambda s: tuple(s.head(5))))

same_ind = same_tbl = diff_ind_same_tbl = diff_ind_diff_tbl = 0
rows = []
for text, g in multi.items():
    ids = list(g['claim_measurement_id'])
    inds = {i: g.loc[g['claim_measurement_id'] == i, 'indicator'].iloc[0] for i in ids}
    items = {i: g.loc[g['claim_measurement_id'] == i, 'industry_or_item'].iloc[0] for i in ids}
    tbls = {i: top5.get(i, ()) for i in ids}

    ind_identical = len(set(inds.values())) == 1
    tbl_identical = len(set(tbls.values())) == 1
    same_ind += ind_identical
    same_tbl += tbl_identical
    if not ind_identical and tbl_identical:
        diff_ind_same_tbl += 1
    if not ind_identical and not tbl_identical:
        diff_ind_diff_tbl += 1

    rows.append({"claim_text": text[:70], "n": len(ids),
                 "indicator_identical": ind_identical,
                 "top5_identical": tbl_identical,
                 "indicators": " | ".join(sorted(set(inds.values())))[:90],
                 "items": " | ".join(sorted(set(items.values())))[:70]})

df = pd.DataFrame(rows)
n = len(df)
print(f"\n=== 같은 문장에서 나온 measurement 들 (문장 {n}개) ===")
print(f"  indicator 가 전부 같음: {same_ind} ({same_ind/max(n,1):.0%})")
print(f"  Top-5 표가 전부 같음:   {same_tbl} ({same_tbl/max(n,1):.0%})")
print(f"  indicator 다른데 표 같음: {diff_ind_same_tbl}   ← 검색 가중치 문제")
print(f"  indicator 다르고 표 다름: {diff_ind_diff_tbl}   ← 정상 동작")

print("\n=== 문제의 문장 (무역흑자 건) ===")
target = df[df['claim_text'].str.contains('무역 흑자', na=False)]
print(target.to_string(index=False) if len(target) else "  (못 찾음)")

print("\n=== indicator 는 다른데 Top-5 가 같은 사례 (검색이 구분 못 함) ===")
bad = df[(~df['indicator_identical']) & (df['top5_identical'])]
for _, r in bad.head(10).iterrows():
    print(f"\n  {r['claim_text']}")
    print(f"    지표들: {r['indicators']}")
    print(f"    품목들: {r['items']}")

print("\n=== indicator 자체가 같은 사례 (상류 추출이 구분 못 함) ===")
dup = df[df['indicator_identical']]
for _, r in dup.head(10).iterrows():
    print(f"\n  {r['claim_text']}")
    print(f"    지표(공통): {r['indicators']}")

df.to_csv(f'{OUT}/table_search_unit_diagnosis.csv', index=False, encoding='utf-8-sig')
print(f"\n저장: {OUT}/table_search_unit_diagnosis.csv")
print("\n판단:")
print("  '지표 같음' 이 많으면  → 상류 추출부터 고쳐야 한다(검색을 고쳐도 소용없다)")
print("  '지표 다른데 표 같음' 이 많으면 → claim_text 가중치를 낮추면 개선된다")
