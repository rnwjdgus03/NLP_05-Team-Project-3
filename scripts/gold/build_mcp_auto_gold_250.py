"""Extend mcp_auto_gold_200 to 250 rows without changing the original rows."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import build_mcp_auto_gold_200 as v200


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "data/gold/mcp_auto_gold_200.csv"
BASE_MANIFEST = ROOT / "data/gold/mcp_auto_gold_200_manifest.json"
OUTPUT = ROOT / "data/gold/mcp_auto_gold_250.csv"
MANIFEST = ROOT / "data/gold/mcp_auto_gold_250_manifest.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def select_additions(
    existing: list[dict[str, str]], codebook: list[dict[str, str]]
) -> tuple[list[dict[str, str]], dict[str, int]]:
    used = {v200.semantic_key(row) for row in existing}
    used_claim_ids = {row.get("claim_id", "") for row in existing}

    def available(row: dict[str, str]) -> bool:
        generated_claim_id = f"{row.get('article_id', '')}-{row.get('candidate_id', '')}"
        return v200.semantic_key(row) not in used and generated_claim_id not in used_claim_ids

    duplicate_positives = sorted(
        (row for row in codebook if row["gold_ready"] == "Y" and available(row)),
        key=lambda row: row["candidate_id"],
    )
    if duplicate_positives:
        raise ValueError(
            "unexpected semantically unique CODEBOOK_KOSIS candidates remain; "
            f"review selection policy: {len(duplicate_positives)}"
        )

    measurement_errors = sorted(
        (
            row for row in codebook
            if row["gold_ready"] == "N"
            and row["gold_measurement_correct"] == "N"
            and available(row)
        ),
        key=lambda row: row["candidate_id"],
    )[:25]
    for row in measurement_errors:
        used.add(v200.semantic_key(row))

    out_of_scope = sorted(
        (
            row for row in codebook
            if row["gold_ready"] == "N"
            and row["gold_measurement_correct"] == "Y"
            and row["gold_verifiable"] == "N"
            and available(row)
        ),
        key=lambda row: row["candidate_id"],
    )[:25]

    additions = measurement_errors + out_of_scope
    counts = {
        "CODEBOOK_KOSIS": 0,
        "MEASUREMENT_ERROR": len(measurement_errors),
        "MCP_NOT_VERIFIABLE": len(out_of_scope),
    }
    if len(additions) != 50 or counts != {
        "CODEBOOK_KOSIS": 0,
        "MEASUREMENT_ERROR": 25,
        "MCP_NOT_VERIFIABLE": 25,
    }:
        raise ValueError(f"unexpected extension composition: {counts}")
    return additions, counts


def main() -> None:
    fields, existing = v200.read_rows(BASE)
    _, codebook = v200.read_rows(v200.CODEBOOK)
    _, contexts = v200.read_rows(v200.NEWS_CONTEXT)
    additions, added_counts = select_additions(existing, codebook)
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    # The original raw news export is no longer shipped in this checkout; the locked
    # 200 rows and the frozen 50-article context file contain the same URL metadata.
    news_index = v200.build_news_index(existing + contexts)
    new_rows = [v200.make_row(row, fields, news_index, now) for row in additions]
    rows: list[dict[str, object]] = [dict(row) for row in existing] + new_rows

    if len(rows) != 250:
        raise ValueError(f"expected 250 rows, got {len(rows)}")
    ids = [str(row["claim_measurement_id"]) for row in rows]
    if len(set(ids)) != 250:
        raise ValueError("claim_measurement_id is not unique")
    blanks = [
        (row["claim_measurement_id"], field)
        for row in rows for field in fields
        if row.get(field, "") in ("", None)
    ]
    if blanks:
        raise ValueError(f"blank fields remain: {blanks[:20]}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    # Exact field-by-field preservation of every original row is a hard invariant.
    _, written = v200.read_rows(OUTPUT)
    if written[:200] != existing:
        raise ValueError("the original 200 rows changed")

    tiers = Counter(str(row["gold_label_tier"]) for row in rows)
    manifest = {
        "dataset": "mcp_auto_gold_250",
        "created_at": now,
        "row_count": 250,
        "unique_measurement_count": len(set(ids)),
        "original_200_preserved": True,
        "human_reviewed": False,
        "blank_field_count": 0,
        "tier_counts": dict(tiers),
        "gold_verifiable_counts": dict(Counter(str(row["gold_verifiable"]) for row in rows)),
        "added_rows": {
            "total": 50,
            **added_counts,
            "candidate_ids": [row["candidate_id"] for row in additions],
        },
        "selection_policy": [
            "no semantically unique CODEBOOK_KOSIS positives remained after the original 200",
            "25 unused measurement errors",
            "25 unused out-of-scope/not-verifiable measurements",
            "semantic duplicates with the original 200 are excluded",
        ],
        "mcp_scope": (
            "No new positive KOSIS table labels were added; all 50 extension rows are negative "
            "measurement-quality or scope labels from the locked codebook."
        ),
        "sources": {
            str(BASE.relative_to(ROOT)).replace("\\", "/"): sha256(BASE),
            str(BASE_MANIFEST.relative_to(ROOT)).replace("\\", "/"): sha256(BASE_MANIFEST),
            str(v200.CODEBOOK.relative_to(ROOT)).replace("\\", "/"): sha256(v200.CODEBOOK),
            str(v200.CODEBOOK_MANIFEST.relative_to(ROOT)).replace("\\", "/"): sha256(v200.CODEBOOK_MANIFEST),
            str(v200.NEWS_CONTEXT.relative_to(ROOT)).replace("\\", "/"): sha256(v200.NEWS_CONTEXT),
        },
        "output": str(OUTPUT.relative_to(ROOT)).replace("\\", "/"),
        "output_sha256": sha256(OUTPUT),
    }
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
