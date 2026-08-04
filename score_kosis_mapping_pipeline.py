#!/usr/bin/env python3
"""Evaluate KOSIS mapping outputs against available gold columns only."""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

YES = {"Y", "YES", "TRUE", "1", "READY", "일치"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def key(row: dict[str, str]) -> str:
    return (row.get("claim_measurement_id") or row.get("claim_id") or "").strip()


def norm(v) -> str:
    return str(v or "").strip()


def yes(v) -> bool:
    return norm(v).upper() in YES


def prf(tp: int, fp: int, fn: int):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", required=True)
    ap.add_argument("--validated", required=True)
    ap.add_argument("--table-candidates", default="")
    args = ap.parse_args()
    gold = read_csv(Path(args.gold))
    val = read_csv(Path(args.validated))
    pred = {key(r): r for r in val if key(r)}
    table_rows = read_csv(Path(args.table_candidates)) if args.table_candidates else []
    tables = defaultdict(list)
    for r in table_rows:
        tables[key(r)].append(r)

    print("==== files ====")
    print("gold rows:", len(gold))
    print("validated rows:", len(val))
    print("table candidate rows:", len(table_rows))

    if any("kosis_verifiable" in r for r in gold):
        tp = fp = fn = 0
        for g in gold:
            y = yes(g.get("kosis_verifiable"))
            p = (pred.get(key(g), {}).get("final_status") == "READY" or pred.get(key(g), {}).get("kosis_verifiable_pred") == "Y")
            tp += int(y and p); fp += int((not y) and p); fn += int(y and not p)
        p, r, f = prf(tp, fp, fn)
        print("\n==== KOSIS verifiable ====")
        print(f"precision={p:.3f} recall={r:.3f} f1={f:.3f} tp={tp} fp={fp} fn={fn}")

    gold_tbl = [g for g in gold if norm(g.get("gold_tbl_id"))]
    if gold_tbl:
        print("\n==== table retrieval ====")
        for n in (1, 5, 10):
            hit = 0
            for g in gold_tbl:
                cands = tables.get(key(g), [])[:n]
                if not cands and key(g) in pred:
                    cands = [pred[key(g)]]
                hit += int(any(norm(c.get("tbl_id") or c.get("selected_tbl_id")) == norm(g.get("gold_tbl_id")) for c in cands))
            print(f"recall@{n}: {hit}/{len(gold_tbl)} = {hit/len(gold_tbl):.3f}")

    coord_gold = [g for g in gold if any(norm(g.get(c)) for c in ("gold_tbl_id", "gold_itm_id", "gold_obj_l1", "gold_obj_l2"))]
    if coord_gold:
        item_hit = obj_hit = coord_hit = ready_tp = ready_pred = ready_gold = 0
        false_ready = []
        gold_ready_review = []
        mismapped_tables = Counter()
        for g in coord_gold:
            r = pred.get(key(g), {})
            status = r.get("final_status") or r.get("mapping_status")
            pred_ready = status == "READY"
            gold_ready = yes(g.get("gold_in_ready") or g.get("kosis_verifiable") or "Y")
            ready_pred += int(pred_ready); ready_gold += int(gold_ready); ready_tp += int(pred_ready and gold_ready)
            item_ok = not norm(g.get("gold_itm_id")) or norm(r.get("selected_itm_id")) == norm(g.get("gold_itm_id"))
            obj_ok = True
            for level in range(1, 9):
                gv = norm(g.get(f"gold_obj_l{level}"))
                if gv and norm(r.get(f"selected_obj_l{level}")) != gv:
                    obj_ok = False
            tbl_ok = not norm(g.get("gold_tbl_id")) or norm(r.get("selected_tbl_id") or r.get("tbl_id")) == norm(g.get("gold_tbl_id"))
            item_hit += int(item_ok); obj_hit += int(obj_ok); coord_hit += int(item_ok and obj_ok and tbl_ok)
            if pred_ready and not gold_ready:
                false_ready.append((key(g), r.get("tbl_id") or r.get("selected_tbl_id"), r.get("mapping_reason") or r.get("review_reason")))
            if gold_ready and not pred_ready:
                gold_ready_review.append((key(g), status, r.get("review_reason") or r.get("mapping_reason")))
            if norm(g.get("gold_tbl_id")) and not tbl_ok:
                mismapped_tables[(g.get("gold_tbl_id"), r.get("tbl_id") or r.get("selected_tbl_id"))] += 1
        total = len(coord_gold)
        print("\n==== coordinate ====")
        print(f"ITEM exact: {item_hit}/{total} = {item_hit/total:.3f}")
        print(f"OBJ exact: {obj_hit}/{total} = {obj_hit/total:.3f}")
        print(f"coordinate exact: {coord_hit}/{total} = {coord_hit/total:.3f}")
        print(f"READY precision={ready_tp/ready_pred if ready_pred else 0:.3f}")
        print(f"READY recall={ready_tp/ready_gold if ready_gold else 0:.3f}")
        print(f"READY coverage={ready_pred}/{len(val)} = {ready_pred/len(val) if val else 0:.3f}")
        print("false READY:", false_ready[:30])
        print("gold READY but REVIEW/other:", gold_ready_review[:30])
        print("mismapped tbl_id top:", mismapped_tables.most_common(20))

    print("\n==== status ====")
    print("final_status:", Counter(r.get("final_status") or r.get("mapping_status") for r in val))
    review_count = sum(1 for r in val if (r.get("final_status") or r.get("mapping_status")) == "REVIEW")
    print(f"REVIEW ratio={review_count}/{len(val)} = {review_count/len(val) if val else 0:.3f}")
    print("review reasons:", Counter(r.get("review_reason") or r.get("mapping_reason") for r in val).most_common(30))


if __name__ == "__main__":
    main()
