from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


SELECTED_CLAIM_IDS = (
    "A0006-SP382DCE21AF",  # annual total exports
    "A0006-SP270B11DBD0",  # monthly semiconductor exports
    "A0012-SPE7F554D64E",  # shipbuilding technical workforce
    "A0012-SP13E0E2E6EE",  # foreign technical workforce
    "A0041-SPF140502152",  # non-KOSIS consumer-price survey safety case
)
RAW_FIELDS = (
    "claim_id", "article_id", "title", "date", "url", "claim_text",
    "prev_sentence", "next_sentence", "article_context",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with args.input.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    by_id = {}
    for row in rows:
        claim_id = row.get("claim_id", "")
        if claim_id in SELECTED_CLAIM_IDS and claim_id not in by_id:
            by_id[claim_id] = {field: row.get(field, "") for field in RAW_FIELDS}
    missing = [claim_id for claim_id in SELECTED_CLAIM_IDS if claim_id not in by_id]
    if missing:
        raise SystemExit(f"selected real claims missing: {missing}")
    claims = [by_id[claim_id] for claim_id in SELECTED_CLAIM_IDS]
    if len({row["url"] for row in claims}) != 3:
        raise SystemExit("expected five claims from three real articles")
    payload = {
        "input_stage": "claims",
        "client_request_id": "real-article-e2e-smoke5-20260821",
        "claims": claims,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"claims={len(claims)} articles={len({row['article_id'] for row in claims})}")
    for row in claims:
        print(f"{row['claim_id']} | {row['title']} | {row['claim_text'][:60]}")


if __name__ == "__main__":
    main()
