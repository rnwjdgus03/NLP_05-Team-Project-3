import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def csv_rows(name):
    with (ROOT / name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def jsonl_rows(name):
    rows = []
    with (ROOT / name).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


gold = {r["claim_measurement_id"]: r for r in csv_rows("blind_coordinate_gold30_locked.csv")}
inputs = {r["claim_measurement_id"]: r for r in csv_rows("blind_input30.csv")}
stage_a = {r["claim_measurement_id"]: r for r in csv_rows("stage_a_table_recall_details.csv")}
coords = {r["claim_measurement_id"]: r for r in csv_rows("coordinate_topk_details.csv")}
decisions = {r["claim_measurement_id"]: r for r in jsonl_rows("claim_decisions.jsonl")}
verified = defaultdict(list)
for row in jsonl_rows("verified_candidates.jsonl"):
    verified[row.get("claim_measurement_id", "")].append(row)


def passed(value, k):
    try:
        return 0 < int(float(value)) <= k
    except (TypeError, ValueError):
        return False


print("SUMMARY")
for field, k in (("table_rank", 10), ("item_rank", 5), ("coordinate_rank", 5), ("full_rank", 5)):
    print(field, sum(passed(r.get(field), k) for r in coords.values()), "/", len(gold))

print("\nPER_TABLE")
grouped = defaultdict(list)
for cid, g in gold.items():
    grouped[(g["gold_org_id"], g["gold_tbl_id"], g["gold_tbl_name"])].append(cid)
for key, ids in sorted(grouped.items()):
    table_ok = sum(passed(coords.get(cid, {}).get("table_rank"), 10) for cid in ids)
    item_ok = sum(passed(coords.get(cid, {}).get("item_rank"), 5) for cid in ids)
    coord_ok = sum(passed(coords.get(cid, {}).get("coordinate_rank"), 5) for cid in ids)
    print(f"{key[0]}/{key[1]} n={len(ids)} table10={table_ok} item5={item_ok} coord5={coord_ok} :: {key[2]}")

print("\nFAILURES")
for cid, g in gold.items():
    c = coords.get(cid, {})
    if passed(c.get("table_rank"), 10) and passed(c.get("item_rank"), 5) and passed(c.get("coordinate_rank"), 5):
        continue
    i = inputs[cid]
    a = stage_a.get(cid, {})
    print(json.dumps({
        "id": cid,
        "gold_table": f'{g["gold_org_id"]}/{g["gold_tbl_id"]}',
        "gold_table_name": g["gold_tbl_name"],
        "gold_item": g["gold_itm_name"],
        "gold_obj": [g.get(f"gold_obj_l{x}_name", "") for x in range(1, 9) if g.get(f"gold_obj_l{x}_name", "")],
        "survey": i.get("survey_name"),
        "statistics": i.get("statistics_name"),
        "indicator": i.get("indicator"),
        "target": i.get("industry_or_item"),
        "period": i.get("period"),
        "prepared": a.get("prediction_present"),
        "table_rank": c.get("table_rank"),
        "item_rank": c.get("item_rank"),
        "coordinate_rank": c.get("coordinate_rank"),
        "item_terms": a.get("item_recall_terms"),
    }, ensure_ascii=False))

print("\nUNSAFE")
for cid, d in decisions.items():
    if d.get("claim_decision") == "MISMATCH_EVIDENCE_REVIEW_REQUIRED" or d.get("verdict_code") == "VALUE_MISMATCH":
        g = gold.get(cid, {})
        i = inputs.get(cid, {})
        print("CLAIM", json.dumps({
            "id": cid,
            "decision": d.get("claim_decision"),
            "counts": d.get("candidate_verdict_counts"),
            "gold": [g.get("gold_org_id"), g.get("gold_tbl_id"), g.get("gold_itm_id"), g.get("gold_itm_name"), g.get("gold_period"), g.get("gold_actual_value")],
            "input": [i.get("indicator"), i.get("industry_or_item"), i.get("period"), i.get("value"), i.get("unit"), i.get("statistics_name")],
        }, ensure_ascii=False))
        for v in verified.get(cid, []):
            verdict = v.get("verdict_code") or v.get("verdict")
            if verdict in {"VALUE_MISMATCH", "MATCH", "LIKELY_MISMAPPING"}:
                coordinate = v.get("coordinate") or v.get("candidate") or {}
                print("CAND", json.dumps({
                    "rank": v.get("rank") or v.get("candidate_rank"),
                    "verdict": verdict,
                    "decision": v.get("decision_status"),
                    "org": coordinate.get("org_id") or v.get("org_id"),
                    "table": coordinate.get("tbl_id") or v.get("tbl_id"),
                    "item": coordinate.get("itm_id") or v.get("itm_id"),
                    "item_name": coordinate.get("itm_name") or v.get("itm_name"),
                    "actual": v.get("actual_value"),
                    "claimed": v.get("claimed_value"),
                    "preflight": v.get("postgres_preflight_status"),
                    "period_alignment": v.get("period_alignment_status"),
                    "exact_gate": v.get("mismatch_exact_gate"),
                    "scope": v.get("semantic_scope_status") or v.get("semantic_scope_state"),
                }, ensure_ascii=False))

