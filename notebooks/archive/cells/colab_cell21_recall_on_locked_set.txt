# 21. 확정 집합에서 좌표 재현율 재측정 (A 의 API-valid 좌표를 정답 근사치로)
#
# 주의: 이 프록시는 'A 가 API 로 통과시킨 좌표'를 정답으로 가정한다.
#       A 도 틀릴 수 있으므로 절대값이 아니라 **A/C 상대 비교**로만 읽는다.
#       실버가 값까지 재현한 건은 별도로 표시해 신뢰 구간을 구분한다.
import pandas as pd

TRUE = {"true", "1", "y", "yes", "t"}
DEEP = 3


def load(path):
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def norm(v):
    v = str(v or "").strip()
    return "" if v.lower() in {"nan", "none"} else v


def coord_cols(df):
    itm = "selected_itm_id" if "selected_itm_id" in df.columns else "itm_id"
    objs = []
    for i in range(1, 9):
        for c in (f"selected_obj_l{i}", f"obj_l{i}"):
            if c in df.columns:
                objs.append(c)
                break
    return itm, objs


def key_of(row, itm, objs, depth):
    return (norm(row.get("tbl_id")), norm(row.get(itm))) + tuple(
        norm(row.get(c)) for c in objs[:depth])


def rank_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 999


evalset = load(f'{OUT}/evaluation_set_v2.csv')
KEYS = set(evalset["claim_measurement_id"])
A_val = load(f'{RUN}/05_hcx_measurements_kosis_validated_mappings.csv')
C_cand = load(f'{OUT}/05_hcx_measurements_kosis_chroma_candidates.csv')
silver = load(f'{OUT}/silver_coordinates.csv')
tier_of = dict(zip(silver["claim_measurement_id"], silver["tier"]))

ok = A_val["response_code_valid"].astype(str).str.strip().str.lower().isin(TRUE)
A_ok = A_val[ok & A_val["claim_measurement_id"].isin(KEYS)]
itmA, objsA = coord_cols(A_val)
itmC, objsC = coord_cols(C_cand)
C_by_m = dict(tuple(C_cand.groupby("claim_measurement_id")))

rows = []
for mid in sorted(set(A_ok["claim_measurement_id"])):
    want = {key_of(r, itmA, objsA, 1) for _, r in
            A_ok[A_ok["claim_measurement_id"] == mid].iterrows()}
    g = C_by_m.get(mid)
    hit_rank = ""
    if g is not None and not g.empty:
        got = {}
        for _, r in g.iterrows():
            got.setdefault(key_of(r, itmC, objsC, 1), rank_int(r.get("candidate_rank")))
        hits = [got[k] for k in want if k in got]
        hit_rank = min(hits) if hits else ""
    rows.append({"claim_measurement_id": mid, "found": hit_rank != "",
                 "rank": hit_rank, "tier": tier_of.get(mid, "(없음)")})

df = pd.DataFrame(rows)
print(f"확정 집합 {len(KEYS)} | A api-valid {len(df)}")
print(f"좌표 재현율 Top-10 = {df['found'].mean():.1%}   (177 집합에서는 41.0% 였다)")

print("\n실버 tier 별 재현율 (신뢰 구간 구분):")
for tier, g in df.groupby("tier"):
    print(f"  {tier:<18} {g['found'].mean():>6.1%}  (n={len(g)})")

strong = df[df["tier"] == "SILVER_UNIQUE"]
if len(strong):
    print(f"\n※ 값까지 재현된 {len(strong)}건에서의 재현율 = {strong['found'].mean():.1%}")
    print("   ← 이것만이 '정답이 확실한' 표본이다. n 이 작으므로 신뢰구간을 감안할 것.")

df.to_csv(f'{OUT}/coordinate_recall_v2.csv', index=False, encoding='utf-8-sig')
print(f"\n저장: {OUT}/coordinate_recall_v2.csv")
