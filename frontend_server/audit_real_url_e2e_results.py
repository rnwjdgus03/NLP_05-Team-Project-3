#!/usr/bin/env python3
"""Audit URL E2E outcomes without changing the locked QA set or engine."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def rows_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def rows_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--details", type=Path, required=True)
    args = parser.parse_args()
    state = json.loads(args.state.read_text(encoding="utf-8"))
    records = list(state["records"].values())
    audit = Counter(); verdict_codes = Counter(); gates = Counter(); source_gate_outcomes = Counter()
    detail_rows = []
    for record in records:
        source_gate = str(record.get("source_article_gate") or "")
        if record.get("article_fetch_status") != "SUCCEEDED":
            source_gate_outcomes[f"{source_gate}:FETCH_FAILED"] += 1
            continue
        job_id = record["job_id"]
        run = args.runs_dir / job_id
        result_path = Path(record.get("result_path") or "")
        result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else {}
        ready = rows_csv(run / "service_prepared_ready.csv")
        enrich = rows_csv(run / "service_prepared_enrich.csv")
        rejected = rows_csv(run / "service_prepared_rejected.csv")
        verified = rows_jsonl(run / "verified_candidates.jsonl")
        pipeline = (run / "engine" / "fallback_manifest.json").exists()
        audit["fetch_succeeded_articles"] += 1
        audit["pipeline_articles" if pipeline else "gate_only_articles"] += 1
        audit["ready_measurements"] += len(ready)
        audit["enrich_measurements"] += len(enrich)
        audit["rejected_measurements"] += len(rejected)
        audit["verified_candidate_rows"] += len(verified)
        verdict_codes.update(str(row.get("verdict_code") or "") for row in verified)
        gates.update(str(row.get("mapping_exclusion_code") or row.get("mapping_gate_reason") or "") for row in enrich + rejected)
        claims = result.get("claims") or []
        match = sum(row.get("verdict") == "MATCH" for row in claims)
        evidence = sum(bool(row.get("selected_evidence")) for row in claims)
        source_gate_outcomes[f"{source_gate}:{'MATCH' if match else 'UNRESOLVED'}"] += 1
        detail_rows.append({
            "index": record.get("index"), "job_id": job_id, "source_article_gate": source_gate,
            "pipeline": "Y" if pipeline else "N", "article_claims": (record.get("article") or {}).get("extracted_claims", 0),
            "measurements": len(claims), "ready": len(ready), "enrich": len(enrich), "reject": len(rejected),
            "verified_candidate_rows": len(verified), "match": match, "selected_evidence": evidence,
            "title": record.get("title", ""),
        })
    summary = {
        "schema_version": "kosis-real-url-e2e-audit-v1",
        "counts": dict(audit),
        "source_gate_outcomes": dict(source_gate_outcomes),
        "verified_verdict_code_counts": dict(verdict_codes),
        "gate_reason_counts": dict(gates),
    }
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with args.details.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(detail_rows[0]) if detail_rows else ["index"])
        writer.writeheader(); writer.writerows(detail_rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
