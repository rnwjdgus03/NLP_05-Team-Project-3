#!/usr/bin/env python3
"""Report the raw PostgreSQL ITEM-recall rank of each coordinate-gold table."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from kosis_postgres_store import PostgresKosisMetadataStore
from run_kosis_coordinate_stage_a import item_table_recall_terms


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--retrieval", required=True, type=Path)
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--dsn", default="postgresql:///kosis_project")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--ids", default="")
    args = parser.parse_args()
    packets = {row["claim_measurement_id"]: row for row in read_jsonl(args.retrieval)}
    with args.gold.open(encoding="utf-8-sig", newline="") as handle:
        gold = list(csv.DictReader(handle))
    selected_ids = {value.strip() for value in args.ids.split(",") if value.strip()}
    with PostgresKosisMetadataStore(args.dsn) as store:
        with store.metadata_read_guard():
            for row in gold:
                claim_id = str(row.get("claim_measurement_id") or "").strip()
                if selected_ids and claim_id not in selected_ids:
                    continue
                packet = packets.get(claim_id)
                if packet is None:
                    continue
                terms = item_table_recall_terms(packet.get("claim") or {})
                hits = store.item_table_recall(
                    terms, limit=args.limit,
                    prd_se=(packet.get("claim") or {}).get("prd_se", ""),
                )
                gold_key = (
                    str(row.get("gold_org_id") or "").strip(),
                    str(row.get("gold_tbl_id") or "").strip(),
                )
                rank = next((
                    hit["rank"] for hit in hits
                    if (hit["org_id"], hit["tbl_id"]) == gold_key
                ), None)
                print(json.dumps({
                    "claim_measurement_id": claim_id,
                    "gold_key": gold_key,
                    "raw_item_rank": rank,
                    "returned_hits": len(hits),
                    "terms": terms,
                }, ensure_ascii=False))


if __name__ == "__main__":
    main()
