from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "data" / "gold" / "mcp_actual_verified_23.csv"
DEFAULT_AUDIT = ROOT / "data" / "gold" / "mcp_actual_claim_reproducibility_audit_23.csv"
DEFAULT_TRUSTED = ROOT / "data" / "gold" / "mcp_actual_semantic_verified.csv"
DEFAULT_MANIFEST = ROOT / "data" / "gold" / "mcp_actual_semantic_verified.manifest.json"
SCALE_PATTERN = re.compile(r"source unit scale\s*\(([^)]+)\)", re.IGNORECASE)


def clean(value: object) -> str:
    return str(value or "").strip()


def decimal(value: object) -> Decimal | None:
    try:
        return Decimal(clean(value))
    except (InvalidOperation, ValueError):
        return None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit_row(row: dict[str, str]) -> dict[str, str]:
    claim_type = clean(row.get("claim_type")).upper()
    claim_value = decimal(row.get("claim_value"))
    current = decimal(row.get("mcp_actual_value"))
    previous = decimal(row.get("mcp_previous_actual_value"))
    method = clean(row.get("gold_derivation_method"))
    result = dict(row)
    result.update(
        {
            "reproducibility_status": "REVIEW",
            "reproducibility_reason": "UNSUPPORTED_DERIVATION",
            "reproduced_claim_value": "",
            "reproducibility_abs_error": "",
            "reproducibility_tolerance": "",
        }
    )
    if clean(row.get("mcp_coordinate_confirmed")).upper() != "Y" or clean(
        row.get("mcp_value_confirmed")
    ).upper() != "Y":
        result["reproducibility_reason"] = "MCP_COORDINATE_OR_VALUE_UNCONFIRMED"
        return result
    if claim_value is None or current is None:
        result["reproducibility_reason"] = "NUMERIC_VALUE_MISSING"
        return result

    reproduced: Decimal | None = None
    tolerance: Decimal | None = None
    if claim_type == "LEVEL":
        scale_match = SCALE_PATTERN.search(method)
        if not scale_match:
            result["reproducibility_reason"] = "LEVEL_SCALE_MISSING"
            return result
        scale = decimal(scale_match.group(1))
        if scale is None:
            result["reproducibility_reason"] = "LEVEL_SCALE_INVALID"
            return result
        reproduced = current * scale
        if clean(row.get("mcp_actual_unit")) == "%":
            tolerance = Decimal("0.15")
        else:
            tolerance = max(Decimal("0.5"), abs(reproduced) * Decimal("0.001"))
    elif claim_type == "CHANGE_RATE" and "MCP current" in method and "MCP previous" in method:
        if previous is None or previous == 0:
            result["reproducibility_reason"] = "PREVIOUS_VALUE_MISSING_OR_ZERO"
            return result
        reproduced = (current - previous) / abs(previous) * Decimal("100")
        tolerance = Decimal("0.15")
    else:
        result["reproducibility_reason"] = "UNSUPPORTED_CLAIM_TYPE_OR_METHOD"
        return result

    error = abs(claim_value - reproduced)
    passed = error <= tolerance
    result.update(
        {
            "reproducibility_status": "PASS" if passed else "REVIEW",
            "reproducibility_reason": "CLAIM_VALUE_REPRODUCED" if passed else "CLAIM_VALUE_NOT_REPRODUCED",
            "reproduced_claim_value": format(reproduced, "f"),
            "reproducibility_abs_error": format(error, "f"),
            "reproducibility_tolerance": format(tolerance, "f"),
        }
    )
    return result


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run(input_path: Path, audit_path: Path, trusted_path: Path, manifest_path: Path) -> dict[str, object]:
    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    audited = [audit_row(row) for row in rows]
    trusted = [row for row in audited if row["reproducibility_status"] == "PASS"]
    write_csv(audit_path, audited)
    write_csv(trusted_path, trusted)
    reason_counts: dict[str, int] = {}
    for row in audited:
        reason = row["reproducibility_reason"]
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS",
        "gate": "MCP_ACTUAL_CLAIM_VALUE_REPRODUCIBILITY",
        "input_path": str(input_path.relative_to(ROOT)),
        "input_sha256": sha256(input_path),
        "audit_path": str(audit_path.relative_to(ROOT)),
        "audit_sha256": sha256(audit_path),
        "trusted_path": str(trusted_path.relative_to(ROOT)),
        "trusted_sha256": sha256(trusted_path),
        "input_rows": len(rows),
        "trusted_rows": len(trusted),
        "review_rows": len(rows) - len(trusted),
        "reason_counts": reason_counts,
        "level_tolerance": "percent: 0.15 percentage points; otherwise max(0.5 claim units, 0.1% of reproduced value)",
        "change_rate_tolerance_percentage_points": 0.15,
        "limitations": [
            "The gate checks numerical reproducibility from independently queried KOSIS values.",
            "Comparator, threshold, absolute-change, and unsupported derivations remain REVIEW instead of being guessed.",
            "This is a development subset and not a disjoint holdout.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit whether each claim value is reproducible from KOSIS MCP actual values.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--trusted", type=Path, default=DEFAULT_TRUSTED)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    print(json.dumps(run(args.input, args.audit, args.trusted, args.manifest), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
