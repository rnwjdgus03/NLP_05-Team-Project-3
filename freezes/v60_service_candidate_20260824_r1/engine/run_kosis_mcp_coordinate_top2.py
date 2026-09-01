#!/usr/bin/env python3
"""Produce an independent KOSIS MCP coordinate Top-2 for each claim."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import requests

from kosis_coordinate_low_memory import (
    JsonlCheckpoint, prepare_unique_claims, search_eligible_claims,
)
from kosis_coordinate_merge import (
    SUGGESTION_SCHEMA_VERSION,
    canonical_coordinate_json,
    validate_suggestion_packet,
)
from kosis_hybrid_top3 import read_csv
from kosis_meta_coordinates import (
    build_coordinates, coordinate_document, normalize_periodicity,
)
from kosis_component_search import item_structure_state


TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")
RETRYABLE_STATUSES = {"mcp_error", "mcp_retryable_error"}
MCP_QUERY_STRATEGY_VERSION = "mcp-independent-query-v2"


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def remove_retryable_state_records(path: Path) -> int:
    """Remove nonterminal records so the same claim can be retried safely."""
    if not path.exists():
        return 0
    records = []
    removed = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("status") in RETRYABLE_STATUSES or (
                row.get("status") == "mcp_coordinate_abstention"
                and row.get("query_strategy_version") != MCP_QUERY_STRATEGY_VERSION
            ):
                removed += 1
            else:
                records.append(row)
    if removed:
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            for row in records:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    return removed


def claim_query(claim: Mapping[str, Any]) -> str:
    values = []
    for name in (
        "claim_text", "measurement_indicator", "indicator",
        "measurement_item", "industry_or_item", "obj_target_terms",
        "survey_name", "source_survey", "statistics_name", "stat_name",
        "metric_domain", "keywords", "unit", "prd_se", "region",
        "age_group", "gender", "origin_country", "destination_country",
    ):
        value = _text(claim.get(name))
        if value and value != "-" and value not in values:
            values.append(value)
    return " ".join(values)


def claim_query_variants(claim: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Generate MCP-only query variants without using local branch results."""
    variants: list[tuple[str, str]] = []

    def add(label: str, values: Sequence[Any]) -> None:
        parts = []
        for value in values:
            text = _text(value)
            if text and text != "-" and text not in parts:
                parts.append(text)
        query = " ".join(parts)
        if query and query not in {existing for _label, existing in variants}:
            variants.append((label, query))

    add("full_claim", [claim_query(claim)])
    add("indicator_item", [
        claim.get("measurement_indicator") or claim.get("indicator"),
        claim.get("measurement_item") or claim.get("industry_or_item"),
        claim.get("obj_target_terms"),
        claim.get("unit"),
        claim.get("prd_se") or claim.get("measurement_prd_se"),
    ])
    add("survey_indicator", [
        claim.get("survey_name") or claim.get("source_survey")
        or claim.get("statistics_name") or claim.get("stat_name"),
        claim.get("measurement_indicator") or claim.get("indicator"),
        claim.get("metric_domain"),
    ])
    add("raw_text", [claim.get("claim_text")])
    return variants


def parse_mcp_tool_result(response: Mapping[str, Any]) -> dict[str, Any]:
    error = response.get("error")
    if error:
        raise RuntimeError(f"MCP JSON-RPC error: {error}")
    result = response.get("result") or {}
    structured = result.get("structuredContent")
    if isinstance(structured, Mapping):
        return dict(structured)
    plain_text: list[str] = []
    for entry in result.get("content") or []:
        if not isinstance(entry, Mapping) or entry.get("type") != "text":
            continue
        text = _text(entry.get("text"))
        if text:
            plain_text.append(text)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, Mapping):
            return dict(parsed)
    detail = " | ".join(plain_text)[:1000]
    if detail:
        raise RuntimeError(f"MCP tool returned non-JSON text: {detail}")
    raise RuntimeError("MCP tool returned no structured JSON object")


def normalize_api_period(value: Any, prd_se: Any = "") -> str:
    """Normalize human period labels to the digit-only KOSIS API contract."""
    raw = _text(value)
    if not raw:
        return ""
    periodicity = _text(prd_se).upper()
    year_match = re.search(r"((?:19|20)\d{2})", raw)
    if not year_match:
        return re.sub(r"\D", "", raw)
    year = year_match.group(1)
    if periodicity == "Y":
        return year
    quarter_match = re.search(r"Q\s*([1-4])|([1-4])\s*분기", raw, re.IGNORECASE)
    if periodicity == "Q" or quarter_match:
        if quarter_match:
            quarter = quarter_match.group(1) or quarter_match.group(2)
            return f"{year}0{quarter}"
    month_match = re.search(r"(?:19|20)\d{2}\D*(1[0-2]|0?[1-9])", raw)
    if month_match:
        return f"{year}{int(month_match.group(1)):02d}"
    digits = re.sub(r"\D", "", raw)
    return digits or year


class McpHttpClient:
    def __init__(
        self, url: str, timeout: float = 90.0, *, min_interval: float = 0.35,
        cache_path: str | Path | None = None, max_retries: int = 3,
    ):
        self.url = url
        self.timeout = timeout
        self.min_interval = max(0.0, float(min_interval))
        self.max_retries = max(0, int(max_retries))
        self.last_call_at = 0.0
        self.session = requests.Session()
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        }
        self.request_id = 100
        self.cache = None
        if cache_path is not None:
            path = Path(cache_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self.cache = sqlite3.connect(path)
            self.cache.execute(
                """CREATE TABLE IF NOT EXISTS mcp_tool_cache (
                       request_sha256 TEXT PRIMARY KEY,
                       tool_name TEXT NOT NULL,
                       arguments_json TEXT NOT NULL,
                       response_json TEXT NOT NULL,
                       created_at REAL NOT NULL
                   )"""
            )
            self.cache.commit()

    def close(self) -> None:
        if self.cache is not None:
            self.cache.close()
            self.cache = None

    def _cache_key(self, name: str, arguments: Mapping[str, Any]) -> tuple[str, str]:
        arguments_json = json.dumps(
            dict(arguments), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        payload = f"{name}\n{arguments_json}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest(), arguments_json

    def call(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        cache_key, arguments_json = self._cache_key(name, arguments)
        if self.cache is not None:
            cached = self.cache.execute(
                "SELECT response_json FROM mcp_tool_cache WHERE request_sha256=?",
                (cache_key,),
            ).fetchone()
            if cached is not None:
                return json.loads(cached[0])
        for attempt in range(self.max_retries + 1):
            wait = self.min_interval - (time.monotonic() - self.last_call_at)
            if wait > 0:
                time.sleep(wait)
            self.request_id += 1
            try:
                response = self.session.post(
                    self.url,
                    headers=self.headers,
                    json={
                        "jsonrpc": "2.0", "id": self.request_id,
                        "method": "tools/call",
                        "params": {"name": name, "arguments": dict(arguments)},
                    },
                    timeout=self.timeout,
                )
                self.last_call_at = time.monotonic()
                response.raise_for_status()
                result = parse_mcp_tool_result(response.json())
            except (requests.RequestException, RuntimeError, ValueError):
                if attempt >= self.max_retries:
                    raise
                time.sleep(min(8.0, 0.5 * (2 ** attempt)))
                continue
            if self.cache is not None:
                with self.cache:
                    self.cache.execute(
                        """INSERT INTO mcp_tool_cache VALUES (?,?,?,?,?)
                           ON CONFLICT(request_sha256) DO UPDATE SET
                           response_json=excluded.response_json,
                           created_at=excluded.created_at""",
                        (
                            cache_key, name, arguments_json,
                            json.dumps(result, ensure_ascii=False, sort_keys=True), time.time(),
                        ),
                    )
            return result
        raise AssertionError("unreachable MCP retry state")


def normalized_meta_rows(
    raw_rows: Sequence[Mapping[str, Any]], table: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows = []
    for raw in raw_rows:
        row = dict(raw)
        row.setdefault("ORG_ID", _text(table.get("orgId")))
        row.setdefault("TBL_ID", _text(table.get("tableId")))
        row.setdefault("TBL_NM", _text(table.get("tableName")))
        rows.append(row)
    return rows


def lexical_coordinate_score(
    claim: Mapping[str, Any], coordinate: Mapping[str, Any], table_rank: int,
) -> float:
    query_tokens = set(TOKEN_RE.findall(claim_query(claim).lower()))
    document_tokens = set(TOKEN_RE.findall(coordinate_document(coordinate).lower()))
    overlap = len(query_tokens & document_tokens) / max(1, len(query_tokens))
    aggregate_names = {_text(value) for value in (coordinate.get("obj_names") or {}).values()}
    aggregate_bonus = 0.03 if aggregate_names & {"전국", "전체", "계", "총계", "합계"} else 0.0
    return (1.0 / max(1, table_rank)) + overlap + aggregate_bonus


def canonical_from_meta_coordinate(
    coordinate: Mapping[str, Any], claim: Mapping[str, Any], prd_se: str,
) -> dict[str, Any]:
    axis_values = []
    for order, value_id in sorted((coordinate.get("obj_codes") or {}).items()):
        axis_id = _text((coordinate.get("axis_ids") or {}).get(order))
        if axis_id and _text(value_id):
            axis_values.append({
                "axis_order": int(order),
                "axis_id": axis_id,
                "value_id": _text(value_id),
            })
    selected_prd_se = normalize_periodicity(
        claim.get("prd_se") or prd_se or claim.get("measurement_prd_se")
    )
    target_period = normalize_api_period(
        claim.get("period") or claim.get("measurement_period"), selected_prd_se,
    )
    previous_period = normalize_api_period(
        claim.get("comparison_period") or claim.get("previous_period"), selected_prd_se
    )
    return {
        "org_id": _text(coordinate.get("org_id")),
        "tbl_id": _text(coordinate.get("tbl_id")),
        "item_id": _text(coordinate.get("itm_id")),
        "axis_values": axis_values,
        "prd_se": selected_prd_se,
        "target_period": target_period,
        "previous_period": previous_period,
        "aggregation": _text(
            claim.get("period_aggregation") or claim.get("aggregation") or "none"
        ).lower(),
    }


def mcp_postgres_gate_decision(
    preflight: Mapping[str, Any], hypothesis: Mapping[str, Any],
) -> tuple[bool, str]:
    if not preflight.get("postgres_coordinate_valid"):
        return False, _text(preflight.get("postgres_coordinate_status")) or "coordinate_invalid"
    if preflight.get("period_alignment_state") != "exact":
        return False, "period_not_exact"
    if preflight.get("postgres_period_in_range") is not True:
        return False, "period_range_unconfirmed"
    if preflight.get("unit_precheck_state") != "compatible":
        return False, "unit_not_compatible"
    if not hypothesis.get("structural_compatible"):
        return False, "item_structure_incompatible"
    return True, "accepted"


def mcp_top2_for_claim(
    claim: Mapping[str, Any], client: McpHttpClient, *, search_limit: int = 8,
    postgres_store: Any = None, postgres_filter: bool = True,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if postgres_filter and postgres_store is None:
        raise ValueError("MCP PostgreSQL filter requires postgres_store")
    ranked: list[dict[str, Any]] = []
    table_errors = []
    searched_tables: dict[tuple[str, str], dict[str, Any]] = {}
    queries_used: list[dict[str, str]] = []
    for query_label, query in claim_query_variants(claim):
        queries_used.append({"label": query_label, "query": query})
        search = client.call("search_statistics", {
            "query": query,
            "limit": max(search_limit, 12 if query_label != "full_claim" else search_limit),
        })
        tables = list(search.get("results") or [])
        for table_rank, table in enumerate(tables, 1):
            table_key = (_text(table.get("orgId")), _text(table.get("tableId")))
            if not all(table_key):
                continue
            searched_tables.setdefault(table_key, dict(table))
            try:
                info = client.call("get_table_info", {
                    "orgId": table_key[0],
                    "tableId": table_key[1],
                    "infoType": "ITM",
                })
                period = client.call("get_table_info", {
                    "orgId": table_key[0],
                    "tableId": table_key[1],
                    "infoType": "PRD",
                })
            except Exception as error:
                table_errors.append({
                    "query_label": query_label,
                    "table": dict(table),
                    "error": str(error),
                })
                continue
            prd_se = _text((period.get("periodInfo") or {}).get("periodType"))
            coordinates = build_coordinates(
                normalized_meta_rows(info.get("rawData") or [], table),
                axis_value_limit=20,
                max_coordinates_per_table=1200,
            )
            for coordinate in coordinates:
                canonical = canonical_from_meta_coordinate(coordinate, claim, prd_se)
                score = lexical_coordinate_score(claim, coordinate, table_rank)
                if query_label != "full_claim":
                    score -= 0.08
                ranked.append({
                    "coordinate": canonical,
                    "score": score,
                    "table_rank": table_rank,
                    "query_label": query_label,
                    "table": dict(table),
                    "document": coordinate_document(coordinate),
                })
        if len(ranked) >= 2:
            break
    gate_rejections: dict[str, int] = {}
    if postgres_store is not None and postgres_filter and ranked:
        from run_kosis_top5_verification import (
            hydrate_postgres_catalog, postgres_preflight,
        )
        table_candidates = []
        seen_tables = set()
        for row in ranked:
            coordinate = row["coordinate"]
            key = (coordinate["org_id"], coordinate["tbl_id"])
            if key in seen_tables:
                continue
            seen_tables.add(key)
            table_candidates.append({
                "org_id": key[0], "tbl_id": key[1], "rank": row["table_rank"],
            })
        _, catalog = hydrate_postgres_catalog(postgres_store, table_candidates)
        filtered = []
        for row in ranked:
            coordinate = row["coordinate"]
            key = (coordinate["org_id"], coordinate["tbl_id"])
            preflight = postgres_preflight(coordinate, claim, catalog.get(key))
            table_catalog = catalog.get(key) or {}
            item = (table_catalog.get("items") or {}).get(coordinate["item_id"], {})
            hypothesis = item_structure_state(claim, item)
            accepted, rejection_reason = mcp_postgres_gate_decision(preflight, hypothesis)
            if not accepted:
                gate_rejections[rejection_reason] = gate_rejections.get(rejection_reason, 0) + 1
                continue
            if preflight.get("repaired_axis_values"):
                coordinate = dict(coordinate)
                coordinate["axis_values"] = preflight["repaired_axis_values"]
                coordinate["prd_se"] = preflight.get("api_prd_se") or coordinate["prd_se"]
                coordinate["target_period"] = preflight.get("normalized_target_period", "")
                coordinate["previous_period"] = preflight.get("normalized_previous_period", "")
                row["coordinate"] = coordinate
            row["postgres_preflight"] = preflight
            row["mapping_hypothesis"] = hypothesis
            filtered.append(row)
        ranked = filtered

    ranked.sort(key=lambda row: (-row["score"], row["table_rank"], canonical_coordinate_json(row["coordinate"])))
    selected = []
    seen = set()
    for row in ranked:
        key = canonical_coordinate_json(row["coordinate"])
        if key in seen:
            continue
        seen.add(key)
        selected.append(row)
        if len(selected) == 2:
            break
    state = {
        "claim_measurement_id": claim["claim_measurement_id"],
        "source": "kosis_mcp",
        "query": queries_used[0]["query"] if queries_used else "",
        "query_strategy_version": MCP_QUERY_STRATEGY_VERSION,
        "queries_used": queries_used,
        "searched_table_count": len(searched_tables),
        "coordinate_candidate_count": len(ranked),
        "selected_coordinate_count": len(selected),
        "status": (
            "coordinate_ready" if len(selected) == 2
            else "mcp_retryable_error" if table_errors
            else "mcp_coordinate_abstention"
        ),
        "table_errors": table_errors,
        "postgres_gate_enabled": bool(postgres_filter),
        "postgres_gate_rejection_counts": gate_rejections,
    }
    if len(selected) != 2:
        return None, state
    packet = {
        "schema_version": SUGGESTION_SCHEMA_VERSION,
        "claim_measurement_id": claim["claim_measurement_id"],
        "source": "kosis_mcp",
        "suggestions": [{
            "source": "kosis_mcp",
            "source_rank": rank,
            "coordinate": row["coordinate"],
            "score": row["score"],
            "rationale": "KOSIS MCP search_statistics + get_table_info 독립 후보",
            "evidence": {
                "mcp_tools": ["search_statistics", "get_table_info"],
                "mcp_table_rank": row["table_rank"],
                "mcp_query_label": row.get("query_label", ""),
                "table_name": _text(row["table"].get("tableName")),
                "coordinate_document": row["document"],
                "postgres_preflight": row.get("postgres_preflight", {}),
                "mapping_type": _text(
                    (row.get("mapping_hypothesis") or {}).get("resolved_mapping_type")
                ),
                "resolved_unit_hypothesis": _text(
                    (row.get("mapping_hypothesis") or {}).get("resolved_unit_hypothesis")
                ),
                "hypothesis_evidence": _text(
                    (row.get("mapping_hypothesis") or {}).get("hypothesis_evidence")
                ),
                "verification_review_required": _text(
                    claim.get("verification_review_required")
                ),
                "verification_review_reason": _text(
                    claim.get("verification_review_reason")
                ),
            },
        } for rank, row in enumerate(selected, 1)],
    }
    return validate_suggestion_packet(packet), state


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--claims", required=True, type=Path)
    parser.add_argument("--mcp-url", default="http://127.0.0.1:3000/mcp")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--state-output", required=True, type=Path)
    parser.add_argument("--search-limit", type=int, default=8)
    parser.add_argument("--mcp-min-interval", type=float, default=0.35)
    parser.add_argument("--mcp-cache", type=Path)
    parser.add_argument("--mcp-retries", type=int, default=3)
    parser.add_argument("--postgres-dsn", default=os.environ.get("KOSIS_POSTGRES_DSN"))
    parser.add_argument(
        "--postgres-filter", action="store_true", default=True,
        help="Deprecated compatibility flag; PostgreSQL filtering is mandatory in v20.",
    )
    args = parser.parse_args()
    if not args.postgres_dsn:
        parser.error("--postgres-dsn or KOSIS_POSTGRES_DSN is required in v20")
    claims = [
        claim for _row, claim in search_eligible_claims(
            prepare_unique_claims(read_csv(args.claims))
        )
    ]
    output = JsonlCheckpoint(args.output)
    removed_retryable = remove_retryable_state_records(args.state_output)
    state = JsonlCheckpoint(args.state_output)
    terminal_state_ids = {
        _text(row.get("claim_measurement_id")) for row in state.records
        if (
            row.get("status") == "mcp_coordinate_abstention"
            and row.get("query_strategy_version") == MCP_QUERY_STRATEGY_VERSION
        )
    }
    completed = output.completed_ids | terminal_state_ids
    pending = [claim for claim in claims if claim["claim_measurement_id"] not in completed]
    print(
        f"[mcp_top2] pending={len(pending)} completed={len(completed)} "
        f"retryable_records_removed={removed_retryable}", flush=True,
    )
    client = McpHttpClient(
        args.mcp_url, min_interval=args.mcp_min_interval,
        cache_path=args.mcp_cache, max_retries=args.mcp_retries,
    )
    postgres_store = None
    if args.postgres_dsn:
        from kosis_postgres_store import PostgresKosisMetadataStore
        postgres_store = PostgresKosisMetadataStore(args.postgres_dsn)
    try:
        for index, claim in enumerate(pending, 1):
            try:
                packet, status = mcp_top2_for_claim(
                    claim, client, search_limit=args.search_limit,
                    postgres_store=postgres_store,
                    postgres_filter=args.postgres_filter,
                )
            except Exception as error:
                packet = None
                status = {
                    "claim_measurement_id": claim["claim_measurement_id"],
                    "source": "kosis_mcp", "status": "mcp_error", "error": str(error),
                }
            if packet is not None:
                output.append(packet)
            # Retryable MCP/network failures must not become permanent checkpoints.
            if status.get("status") not in RETRYABLE_STATUSES:
                state.append(status)
            print(
                f"[mcp_top2] {index}/{len(pending)} claim={claim['claim_measurement_id']} "
                f"status={status['status']}", flush=True,
            )
    finally:
        client.close()
        if postgres_store is not None:
            postgres_store.close()


if __name__ == "__main__":
    main()
