#!/usr/bin/env python3
"""Score the current KOSIS mapping pipeline against a merged gold CSV.

The gold set is intentionally partial: all 109 rows can score gate/extraction,
while table/item/obj/verdict scores only use rows with the relevant gold fields.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def measurement_id(row: Mapping[str, Any]) -> str:
    return str(row.get("claim_measurement_id") or row.get("claim_id") or "").strip()


def norm(value: Any) -> str:
    return str(value or "").strip()


def candidate_rank(row: Mapping[str, Any]) -> int:
    try:
        return int(float(norm(row.get("candidate_rank")) or "999"))
    except ValueError:
        return 999


def print_counter(title: str, values: list[str], limit: int = 20) -> None:
    print(f"\n{title}")
    for value, count in Counter(values).most_common(limit):
        print(f"  {value or '(blank)'}: {count}")


def ratio(hit: int, total: int) -> str:
    return f"{hit}/{total} = {hit / total:.3f}" if total else "n/a"


def score_table_retrieval(gold: list[dict[str, str]], table_candidates: list[dict[str, str]]) -> None:
    gold_tbl = {
        measurement_id(row): norm(row.get("gold_tbl_id"))
        for row in gold
        if measurement_id(row) and norm(row.get("gold_tbl_id"))
    }

    candidates_by_id: dict[str, list[dict[str, str]]] = {}
    for row in table_candidates:
        key = measurement_id(row)
        if not key:
            continue
        candidates_by_id.setdefault(key, []).append(row)
    for rows in candidates_by_id.values():
        rows.sort(key=candidate_rank)

    top1 = top3 = top5 = 0
    missing_candidate = []
    misses = []
    for key, expected_tbl in gold_tbl.items():
        rows = candidates_by_id.get(key, [])
        predicted = [norm(row.get("tbl_id")) for row in rows]
        if not rows:
            missing_candidate.append(key)
        if expected_tbl in predicted[:1]:
            top1 += 1
        if expected_tbl in predicted[:3]:
            top3 += 1
        if expected_tbl in predicted[:5]:
            top5 += 1
        if expected_tbl not in predicted[:5]:
            misses.append((key, expected_tbl, predicted[:5]))

    total = len(gold_tbl)
    print("\n==== 3. table retrieval recall ====")
    print("gold_tbl_id rows:", total)
    print("recall@1:", ratio(top1, total))
    print("recall@3:", ratio(top3, total))
    print("recall@5:", ratio(top5, total))
    print("missing table candidates:", len(missing_candidate), missing_candidate[:10])
    print("top5 miss samples:")
    for item in misses[:10]:
        print(" ", item)


def score_item_obj(gold: list[dict[str, str]], validated: list[dict[str, str]]) -> None:
    gold_item_obj = {
        measurement_id(row): row
        for row in gold
        if measurement_id(row) and norm(row.get("gold_itm_id")) and norm(row.get("gold_obj_l1"))
    }

    ready_by_id = {
        measurement_id(row): row
        for row in validated
        if norm(row.get("mapping_status")) == "READY" and measurement_id(row)
    }

    item_hit = obj_hit = both_hit = 0
    ready_count = 0
    not_ready = []
    mismatch_samples = []
    for key, expected in gold_item_obj.items():
        predicted = ready_by_id.get(key)
        if not predicted:
            not_ready.append(key)
            continue
        ready_count += 1
        expected_itm = norm(expected.get("gold_itm_id"))
        expected_obj = norm(expected.get("gold_obj_l1"))
        predicted_itm = norm(predicted.get("selected_itm_id"))
        predicted_obj = norm(predicted.get("selected_obj_l1"))

        item_ok = expected_itm == predicted_itm
        obj_ok = expected_obj == predicted_obj
        item_hit += int(item_ok)
        obj_hit += int(obj_ok)
        both_hit += int(item_ok and obj_ok)
        if not (item_ok and obj_ok):
            mismatch_samples.append((key, expected_itm, predicted_itm, expected_obj, predicted_obj))

    total = len(gold_item_obj)
    print("\n==== 5. item / obj accuracy ====")
    print("gold item+obj rows:", total)
    print("READY coverage:", ratio(ready_count, total))
    print("READY item accuracy:", ratio(item_hit, ready_count))
    print("READY obj accuracy:", ratio(obj_hit, ready_count))
    print("READY item+obj accuracy:", ratio(both_hit, ready_count))
    print("end-to-end item+obj success:", ratio(both_hit, total))
    print("gold item/obj rows not READY:", len(not_ready), not_ready[:10])
    print("mismatch samples:")
    for item in mismatch_samples[:10]:
        print(" ", item)


def score_verdict(gold: list[dict[str, str]], verified: list[dict[str, str]]) -> None:
    gold_verdict = {
        measurement_id(row): norm(row.get("gold_verdict"))
        for row in gold
        if measurement_id(row) and norm(row.get("gold_verdict"))
    }
    verified_by_id = {
        measurement_id(row): row
        for row in verified
        if measurement_id(row)
    }

    predicted_count = hit = 0
    missing = []
    mismatches = []
    for key, expected in gold_verdict.items():
        predicted = verified_by_id.get(key)
        if not predicted:
            missing.append(key)
            continue
        verdict = norm(predicted.get("verdict"))
        predicted_count += int(bool(verdict))
        if verdict == expected:
            hit += 1
        else:
            mismatches.append((key, expected, verdict, norm(predicted.get("verdict_code"))))

    total = len(gold_verdict)
    print("\n==== 6. verdict accuracy ====")
    print("gold verdict rows:", total)
    print("predicted verdict rows:", predicted_count)
    print("verdict accuracy:", ratio(hit, total))
    print("missing verified:", len(missing), missing[:10])
    print("verdict mismatch samples:")
    for item in mismatches[:10]:
        print(" ", item)


def main() -> None:
    parser = argparse.ArgumentParser(description="Score KOSIS mapping outputs against merged gold")
    parser.add_argument("--gold", default="data/gold/gold_measurement_merged.csv")
    parser.add_argument("--table-candidates", required=True)
    parser.add_argument("--validated", required=True)
    parser.add_argument("--verified", required=True)
    args = parser.parse_args()

    gold = read_csv(Path(args.gold))
    table_candidates = read_csv(Path(args.table_candidates))
    validated = read_csv(Path(args.validated))
    verified = read_csv(Path(args.verified))

    print("==== files ====")
    print("gold rows:", len(gold))
    print("table candidate rows:", len(table_candidates))
    print("validated rows:", len(validated))
    print("verified rows:", len(verified))

    print("\n==== 1. gold coverage ====")
    for column in [
        "gold_verifiable",
        "gold_measurement_correct",
        "gold_tbl_id",
        "gold_itm_id",
        "gold_obj_l1",
        "gold_verdict",
        "gold_actual_value",
    ]:
        values = [norm(row.get(column)) for row in gold]
        print(
            column,
            "filled:",
            sum(bool(value) for value in values),
            "/",
            len(values),
            Counter(values).most_common(10),
        )

    print_counter("==== 2. gate / extraction gold summary: gold_verifiable ====",
                  [norm(row.get("gold_verifiable")) for row in gold])
    print_counter("==== 2. gate / extraction gold summary: gold_measurement_correct ====",
                  [norm(row.get("gold_measurement_correct")) for row in gold])

    score_table_retrieval(gold, table_candidates)

    print("\n==== 4. validated mapping status ====")
    print("mapping_status:", Counter(norm(row.get("mapping_status")) for row in validated))
    print("mapping_reason:", Counter(norm(row.get("mapping_reason")) for row in validated).most_common(20))

    score_item_obj(gold, validated)
    score_verdict(gold, verified)

    print("\n==== 7. quick conclusion hints ====")
    print("- table recall@5가 높고 READY가 낮으면 ITEM/OBJ/API 검증 병목")
    print("- table recall@5가 낮으면 후보 검색 자체가 병목")
    print("- item/obj not READY가 많으면 HITL 또는 rank/metadata 후보 확장 필요")
    print("- verdict 표본은 아직 작으니 참고용")


if __name__ == "__main__":
    main()
