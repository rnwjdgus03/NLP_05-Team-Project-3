from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Iterable


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
    return rows


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def normalize_period(value: str) -> str:
    value = str(value or "").strip().upper()
    for token in ("년", "월", "분기", " ", "-", "."):
        value = value.replace(token, "")
    value = value.replace("Q", "")
    return value


def first_nonempty(row: dict[str, str], keys: Iterable[str]) -> str:
    for key in keys:
        value = str(row.get(key, "") or "").strip()
        if value:
            return value
    return ""


def candidate_rank(row: dict[str, str]) -> int:
    raw = first_nonempty(row, ("candidate_rank", "table_rank", "pre_hybrid_candidate_rank"))
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return 10**9


def coordinate_matches(prediction: dict[str, str], gold: dict[str, Any]) -> bool:
    mappings = [gold, *list(gold.get("acceptable_coordinates", []) or [])]
    for mapping in mappings:
        expected_table = str(mapping.get("gold_tbl_id", "") or mapping.get("tbl_id", ""))
        if prediction.get("tbl_id", "") != expected_table:
            continue
        expected_item = str(mapping.get("gold_itm_id", "") or mapping.get("itm_id", ""))
        if expected_item and prediction.get("selected_itm_id", "") != expected_item:
            continue
        if all(
            not (
                expected := str(
                    mapping.get(f"gold_obj_l{level}", "")
                    or mapping.get(f"obj_l{level}", "")
                )
            )
            or prediction.get(f"selected_obj_l{level}", "") == expected
            for level in range(1, 9)
        ):
            return True
    return False


def acceptable_table_ids(gold: dict[str, Any]) -> tuple[str, ...]:
    raw = gold.get("acceptable_tbl_ids", ())
    if isinstance(raw, str):
        alternates = [value.strip() for value in raw.split("|") if value.strip()]
    else:
        alternates = [str(value).strip() for value in (raw or ()) if str(value).strip()]
    canonical = str(gold.get("gold_tbl_id", "") or "").strip()
    return tuple(dict.fromkeys([canonical, *alternates]))


def evaluate(
    evidence: list[dict[str, Any]],
    candidates: list[dict[str, str]],
    selected: list[dict[str, str]],
    claims: list[dict[str, str]],
) -> dict[str, Any]:
    by_claim_candidates: dict[str, list[dict[str, str]]] = {}
    for row in candidates:
        by_claim_candidates.setdefault(row.get("claim_measurement_id", ""), []).append(row)
    for rows in by_claim_candidates.values():
        rows.sort(key=candidate_rank)

    selected_by_claim = {
        row.get("claim_measurement_id", ""): row
        for row in selected
        if row.get("claim_measurement_id", "")
    }
    claims_by_id = {
        row.get("claim_measurement_id", ""): row
        for row in claims
        if row.get("claim_measurement_id", "")
    }

    table_gold = [row for row in evidence if truthy(row.get("table_gold_eligible"))]
    coordinate_gold = [row for row in evidence if truthy(row.get("coordinate_gold_eligible"))]
    period_gold = [row for row in evidence if truthy(row.get("period_gold_eligible"))]

    rank_rows: list[dict[str, Any]] = []
    for gold in table_gold:
        claim_id = str(gold["claim_measurement_id"])
        expected = str(gold["gold_tbl_id"])
        accepted = acceptable_table_ids(gold)
        rank = None
        for row in by_claim_candidates.get(claim_id, []):
            if row.get("tbl_id", "") in accepted:
                rank = candidate_rank(row)
                break
        selected_row = selected_by_claim.get(claim_id)
        rank_rows.append(
            {
                "claim_measurement_id": claim_id,
                "article_id": gold.get("article_id", ""),
                "gold_tbl_id": expected,
                "acceptable_tbl_ids": list(accepted),
                "gold_rank": rank,
                "selected_tbl_id": (selected_row or {}).get("tbl_id", ""),
                "selected_table_exact": bool(selected_row and selected_row.get("tbl_id") in accepted),
            }
        )

    coordinate_exact = sum(
        1
        for gold in coordinate_gold
        if (prediction := selected_by_claim.get(str(gold["claim_measurement_id"])))
        and coordinate_matches(prediction, gold)
    )

    period_rows: list[dict[str, Any]] = []
    for gold in period_gold:
        claim_id = str(gold["claim_measurement_id"])
        claim = claims_by_id.get(claim_id, {})
        predicted = first_nonempty(claim, ("period", "measurement_period"))
        expected = str(gold.get("gold_period", ""))
        period_rows.append(
            {
                "claim_measurement_id": claim_id,
                "predicted_period": predicted,
                "gold_period": expected,
                "exact": normalize_period(predicted) == normalize_period(expected),
            }
        )

    table_count = len(table_gold)
    coordinate_count = len(coordinate_gold)
    period_count = len(period_gold)
    selected_table_exact = sum(1 for row in rank_rows if row["selected_table_exact"])
    selected_labeled = sum(
        1 for row in table_gold if str(row["claim_measurement_id"]) in selected_by_claim
    )

    def ratio(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 6) if denominator else None

    result: dict[str, Any] = {
        "evidence_rows": len(evidence),
        "table_gold_claims": table_count,
        "coordinate_gold_claims": coordinate_count,
        "period_gold_claims": period_count,
        "metrics": {},
        "table_rank_details": rank_rows,
        "period_details": period_rows,
    }
    metrics = result["metrics"]
    for cutoff in (1, 5, 10, 30):
        hits = sum(1 for row in rank_rows if row["gold_rank"] is not None and row["gold_rank"] <= cutoff)
        metrics[f"table_recall_at_{cutoff}"] = {"hits": hits, "total": table_count, "rate": ratio(hits, table_count)}
    metrics["selected_table_exact"] = {
        "hits": selected_table_exact,
        "total": table_count,
        "rate": ratio(selected_table_exact, table_count),
    }
    metrics["selected_table_precision_among_labeled_selected"] = {
        "hits": selected_table_exact,
        "total": selected_labeled,
        "rate": ratio(selected_table_exact, selected_labeled),
    }
    metrics["selected_coordinate_exact"] = {
        "hits": coordinate_exact,
        "total": coordinate_count,
        "rate": ratio(coordinate_exact, coordinate_count),
    }
    period_exact = sum(1 for row in period_rows if row["exact"])
    metrics["period_extraction_exact"] = {
        "hits": period_exact,
        "total": period_count,
        "rate": ratio(period_exact, period_count),
    }
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate a locked blind KOSIS run against MCP evidence")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--selected", type=Path, required=True)
    parser.add_argument("--claims", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = evaluate(
        read_jsonl(args.evidence),
        read_csv(args.candidates),
        read_csv(args.selected),
        read_csv(args.claims),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
