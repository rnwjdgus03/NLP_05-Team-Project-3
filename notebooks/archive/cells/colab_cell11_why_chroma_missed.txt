# 11. 원인 분리 — A는 API-valid 인데 C 가 놓친 measurement (골드 없이 검색 품질 측정)
#
# 아이디어: A 가 KOSIS API 로 코드 일치까지 확인한 좌표는 '사실상 정답에 가까운 좌표'다.
#          그 좌표가 C 의 Top-10 후보 안에 들어 있었는지 보면, 실패가
#          '검색이 못 찾은 것'인지 '순위에서 밀린 것'인지 '표부터 틀린 것'인지 갈린다.
import pandas as pd

TRUE = {"true", "1", "y", "yes", "t"}
DEEP = 3          # 엄격 비교 깊이 (obj_l1~l3)


def load(path):
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def norm(v):
    v = str(v or "").strip()
    return "" if v.lower() in {"nan", "none"} else v


def api_ok(df, keys):
    if "response_code_valid" not in df.columns:
        raise KeyError("response_code_valid 없음 → 컬럼: " + ", ".join(list(df.columns)[:25]))
    flag = df["response_code_valid"].astype(str).str.strip().str.lower().isin(TRUE)
    return df[flag & df["claim_measurement_id"].isin(keys)]


def coord_cols(df):
    itm = "selected_itm_id" if "selected_itm_id" in df.columns else "itm_id"
    objs = []
    for i in range(1, 9):
        for col in (f"selected_obj_l{i}", f"obj_l{i}"):
            if col in df.columns:
                objs.append(col)
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


A_val = load(f"{RUN}/05_hcx_measurements_kosis_validated_mappings.csv")
C_val = load(f"{OUT}/05_hcx_measurements_kosis_chroma_validated.csv")
C_cand = load(f"{OUT}/05_hcx_measurements_kosis_chroma_candidates.csv")
ready = load(f"{RUN}/05_hcx_measurements_kosis_ready.csv")
try:
    stats = load(f"{OUT}/chroma_search_stats.csv").drop_duplicates(
        "claim_measurement_id").set_index("claim_measurement_id")
except Exception as exc:
    print("stats 로드 실패:", exc)
    stats = None

KEYS = set(ready["claim_measurement_id"])
text_of = dict(zip(ready["claim_measurement_id"],
                   ready["claim_text"] if "claim_text" in ready.columns else [""] * len(ready)))

A_ok, C_ok = api_ok(A_val, KEYS), api_ok(C_val, KEYS)
A_set, C_set = set(A_ok["claim_measurement_id"]), set(C_ok["claim_measurement_id"])

print(f"평가 대상 {len(KEYS)} | A api-valid {len(A_set)} | C api-valid {len(C_set)}")
print(f"둘 다 {len(A_set & C_set)} | A만 {len(A_set - C_set)} | "
      f"C만 {len(C_set - A_set)} | 둘 다 실패 {len(KEYS - A_set - C_set)}")

itmA, objsA = coord_cols(A_val)
itmC, objsC = coord_cols(C_cand)
print("좌표 컬럼  A:", itmA, objsA[:DEEP], "| C:", itmC, objsC[:DEEP])

C_by_m = dict(tuple(C_cand.groupby("claim_measurement_id")))

rows = []
for mid in sorted(A_set):
    a = A_ok[A_ok["claim_measurement_id"] == mid]
    want_loose = {key_of(r, itmA, objsA, 1) for _, r in a.iterrows()}
    want_deep = {key_of(r, itmA, objsA, DEEP) for _, r in a.iterrows()}
    want_tbl = {k[0] for k in want_loose}
    g = C_by_m.get(mid)

    if g is None or g.empty:
        cls, hit_rank, deep_hit = "NO_CANDIDATE", "", False
    else:
        got_loose, got_deep, got_tbl = {}, set(), set()
        for _, r in g.iterrows():
            got_loose.setdefault(key_of(r, itmC, objsC, 1), rank_int(r.get("candidate_rank")))
            got_deep.add(key_of(r, itmC, objsC, DEEP))
            got_tbl.add(norm(r.get("tbl_id")))
        hits = [got_loose[k] for k in want_loose if k in got_loose]
        deep_hit = bool(want_deep & got_deep)
        if hits:
            cls, hit_rank = "COORD_IN_TOPK", min(hits)
        elif want_tbl & got_tbl:
            cls, hit_rank = "TABLE_OK_COORD_MISS", ""
        else:
            cls, hit_rank = "TABLE_MISS", ""

    st = stats.loc[mid].to_dict() if stats is not None and mid in stats.index else {}
    rows.append({
        "claim_measurement_id": mid,
        "c_api_valid": mid in C_set,
        "failure_class": cls,
        "coord_hit_rank": hit_rank,
        "deep_match": deep_hit,
        "a_tbl_id": " | ".join(sorted(want_tbl)),
        "a_coordinate": " | ".join(sorted("/".join(k[1:]) for k in want_deep))[:200],
        "c_candidate_rows": 0 if g is None else len(g),
        "dense_count": st.get("dense_count", ""),
        "lexical_count": st.get("lexical_count", ""),
        "claim_text": str(text_of.get(mid, ""))[:120],
    })

diag = pd.DataFrame(rows)
diag.to_csv(f"{OUT}/why_chroma_missed.csv", index=False, encoding="utf-8-sig")

print(f"\n=== A 의 API-valid 좌표가 C Top-10 안에 있었나 (분모 {len(diag)}) ===")
print(diag["failure_class"].value_counts().to_string())
loose = (diag["failure_class"] == "COORD_IN_TOPK").mean()
deep = diag["deep_match"].mean()
print(f"\n좌표 재현율 Top-10  느슨(tbl+itm+obj_l1) = {loose:.1%} | 엄격(obj_l3까지) = {deep:.1%}")
print("  ↑ 골드 없이 측정 가능한 검색 품질. 낮으면 '검색이 못 찾은 것'.")

top = diag[diag["failure_class"] == "COORD_IN_TOPK"]["coord_hit_rank"]
if len(top):
    print("\n맞춘 좌표의 rank 분포:")
    print(top.value_counts().sort_index().to_string())

miss = diag[~diag["c_api_valid"]]
print(f"\n=== A만 성공하고 C가 놓친 {len(miss)}건의 실패 유형 ===")
print(miss["failure_class"].value_counts().to_string())
print()
print(miss[["claim_measurement_id", "failure_class", "coord_hit_rank",
            "a_tbl_id", "claim_text"]].head(25).to_string(index=False))

no_cand = KEYS - set(C_cand["claim_measurement_id"])
print(f"\n=== C 가 후보를 아예 못 만든 measurement {len(no_cand)}건 ===")
for mid in sorted(no_cand):
    print(" ", mid, "|", str(text_of.get(mid, ""))[:90])
if no_cand and stats is not None:
    have = [m for m in sorted(no_cand) if m in stats.index]
    if have:
        print("\n해당 건 검색 통계 (필터가 후보를 다 걷어냈는지 확인):")
        print(stats.loc[have].to_string())

print(f"\n저장: {OUT}/why_chroma_missed.csv")
