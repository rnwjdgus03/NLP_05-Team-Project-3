from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BASE = ROOT / "data/gold/ready52_actual_coordinate_gold_v20.csv"
LOCKED = ROOT / "data/gold/mcp_auto_gold_250.csv"
OUTPUT = ROOT / "data/gold/stratified_actual_coordinate_gold_v21.csv"
MANIFEST = ROOT / "data/gold/stratified_actual_coordinate_gold_v21_manifest.json"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def clean(value: object) -> str:
    return str(value or "").strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def table_key(row: dict[str, str]) -> str:
    return f"{clean(row.get('gold_org_id'))}/{clean(row.get('gold_tbl_id'))}"


def full_coordinate(row: dict[str, str]) -> bool:
    return all(
        clean(row.get(field)).lower() not in {"", "n/a", "none", "nan"}
        for field in (
            "claim_measurement_id", "gold_org_id", "gold_tbl_id", "gold_itm_id",
            "gold_obj_l1", "gold_prd_se", "gold_period",
        )
    )


def main() -> None:
    base = read_csv(BASE)
    locked = read_csv(LOCKED)
    base_tables = {table_key(row) for row in base}
    seen_ids = {clean(row.get("claim_measurement_id")) for row in base}
    additions: list[dict[str, str]] = []

    # Only the old rows whose actual ITEM/OBJ/period coordinates were locked.
    # CODEBOOK_KOSIS and TABLE_ONLY rows are deliberately excluded.
    for source in locked:
        claim_id = clean(source.get("claim_measurement_id"))
        if source.get("gold_label_tier") != "FULL_KOSIS":
            continue
        if source.get("gold_ready") != "Y" or not full_coordinate(source):
            continue
        if table_key(source) in base_tables or claim_id in seen_ids:
            continue
        row = dict(source)
        row["coordinate_gold_source_group"] = "LOCKED_FULL_KOSIS_DIVERSITY"
        row["gold_label_source"] = (
            clean(row.get("gold_label_source")) + "|STRATIFIED_RELOCK_V21"
        ).strip("|")
        additions.append(row)
        seen_ids.add(claim_id)

    output = []
    for source in base:
        row = dict(source)
        row["coordinate_gold_source_group"] = "READY52_ACTUAL_V20"
        output.append(row)
    output.extend(additions)
    output.sort(key=lambda row: clean(row.get("claim_measurement_id")))

    if len({clean(row.get("claim_measurement_id")) for row in output}) != len(output):
        raise RuntimeError("duplicate claim_measurement_id")
    if any(not full_coordinate(row) for row in output):
        raise RuntimeError("gold contains an incomplete coordinate")
    if any(row.get("gold_label_tier") == "CODEBOOK_KOSIS" for row in output):
        raise RuntimeError("CODEBOOK_KOSIS must not enter actual coordinate gold")

    fields: list[str] = []
    for row in output:
        for key in row:
            if key not in fields:
                fields.append(key)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(output)

    table_counts = Counter(table_key(row) for row in output)
    organization_counts = Counter(clean(row.get("gold_org_id")) for row in output)
    manifest = {
        "schema_version": "stratified-actual-coordinate-gold-v21",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_source": str(BASE),
        "base_source_sha256": sha256(BASE),
        "locked_source": str(LOCKED),
        "locked_source_sha256": sha256(LOCKED),
        "rows": len(output),
        "base_rows": len(base),
        "diversity_additions": len(additions),
        "distinct_tables": len(table_counts),
        "distinct_organizations": len(organization_counts),
        "largest_table_share": max(table_counts.values()) / len(output),
        "table_counts": dict(sorted(table_counts.items())),
        "organization_counts": dict(sorted(organization_counts.items())),
        "admission_policy": (
            "READY52 actual-coordinate v20 plus unseen-table FULL_KOSIS rows only; "
            "CODEBOOK_KOSIS/TABLE_ONLY/not-verifiable rows excluded"
        ),
        "evaluation_note": (
            "30 READY52 rows retain same-set regression comparability; 10 external locked "
            "rows form a cross-survey expansion and require their matching claim input."
        ),
        "output_sha256": sha256(OUTPUT),
    }
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
