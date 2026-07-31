# 12. 인덱스 커버리지 진단 — 정답 좌표가 '애초에 인덱스에 들어갔는가'
#
# 가설: 검색이 못 찾은 게 아니라, build_coordinates 의 두 상한 때문에
#       정답 좌표가 인덱스에 존재하지도 않았다.
#         (a) --axis-value-limit 40      축당 40개 값만
#         (b) --max-coordinates-per-table 4000
#             ↑ 이 상한은 item 루프 '바깥'에서 break 하므로,
#               앞쪽 item 이 4000개를 다 써버리면 뒤쪽 itm_id 는 좌표가 0개가 된다.
#
# build_coordinates 는 결정적이라 재실행하면 인덱스와 같은 결과가 나온다(재빌드 아님, GPU 불필요).
import json
from collections import defaultdict
from math import prod

import pandas as pd

from kosis_meta_coordinates import build_coordinates, group_meta_rows, read_csv_rows

TRUE = {"true", "1", "y", "yes", "t"}


def norm(v):
    v = str(v or "").strip()
    return "" if v.lower() in {"nan", "none"} else v


# ── 실행에 쓴 상한을 manifest 에서 그대로 읽는다 ───────────────────────────
man = {}
# 이번 실행으로 갓 만든 로컬 manifest 를 먼저 본다.
# Drive 사본은 '지난 실행'의 상한값일 수 있어 뒤로 미룬다.
for path in ("data/indexes/kosis_meta_chroma/chroma_manifest.json",
             f"{OUT}/kosis_meta_chroma_index/chroma_manifest.json"):
    try:
        man = json.load(open(path, encoding="utf-8"))
        print("manifest:", path)
        break
    except (FileNotFoundError, OSError):
        continue

AXIS_LIMIT = int(man.get("axis_value_limit", 40))
TABLE_CAP = int(man.get("max_coordinates_per_table", 4000))
print(f"axis_value_limit={AXIS_LIMIT} | max_coordinates_per_table={TABLE_CAP} | "
      f"manifest document_count={man.get('document_count')}")

# ── 메타에 '존재하는' 코드 vs 인덱스에 '들어간' 좌표 ──────────────────────
meta = read_csv_rows(f"{RUN}/05_hcx_measurements_kosis_meta_index.csv")
tables = group_meta_rows(meta)
print(f"메타 행 {len(meta):,} / 표 {len(tables)}개")

meta_itm, meta_obj1, n_items, axis_sizes = (defaultdict(set), defaultdict(set), {}, {})
for (_org, tbl), tab in tables.items():
    meta_itm[tbl] |= {i["code"] for i in tab["items"]}
    n_items[tbl] = len(tab["items"])
    axis_sizes[tbl] = {o: len(a["values"]) for o, a in sorted(tab["axes"].items())}
    if 1 in tab["axes"]:
        meta_obj1[tbl] |= {v["code"] for v in tab["axes"][1]["values"]}

coords = build_coordinates(meta, axis_value_limit=AXIS_LIMIT,
                           max_coordinates_per_table=TABLE_CAP)
print(f"재현된 좌표 {len(coords):,}개 (manifest 와 같아야 정상)")

cov_itm, cov_pair, made = defaultdict(set), defaultdict(set), defaultdict(int)
for c in coords:
    tbl = c["tbl_id"]
    made[tbl] += 1
    cov_itm[tbl].add(c["itm_id"])
    cov_pair[tbl].add((c["itm_id"], norm(c["obj_codes"].get(1, ""))))

# ── A 가 API 로 확인한 좌표를 단계별로 추적 ──────────────────────────────
diag = pd.read_csv(f"{OUT}/why_chroma_missed.csv", dtype=str, keep_default_na=False)
A_val = pd.read_csv(f"{RUN}/05_hcx_measurements_kosis_validated_mappings.csv",
                    dtype=str, keep_default_na=False)
A_ok = A_val[A_val["response_code_valid"].astype(str).str.strip().str.lower().isin(TRUE)]
A_ok = A_ok[A_ok["claim_measurement_id"].isin(set(diag["claim_measurement_id"]))]


def classify(tbl, itm, obj1):
    if tbl not in meta_itm:
        return "TBL_NOT_IN_META"          # 메타 인덱스 자체에 표가 없음
    if itm and itm not in meta_itm[tbl]:
        return "ITM_NOT_IN_META"          # 메타에 그 ITEM 코드가 없음
    if obj1 and meta_obj1.get(tbl) and obj1 not in meta_obj1[tbl]:
        return "OBJ_NOT_IN_META"
    if (itm, obj1) in cov_pair.get(tbl, set()):
        return "IN_INDEX"                 # 인덱스엔 있었다 → 필터/검색 문제
    if itm in cov_itm.get(tbl, set()):
        return "OBJ_TRUNCATED"            # ITEM 은 들어갔는데 그 축 조합이 잘림 (axis limit)
    return "ITM_TRUNCATED"                # ITEM 자체가 표 상한에 먹힘 (table cap)


rows = []
for _, r in A_ok.iterrows():
    tbl, itm = norm(r.get("tbl_id")), norm(r.get("selected_itm_id"))
    obj1 = norm(r.get("selected_obj_l1"))
    rows.append({
        "claim_measurement_id": r["claim_measurement_id"],
        "tbl_id": tbl, "itm_id": itm, "obj_l1": obj1,
        "coverage": classify(tbl, itm, obj1),
        "meta_items": n_items.get(tbl, 0),
        "indexed_items": len(cov_itm.get(tbl, set())),
        "coords_made": made.get(tbl, 0),
        "hit_table_cap": made.get(tbl, 0) >= TABLE_CAP,
        "axis_sizes": str(axis_sizes.get(tbl, {})),
    })

cov = pd.DataFrame(rows).drop_duplicates(["claim_measurement_id", "tbl_id", "itm_id", "obj_l1"])
cov = cov.merge(diag[["claim_measurement_id", "failure_class"]],
                on="claim_measurement_id", how="left")
cov.to_csv(f"{OUT}/index_coverage_diagnosis.csv", index=False, encoding="utf-8-sig")

print(f"\n=== 정답 좌표 {len(cov)}개가 인덱스에 들어갔는가 ===")
print(cov["coverage"].value_counts().to_string())
print("\n=== 검색 실패 유형 × 인덱스 커버리지 ===")
print(pd.crosstab(cov["failure_class"], cov["coverage"]).to_string())

# ── 표 상한이 ITEM 을 잡아먹는지 직접 확인 ────────────────────────────────
tbl_stat = (cov[["tbl_id", "meta_items", "indexed_items", "coords_made",
                 "hit_table_cap", "axis_sizes"]]
            .drop_duplicates("tbl_id").sort_values("meta_items", ascending=False))
tbl_stat["item_coverage"] = (tbl_stat["indexed_items"] /
                             tbl_stat["meta_items"].clip(lower=1)).round(3)
print(f"\n=== 실패에 관여한 표 {len(tbl_stat)}개의 ITEM 커버리지 ===")
print(tbl_stat.head(30).to_string(index=False))

capped = tbl_stat[tbl_stat["hit_table_cap"]]
print(f"\n표 상한({TABLE_CAP}) 도달: {len(capped)}/{len(tbl_stat)}개 표")
if len(tbl_stat):
    lost = tbl_stat["meta_items"].sum() - tbl_stat["indexed_items"].sum()
    print(f"이 표들의 ITEM {tbl_stat['meta_items'].sum():,}개 중 "
          f"{tbl_stat['indexed_items'].sum():,}개만 인덱싱 → {lost:,}개 누락")

# ── 상한을 올리면 얼마나 커지는지 (실제 빌드 전 비용 추정) ────────────────
print("\n=== 상한별 좌표 수 추정 (전체 표 기준) ===")
for limit in (40, 100, 300, 1000):
    total = 0
    for (_org, tbl), tab in tables.items():
        per_item = prod(min(len(a["values"]), limit) for a in tab["axes"].values()) or 1
        total += min(len(tab["items"]) * per_item, TABLE_CAP)
    print(f"  axis_value_limit={limit:>4} (표 상한 {TABLE_CAP} 유지) → 약 {total:,} 좌표")
for cap in (4000, 20000, 100000):
    total = 0
    for (_org, tbl), tab in tables.items():
        per_item = prod(min(len(a["values"]), AXIS_LIMIT) for a in tab["axes"].values()) or 1
        total += min(len(tab["items"]) * per_item, cap)
    print(f"  max_coordinates_per_table={cap:>6} (축 상한 {AXIS_LIMIT} 유지) → 약 {total:,} 좌표")

print(f"\n저장: {OUT}/index_coverage_diagnosis.csv")
