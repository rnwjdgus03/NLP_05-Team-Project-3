# 13. 어느 hard filter 술어가 정답 좌표를 잘랐는가 (추측 금지, 직접 재현)
#
# 셀 12 결론: 정답 좌표 85%가 인덱스에 있었는데 후보로 안 나왔다.
#             → build_chroma_where / passes_hard_filter 를 그대로 재현해 범인을 특정한다.
from collections import Counter, defaultdict

import pandas as pd

from kosis_meta_coordinates import (build_coordinates, coordinate_metadata,
                                    prd_se_compatible, read_csv_rows,
                                    unit_dimension_compatible)
from kosis_chroma_hybrid_search import load_table_candidates

TRUE = {"true", "1", "y", "yes", "t"}
TOP_K_TABLES = 5          # 검색 때 쓴 값과 동일해야 한다


def norm(v):
    v = str(v or "").strip()
    return "" if v.lower() in {"nan", "none"} else v


def field(row, *names):
    for n in names:
        v = norm(row.get(n))
        if v:
            return v
    return ""


# ── 인덱스 좌표 재현 (셀 12 와 동일) ──────────────────────────────────────
meta = read_csv_rows(f"{RUN}/05_hcx_measurements_kosis_meta_index.csv")
prd_by_tbl = {}
for r in read_csv_rows(f"{RUN}/05_hcx_measurements_kosis_table_candidates.csv"):
    key = (field(r, "org_id", "ORG_ID"), field(r, "tbl_id", "TBL_ID"))
    val = field(r, "prd_se", "PRD_SE")
    if key[1] and val:
        prd_by_tbl.setdefault(key, val)

coords = build_coordinates(meta, axis_value_limit=40,
                           max_coordinates_per_table=4000,
                           prd_se_by_table=prd_by_tbl)
print(f"좌표 재현 {len(coords):,}개 | 표별 prd_se 매핑 {len(prd_by_tbl)}개")

md_by_tbl = defaultdict(list)
md_by_key = {}
for c in coords:
    md = coordinate_metadata(c)
    md_by_tbl[md["tbl_id"]].append(md)
    md_by_key.setdefault((md["tbl_id"], md["itm_id"], md["obj_l1"]), md)

# ── 주장 / 상류 표 후보 ───────────────────────────────────────────────────
ready = {r["claim_measurement_id"]: r
         for r in read_csv_rows(f"{RUN}/05_hcx_measurements_kosis_ready.csv")}
tables = load_table_candidates(f"{RUN}/05_hcx_measurements_kosis_table_candidates.csv",
                               top_k=TOP_K_TABLES)

diag = pd.read_csv(f"{OUT}/why_chroma_missed.csv", dtype=str, keep_default_na=False)
fail_ids = set(diag.loc[diag["failure_class"] != "COORD_IN_TOPK", "claim_measurement_id"])
cls_of = dict(zip(diag["claim_measurement_id"], diag["failure_class"]))

A_val = pd.read_csv(f"{RUN}/05_hcx_measurements_kosis_validated_mappings.csv",
                    dtype=str, keep_default_na=False)
A_ok = A_val[A_val["response_code_valid"].astype(str).str.strip().str.lower().isin(TRUE)]
A_ok = A_ok[A_ok["claim_measurement_id"].isin(fail_ids)]

rows = []
for _, r in A_ok.iterrows():
    mid = r["claim_measurement_id"]
    claim = ready.get(mid, {})
    tbl, itm = norm(r.get("tbl_id")), norm(r.get("selected_itm_id"))
    obj1 = norm(r.get("selected_obj_l1"))

    top5 = [norm(t.get("tbl_id")) for t in tables.get(mid, [])]
    md = md_by_key.get((tbl, itm, obj1))

    claim_prd = field(claim, "measurement_prd_se", "prd_se")
    claim_dim = field(claim, "unit_dimension")
    mapping_type = field(claim, "mapping_type")
    coord_prd = md["prd_se"] if md else ""
    coord_dim = md["unit_dimension"] if md else ""

    in_top5 = tbl in top5
    prd_ok = prd_se_compatible(claim_prd, coord_prd) if md else None
    unit_ok = unit_dimension_compatible(claim_dim, coord_dim, mapping_type) if md else None

    if md is None:
        reason = "NOT_IN_INDEX"
    elif not in_top5:
        reason = "TBL_NOT_IN_TOP5"
    elif not prd_ok:
        reason = "PRD_SE_FILTER"
    elif not unit_ok:
        reason = "UNIT_DIM_FILTER"
    else:
        reason = "PASSED_FILTER"          # 필터는 통과 → 검색/순위 문제

    # 해당 measurement 의 Top-5 표 전체에서 필터 생존 좌표 수
    survivors = 0
    for t in top5:
        for m in md_by_tbl.get(t, []):
            if (prd_se_compatible(claim_prd, m["prd_se"])
                    and unit_dimension_compatible(claim_dim, m["unit_dimension"], mapping_type)):
                survivors += 1

    rows.append({
        "claim_measurement_id": mid,
        "failure_class": cls_of.get(mid, ""),
        "reject_reason": reason,
        "tbl_id": tbl, "in_top5": in_top5,
        "claim_prd_se": claim_prd, "coord_prd_se": coord_prd, "prd_ok": prd_ok,
        "claim_unit_dim": claim_dim, "coord_unit_dim": coord_dim,
        "mapping_type": mapping_type, "unit_ok": unit_ok,
        "top5_survivors": survivors,
        "top5_tbl_ids": " ".join(top5),
    })

f = pd.DataFrame(rows).drop_duplicates(["claim_measurement_id", "tbl_id"])
f.to_csv(f"{OUT}/which_filter_rejected.csv", index=False, encoding="utf-8-sig")

print(f"\n=== 실패 좌표 {len(f)}개를 자른 술어 ===")
print(f["reject_reason"].value_counts().to_string())
print("\n=== 실패 유형 × 자른 술어 ===")
print(pd.crosstab(f["failure_class"], f["reject_reason"]).to_string())

prd = f[f["reject_reason"] == "PRD_SE_FILTER"]
if len(prd):
    print(f"\n=== prd_se 로 잘린 {len(prd)}건: 주장 주기 vs 좌표 주기 ===")
    print(Counter(zip(prd["claim_prd_se"], prd["coord_prd_se"])).most_common())

und = f[f["reject_reason"] == "UNIT_DIM_FILTER"]
if len(und):
    print(f"\n=== unit_dimension 으로 잘린 {len(und)}건 ===")
    print(Counter(zip(und["claim_unit_dim"], und["coord_unit_dim"])).most_common())

dead = f[f["top5_survivors"] == 0]
print(f"\n=== Top-5 표에서 생존 좌표가 0개인 measurement {dead['claim_measurement_id'].nunique()}건 ===")
print(dead[["claim_measurement_id", "claim_prd_se", "claim_unit_dim",
            "mapping_type", "top5_tbl_ids"]].head(20).to_string(index=False))

print("\n=== 필터를 껐다면 생존 좌표가 얼마나 늘었을까 (표본 평균) ===")
base = f["top5_survivors"].mean()
alt = []
for _, r in f.drop_duplicates("claim_measurement_id").iterrows():
    top5 = r["top5_tbl_ids"].split()
    alt.append(sum(len(md_by_tbl.get(t, [])) for t in top5))
print(f"  현재 필터 적용:  평균 {base:,.0f} 좌표")
print(f"  필터 전부 해제:  평균 {sum(alt)/max(len(alt),1):,.0f} 좌표")

print(f"\n저장: {OUT}/which_filter_rejected.csv")
