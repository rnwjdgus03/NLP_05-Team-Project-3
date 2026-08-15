from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE = ROOT / "outputs" / "mcp_gold_200_v11_metadata_reranker" / "semantic_trusted_v2.csv"
DEFAULT_EVIDENCE = ROOT / "data" / "gold" / "mcp_actual_coordinate_evidence_20260813.jsonl"
DEFAULT_OUTPUT = ROOT / "data" / "gold" / "mcp_actual_verified_23.csv"
DEFAULT_MANIFEST = ROOT / "data" / "gold" / "mcp_actual_verified_23.manifest.json"


def clean(value: object) -> str:
    return str(value or "").strip()


def canonical(value: object) -> str:
    text = clean(value)
    return "N/A" if not text or text.upper() in {"NA", "N/A", "NONE", "NULL"} else text


def number_equal(left: object, right: object) -> bool:
    try:
        return Decimal(clean(left)) == Decimal(clean(right))
    except InvalidOperation:
        return clean(left) == clean(right)


def coordinate_key(row: dict[str, str], *, gold: bool) -> tuple[str, ...]:
    prefix = "gold_" if gold else ""
    return (
        canonical(row.get(f"{prefix}org_id")),
        canonical(row.get(f"{prefix}tbl_id")),
        canonical(row.get(f"{prefix}itm_id")),
        canonical(row.get(f"{prefix}obj_l1")),
        canonical(row.get(f"{prefix}obj_l2")),
        canonical(row.get(f"{prefix}prd_se")),
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_evidence(path: Path) -> dict[tuple[str, ...], dict[str, object]]:
    by_coordinate: dict[tuple[str, ...], dict[str, object]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        key = coordinate_key(row, gold=False)
        if key in by_coordinate:
            raise ValueError(f"duplicate evidence coordinate at line {line_number}: {key}")
        if row.get("search_status") not in {"FOUND_EXACT", "FOUND_BY_EXACT_TABLE_VALIDATION"}:
            raise ValueError(f"search not confirmed at line {line_number}")
        if row.get("validate_status") != "VALID_COORDINATE":
            raise ValueError(f"coordinate not validated at line {line_number}")
        if row.get("get_data_status") != "ACTUAL_VALUES_RETURNED":
            raise ValueError(f"actual values missing at line {line_number}")
        by_coordinate[key] = row
    return by_coordinate


def build(source: Path, evidence_path: Path, output: Path, manifest_path: Path) -> dict[str, object]:
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        gold_rows = list(csv.DictReader(handle))
    evidence = load_evidence(evidence_path)
    output_rows: list[dict[str, str]] = []
    errors: list[str] = []

    for gold in gold_rows:
        gold_id = clean(gold.get("gold_id"))
        key = coordinate_key(gold, gold=True)
        fact = evidence.get(key)
        if fact is None:
            errors.append(f"{gold_id}: no independent MCP coordinate evidence for {key}")
            continue
        period_values = {clean(k): clean(v) for k, v in dict(fact["period_values"]).items()}
        period = clean(gold.get("gold_period"))
        previous_period = canonical(gold.get("gold_previous_period"))
        actual = period_values.get(period)
        previous_actual = "N/A" if previous_period == "N/A" else period_values.get(previous_period)
        if actual is None:
            errors.append(f"{gold_id}: MCP actual value missing for {period}")
            continue
        if previous_period != "N/A" and previous_actual is None:
            errors.append(f"{gold_id}: MCP previous value missing for {previous_period}")
            continue
        source_value_match = number_equal(gold.get("gold_source_value"), actual)
        previous_value_match = previous_period == "N/A" or number_equal(
            gold.get("gold_previous_source_value"), previous_actual
        )
        unit_match = canonical(gold.get("gold_source_unit")) == canonical(fact.get("unit"))
        verified = source_value_match and previous_value_match and unit_match
        if not verified:
            errors.append(
                f"{gold_id}: value/unit mismatch current={source_value_match} "
                f"previous={previous_value_match} unit={unit_match}"
            )
        enriched = dict(gold)
        enriched.update(
            {
                "mcp_verification_id": clean(fact.get("verification_id")),
                "mcp_search_keyword": clean(fact.get("search_keyword")),
                "mcp_search_status": clean(fact.get("search_status")),
                "mcp_validate_status": clean(fact.get("validate_status")),
                "mcp_get_data_status": clean(fact.get("get_data_status")),
                "mcp_actual_value": actual,
                "mcp_previous_actual_value": previous_actual or "N/A",
                "mcp_actual_unit": clean(fact.get("unit")),
                "mcp_coordinate_confirmed": "Y",
                "mcp_value_confirmed": "Y" if verified else "N",
                "mcp_series_note": clean(fact.get("series_note")) or "N/A",
                "mcp_retrieved_at": clean(fact.get("retrieved_at")),
                "mcp_evidence_url": clean(fact.get("evidence_url")),
            }
        )
        output_rows.append(enriched)

    if errors:
        raise ValueError("MCP verification failed:\n- " + "\n- ".join(errors))
    if len(output_rows) != len(gold_rows):
        raise ValueError(f"row count changed: source={len(gold_rows)} output={len(output_rows)}")

    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(output_rows[0]) if output_rows else []
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS",
        "method": "KOSIS_MCP_SEARCH_VALIDATE_GET_DATA",
        "source_path": str(source.relative_to(ROOT)),
        "source_sha256": sha256(source),
        "evidence_path": str(evidence_path.relative_to(ROOT)),
        "evidence_sha256": sha256(evidence_path),
        "output_path": str(output.relative_to(ROOT)),
        "output_sha256": sha256(output),
        "gold_rows": len(gold_rows),
        "verified_rows": len(output_rows),
        "unique_verified_coordinates": len(evidence),
        "coordinate_confirmed_rows": sum(row["mcp_coordinate_confirmed"] == "Y" for row in output_rows),
        "value_confirmed_rows": sum(row["mcp_value_confirmed"] == "Y" for row in output_rows),
        "limitations": [
            "This is an independently queried subset of the existing development gold, not a disjoint article holdout.",
            "MCP responses were transcribed into the immutable evidence JSONL and then machine-checked against the gold.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build independently KOSIS-MCP-verified coordinate gold.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.evidence, args.output, args.manifest), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
