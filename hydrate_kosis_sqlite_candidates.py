#!/usr/bin/env python3
"""Hydrate exact KOSIS metadata for every retrieved Top-N table candidate.

The vector/catalog retrieval result determines the hydration scope.  Gold
labels are deliberately not accepted as input, so the same operation can be
used in development and on a genuinely unseen holdout without label leakage.
The baseline SQLite database is copied to a run-local database and never
modified in place.
"""

from __future__ import annotations

import argparse
import csv
import http.client
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping

from kosis_build_meta_index import append_csv, convert_meta_rows
from kosis_meta_coordinates import normalize_periodicity
from kosis_sqlite_metadata import (
    connect,
    counts,
    create_schema,
    import_meta_index,
    sha256,
    upsert_meta_rows,
)


STATUS_FIELDS = (
    "org_id",
    "tbl_id",
    "tbl_name",
    "status",
    "item_rows",
    "periodicities",
    "axes_after",
    "items_after",
    "periodicities_after",
    "error",
    "updated_at",
)
TERMINAL_STATUSES = {
    "DB_PRESENT",
    "HYDRATED",
    "HYDRATED_NO_PERIODICITY",
    "NO_ITM_ROWS",
}
PROJECT_DIR = Path(__file__).resolve().parent
KOSIS_META_URL = "https://kosis.kr/openapi/statisticsData.do"
_UNQUOTED_KEY = re.compile(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)")


def clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def load_kosis_api_key() -> str:
    value = clean(os.environ.get("KOSIS_API_KEY"))
    if value:
        return value
    env_path = PROJECT_DIR / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, raw = line.split("=", 1)
            if key.strip() == "KOSIS_API_KEY":
                value = raw.strip().strip("\"'")
                if value:
                    return value
    raise RuntimeError("KOSIS_API_KEY is not configured in the environment or .env")


def parse_kosis_json(text: str) -> list[dict[str, object]]:
    fixed = _UNQUOTED_KEY.sub(r'\1"\2"\3', text)
    parsed = json.loads(fixed)
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise ValueError(f"unexpected KOSIS response type: {type(parsed).__name__}")
    return [row for row in parsed if isinstance(row, dict)]


def fetch_kosis_meta(
    org_id: str,
    tbl_id: str,
    meta_type: str,
    *,
    timeout: float = 20.0,
    retries: int = 4,
) -> list[dict[str, object]]:
    params = {
        "method": "getMeta",
        "type": meta_type,
        "apiKey": load_kosis_api_key(),
        "orgId": org_id,
        "tblId": tbl_id,
        "format": "json",
    }
    curl = shutil.which("curl")
    if curl:
        command = [
            curl,
            "--silent",
            "--show-error",
            "--fail-with-body",
            "--location",
            "--max-time",
            str(int(timeout)),
            "--retry",
            str(retries),
            "--retry-all-errors",
            "--get",
            KOSIS_META_URL,
        ]
        for key, value in params.items():
            command.extend(("--data-urlencode", f"{key}={value}"))
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        if result.returncode:
            # stderr contains transport diagnostics, not the URL/API key.
            raise RuntimeError(f"KOSIS curl request failed ({result.returncode}): {clean(result.stderr)}")
        return parse_kosis_json(result.stdout)

    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{KOSIS_META_URL}?{query}",
        headers={"User-Agent": "kosis-factcheck-metadata-hydrator/1.0"},
    )
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read().decode("utf-8-sig")
            return parse_kosis_json(payload)
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            http.client.HTTPException,
            TimeoutError,
            OSError,
        ) as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(2**attempt)
    raise RuntimeError(f"KOSIS metadata request failed after {retries + 1} attempts: {last_error}")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[Mapping[str, object]], fields: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def append_status(path: Path, row: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.is_file() and path.stat().st_size > 0
    with path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=STATUS_FIELDS, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def int_value(value: object, default: int = 10**9) -> int:
    try:
        return int(float(clean(value)))
    except ValueError:
        return default


def claim_key(row: Mapping[str, str]) -> str:
    return clean(row.get("claim_measurement_id") or row.get("gold_id") or row.get("claim_id"))


def candidate_rank(row: Mapping[str, str]) -> int:
    for field in ("candidate_rank", "table_rank", "pre_hybrid_candidate_rank"):
        if clean(row.get(field)):
            return int_value(row.get(field))
    return 10**9


def select_candidate_tables(
    candidates: Iterable[Mapping[str, str]], top_k: int
) -> list[dict[str, str]]:
    """Return globally deduplicated tables from each claim's first Top-K ranks."""
    grouped: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in candidates:
        key = claim_key(row)
        if key:
            grouped[key].append(row)

    selected: dict[tuple[str, str], dict[str, str]] = {}
    claim_counts: dict[tuple[str, str], set[str]] = defaultdict(set)
    best_rank: dict[tuple[str, str], int] = {}
    for key, rows in grouped.items():
        rows = sorted(rows, key=candidate_rank)
        per_claim: set[tuple[str, str]] = set()
        for row in rows:
            org_id = clean(row.get("org_id"))
            tbl_id = clean(row.get("tbl_id"))
            table_key = (org_id, tbl_id)
            if not org_id or not tbl_id or table_key in per_claim:
                continue
            if len(per_claim) >= top_k:
                break
            per_claim.add(table_key)
            claim_counts[table_key].add(key)
            rank = candidate_rank(row)
            if table_key not in selected or rank < best_rank[table_key]:
                selected[table_key] = {
                    "org_id": org_id,
                    "tbl_id": tbl_id,
                    "tbl_name": clean(row.get("tbl_name")),
                    "category_path": clean(row.get("category_path")),
                }
                best_rank[table_key] = rank

    output = []
    for table_key, row in selected.items():
        output.append({
            **row,
            "best_candidate_rank": str(best_rank[table_key]),
            "claim_count": str(len(claim_counts[table_key])),
        })
    output.sort(key=lambda row: (int_value(row["best_candidate_rank"]), row["org_id"], row["tbl_id"]))
    return output


def periodicity_fields(rows: Iterable[Mapping[str, object]]) -> tuple[str, str]:
    codes: list[str] = []
    spans: list[str] = []
    for row in rows:
        code = normalize_periodicity(clean(row.get("PRD_SE")))
        if code and code not in codes:
            codes.append(code)
        start = clean(row.get("STRT_PRD_DE"))
        end = clean(row.get("END_PRD_DE"))
        if code and (start or end):
            spans.append(f"{code}:{start}~{end}")
    return "|".join(codes), ";".join(spans)


def table_counts(connection, org_id: str, tbl_id: str) -> dict[str, int]:
    return {
        "items": int(connection.execute(
            "SELECT COUNT(*) FROM kosis_items WHERE org_id=? AND tbl_id=?", (org_id, tbl_id)
        ).fetchone()[0]),
        "axes": int(connection.execute(
            "SELECT COUNT(*) FROM kosis_axes WHERE org_id=? AND tbl_id=?", (org_id, tbl_id)
        ).fetchone()[0]),
        "periodicities": int(connection.execute(
            "SELECT COUNT(*) FROM kosis_periodicities WHERE org_id=? AND tbl_id=?",
            (org_id, tbl_id),
        ).fetchone()[0]),
    }


def load_terminal_statuses(path: Path) -> set[tuple[str, str]]:
    if not path.is_file():
        return set()
    latest: dict[tuple[str, str], str] = {}
    for row in read_csv(path):
        key = (clean(row.get("org_id")), clean(row.get("tbl_id")))
        if all(key):
            latest[key] = clean(row.get("status"))
    return {key for key, status in latest.items() if status in TERMINAL_STATUSES}


def prepare_database(base_db: Path, output_db: Path, meta_output: Path) -> None:
    if base_db.resolve() == output_db.resolve():
        raise ValueError("output DB must differ from the baseline DB")
    output_db.parent.mkdir(parents=True, exist_ok=True)
    if not output_db.exists():
        if not base_db.is_file():
            raise FileNotFoundError(f"baseline metadata DB not found: {base_db}")
        shutil.copy2(base_db, output_db)
    connection = connect(output_db)
    try:
        create_schema(connection)
        if meta_output.is_file() and meta_output.stat().st_size > 0:
            import_meta_index(connection, meta_output)
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()


def hydrate(
    *,
    candidates: list[dict[str, str]],
    output_db: Path,
    meta_output: Path,
    status_output: Path,
    top_k: int,
    delay: float,
    limit: int = 0,
    resume: bool = True,
    fetch_meta: Callable[[str, str, str], list[dict[str, object]]] | None = None,
) -> dict[str, object]:
    if fetch_meta is None:
        fetch_meta = fetch_kosis_meta
    tables = select_candidate_tables(candidates, top_k)
    terminal = load_terminal_statuses(status_output) if resume else set()
    todo = [row for row in tables if (row["org_id"], row["tbl_id"]) not in terminal]
    if limit:
        todo = todo[:limit]

    connection = connect(output_db)
    hydrated = present = no_items = failures = 0
    try:
        create_schema(connection)
        before = counts(connection)
        for index, table in enumerate(todo, start=1):
            org_id = table["org_id"]
            tbl_id = table["tbl_id"]
            prior = table_counts(connection, org_id, tbl_id)
            now = datetime.now(timezone.utc).isoformat()
            if prior["items"] and prior["periodicities"]:
                present += 1
                append_status(status_output, {
                    **table,
                    "status": "DB_PRESENT",
                    "item_rows": prior["items"],
                    "periodicities": "",
                    "axes_after": prior["axes"],
                    "items_after": prior["items"],
                    "periodicities_after": prior["periodicities"],
                    "error": "",
                    "updated_at": now,
                })
                print(f"[{index}/{len(todo)}] {org_id}:{tbl_id} DB_PRESENT", flush=True)
                continue

            try:
                itm_rows = fetch_meta(org_id, tbl_id, "ITM") or []
                itm_rows = [
                    dict(row) for row in itm_rows
                    if clean(row.get("OBJ_ID")) and clean(row.get("ITM_ID"))
                ]
                if delay:
                    time.sleep(delay)
                prd_rows = fetch_meta(org_id, tbl_id, "PRD") or []
                prd_se_list, prd_ranges = periodicity_fields(prd_rows)
                table_with_period = {
                    **table,
                    "prd_se_list": prd_se_list,
                    "prd_ranges": prd_ranges,
                }
                normalized_rows = convert_meta_rows(table_with_period, itm_rows)
                if normalized_rows:
                    append_csv(meta_output, normalized_rows, write_header=not meta_output.exists())
                    upsert_meta_rows(connection, normalized_rows)
                    hydrated += 1
                    status = "HYDRATED" if prd_se_list else "HYDRATED_NO_PERIODICITY"
                else:
                    no_items += 1
                    status = "NO_ITM_ROWS"
                after = table_counts(connection, org_id, tbl_id)
                append_status(status_output, {
                    **table,
                    "status": status,
                    "item_rows": len(itm_rows),
                    "periodicities": prd_se_list,
                    "axes_after": after["axes"],
                    "items_after": after["items"],
                    "periodicities_after": after["periodicities"],
                    "error": "",
                    "updated_at": now,
                })
                print(
                    f"[{index}/{len(todo)}] {org_id}:{tbl_id} {status} "
                    f"items={after['items']} axes={after['axes']} prd={after['periodicities']}",
                    flush=True,
                )
            except Exception as exc:  # checkpoint the failure; --resume retries it
                failures += 1
                append_status(status_output, {
                    **table,
                    "status": "ERROR",
                    "item_rows": 0,
                    "periodicities": "",
                    "axes_after": prior["axes"],
                    "items_after": prior["items"],
                    "periodicities_after": prior["periodicities"],
                    "error": f"{type(exc).__name__}: {exc}",
                    "updated_at": now,
                })
                print(f"[{index}/{len(todo)}] {org_id}:{tbl_id} ERROR {exc}", flush=True)
            if delay:
                time.sleep(delay)
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        after_all = counts(connection)
    finally:
        connection.close()
    return {
        "candidate_tables": len(tables),
        "terminal_before": len(terminal),
        "attempted": len(todo),
        "db_present": present,
        "hydrated": hydrated,
        "no_item_rows": no_items,
        "failures": failures,
        "counts_before": before,
        "counts_after": after_all,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table-candidates", type=Path, required=True)
    parser.add_argument("--base-db", type=Path, required=True)
    parser.add_argument("--output-db", type=Path, required=True)
    parser.add_argument("--meta-output", type=Path, required=True)
    parser.add_argument("--status-output", type=Path, required=True)
    parser.add_argument("--scope-output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--delay", type=float, default=0.12)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    candidates = read_csv(args.table_candidates)
    scope = select_candidate_tables(candidates, args.top_k)
    write_csv(
        args.scope_output,
        scope,
        ("org_id", "tbl_id", "tbl_name", "category_path", "best_candidate_rank", "claim_count"),
    )
    prepare_database(args.base_db, args.output_db, args.meta_output)
    summary = hydrate(
        candidates=candidates,
        output_db=args.output_db,
        meta_output=args.meta_output,
        status_output=args.status_output,
        top_k=args.top_k,
        delay=args.delay,
        limit=args.limit,
        resume=not args.no_resume,
    )
    manifest = {
        "schema_version": "kosis-candidate-metadata-hydration-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "selection_policy": "all claims, first unique Top-N retrieved tables, no gold-label input",
        "top_k": args.top_k,
        "limit": args.limit,
        "table_candidates": str(args.table_candidates),
        "table_candidates_sha256": sha256(args.table_candidates),
        "base_db": str(args.base_db),
        "base_db_sha256": sha256(args.base_db),
        "output_db": str(args.output_db),
        "scope_output": str(args.scope_output),
        "meta_output": str(args.meta_output),
        "status_output": str(args.status_output),
        **summary,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
