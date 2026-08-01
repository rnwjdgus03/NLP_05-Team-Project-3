#!/usr/bin/env python3
"""동일 measurement 표본에서 매핑 방식(A/B/C)을 비교 평가한다.

평가 대상 고정: --measurements 로 준 measurement 집합(예: 1차 READY 177건)에 대해서만 계산한다.
골드 좌표가 없으면 recall 을 임의로 만들지 않고 '골드 필요'로 표시한다.

지표
  - measurement 수 / 후보 행 수
  - table recall@1,3,5      (gold_tbl_id 필요)
  - ITEM recall@1,3,5       (gold_itm_id 필요)
  - OBJ recall@1,3,5        (gold_obj_l1 필요)
  - API-valid measurement 수·비율            (validated CSV 필요)
  - 2차 READY / PROVISIONAL / NEEDS_CONFIRMATION / MAPPING_FAILED / NOT_EVALUATED
  - 최종 verdict 도달 수·비율                (verified CSV 필요)
  - 평균 검색·리랭킹 시간                    (stats CSV 필요)
  - KOSIS API 호출 수                        (validated CSV 의 attempted_combination_count 합)

사용법:
  python evaluate_chroma_hybrid_mapping.py \
    --label C_chroma_hybrid \
    --measurements outputs/.../05_hcx_measurements_kosis_ready.csv \
    --candidates outputs/.../05_hcx_measurements_kosis_chroma_candidates.csv \
    --validated  outputs/.../05_hcx_measurements_kosis_chroma_validated.csv \
    --verified   outputs/.../05_hcx_measurements_kosis_chroma_verified.csv \
    --gold outputs/.../gold_coordinates.csv \
    --output outputs/.../eval_C.json
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from kosis_meta_coordinates import read_csv_rows

STATUS_ORDER = ("READY", "PROVISIONAL", "NEEDS_CONFIRMATION",
                "MAPPING_FAILED", "API_ERROR", "NOT_EVALUATED")
GOLD_REQUIRED = "gold_required"


def _text(value: Any) -> str:
    return str(value or "").strip()


def measurement_key(row: Mapping[str, Any]) -> str:
    return _text(row.get("claim_measurement_id") or row.get("claim_id"))


def _rank(row: Mapping[str, Any]) -> int:
    try:
        return int(float(_text(row.get("candidate_rank")) or "999"))
    except ValueError:
        return 999


def ranked_by_measurement(rows: Iterable[Mapping[str, Any]],
                          keys: set[str]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        key = measurement_key(row)
        if key in keys:
            grouped[key].append(dict(row))
    return {key: sorted(items, key=_rank) for key, items in grouped.items()}


def gold_alternatives(value: Any) -> set[str]:
    """골드 값은 파이프(|)로 복수 정답을 담을 수 있다.

    같은 통계가 여러 표에 수록된 경우(예: 수출액이 DT_1R11006_FRM101 과
    DT_1R11001_FRM101 양쪽에 존재) 어느 쪽을 찾아도 검색은 성공한 것이다.
    정답을 하나로 강제하면 맞은 것을 틀렸다고 세게 된다.
    """
    return {part.strip() for part in _text(value).split("|") if part.strip()}


def recall_at_k(ranked: Mapping[str, list[dict]], gold: Mapping[str, str],
                field: str, ks=(1, 3, 5)) -> dict:
    """gold 가 있는 measurement 만 분모로 삼는다. 없으면 gold_required 를 반환."""
    labeled = {k: gold_alternatives(v) for k, v in gold.items() if _text(v)}
    if not labeled:
        return {f"recall@{k}": GOLD_REQUIRED for k in ks} | {"labeled": 0}
    out: dict[str, Any] = {"labeled": len(labeled)}
    for k in ks:
        hit = 0
        for key, wanted in labeled.items():
            top = ranked.get(key, [])[:k]
            if any(_text(row.get(field)) in wanted for row in top):
                hit += 1
        out[f"recall@{k}"] = round(hit / len(labeled), 4)
    return out


def best_status_by_measurement(validated: Iterable[Mapping[str, Any]],
                               keys: set[str]) -> dict[str, str]:
    priority = {status: i for i, status in enumerate(STATUS_ORDER)}
    best: dict[str, tuple[int, str]] = {}
    for row in validated:
        key = measurement_key(row)
        if key not in keys:
            continue
        status = _text(row.get("mapping_status")) or "NOT_EVALUATED"
        score = priority.get(status, len(STATUS_ORDER))
        if key not in best or score < best[key][0]:
            best[key] = (score, status)
    return {key: status for key, (_, status) in best.items()}


def api_valid_measurements(validated: Iterable[Mapping[str, Any]], keys: set[str]) -> set[str]:
    """요청 코드와 응답 코드가 일치한 후보를 하나라도 가진 measurement."""
    valid = set()
    for row in validated:
        key = measurement_key(row)
        if key in keys and _text(row.get("response_code_valid")).lower() in {"true", "1", "y", "yes"}:
            valid.add(key)
    return valid


def ready_coordinate_precision(
    validated: Iterable[Mapping[str, Any]],
    keys: set[str],
    gold: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Gold 좌표가 있는 READY measurement의 end-to-end precision/recall.

    골드의 비어 있지 않은 좌표 필드만 비교한다. READY가 여러 행이면 candidate_rank가
    가장 높은 한 행만 사용하며, PROVISIONAL은 자동 확정이 아니므로 분모에서 제외한다.
    """
    gold_fields = (
        ("gold_tbl_id", "tbl_id"),
        ("gold_itm_id", "selected_itm_id"),
        ("gold_obj_l1", "selected_obj_l1"),
        ("gold_obj_l2", "selected_obj_l2"),
        ("gold_obj_l3", "selected_obj_l3"),
    )
    labeled = {
        key: row for key, row in gold.items()
        if key in keys and any(_text(row.get(gold_field))
                               for gold_field, _ in gold_fields)
    }
    if not labeled:
        return {
            "precision": GOLD_REQUIRED,
            "recall": GOLD_REQUIRED,
            "correct": 0,
            "predicted": 0,
            "labeled": 0,
        }

    ready_rows: dict[str, dict] = {}
    for row in validated:
        key = measurement_key(row)
        if key not in labeled or _text(row.get("mapping_status")) != "READY":
            continue
        if key not in ready_rows or _rank(row) < _rank(ready_rows[key]):
            ready_rows[key] = dict(row)

    correct = 0
    for key, prediction in ready_rows.items():
        expected = labeled[key]
        comparisons = [
            _text(prediction.get(predicted_field)) in gold_alternatives(expected.get(gold_field))
            for gold_field, predicted_field in gold_fields
            if _text(expected.get(gold_field))
        ]
        if comparisons and all(comparisons):
            correct += 1
    predicted = len(ready_rows)
    return {
        "precision": round(correct / predicted, 4) if predicted else None,
        "recall": round(correct / len(labeled), 4),
        "correct": correct,
        "predicted": predicted,
        "labeled": len(labeled),
    }


def evaluate(label: str, keys: set[str], candidates, validated, verified, gold, stats) -> dict:
    ranked = ranked_by_measurement(candidates, keys)
    gold_tbl = {k: _text(v.get("gold_tbl_id")) for k, v in gold.items()}
    gold_itm = {k: _text(v.get("gold_itm_id")) for k, v in gold.items()}
    gold_obj = {k: _text(v.get("gold_obj_l1")) for k, v in gold.items()}

    result: dict[str, Any] = {
        "label": label,
        "measurements": len(keys),
        "candidate_rows": sum(len(v) for v in ranked.values()),
        "measurements_with_candidates": len(ranked),
        "table_recall": recall_at_k(ranked, gold_tbl, "tbl_id"),
        "item_recall": recall_at_k(ranked, gold_itm, "selected_itm_id"),
        "obj_recall": recall_at_k(ranked, gold_obj, "selected_obj_l1"),
    }

    if validated:
        statuses = best_status_by_measurement(validated, keys)
        counts = Counter(statuses.values())
        result["mapping_status"] = {status: counts.get(status, 0) for status in STATUS_ORDER}
        for status in ("READY", "PROVISIONAL"):
            result[f"{status.lower()}_ratio"] = round(counts.get(status, 0) / max(len(keys), 1), 4)
        valid = api_valid_measurements(validated, keys)
        result["api_valid_measurements"] = len(valid)
        result["api_valid_ratio"] = round(len(valid) / max(len(keys), 1), 4)
        calls = 0
        for row in validated:
            if measurement_key(row) in keys:
                try:
                    calls += int(float(_text(row.get("attempted_combination_count")) or 0))
                except ValueError:
                    pass
        result["kosis_api_calls"] = calls
        result["ready_coordinate_evaluation"] = ready_coordinate_precision(
            validated, keys, gold
        )
    else:
        result["mapping_status"] = "validated_csv_required"

    if verified:
        decided = {measurement_key(r) for r in verified
                   if measurement_key(r) in keys and _text(r.get("verdict"))}
        verdicts = Counter(_text(r.get("verdict")) for r in verified
                           if measurement_key(r) in keys and _text(r.get("verdict")))
        result["verdict_reached"] = len(decided)
        result["verdict_ratio"] = round(len(decided) / max(len(keys), 1), 4)
        result["verdict_counts"] = dict(verdicts)
        result["verdict_code_counts"] = dict(Counter(
            _text(r.get("verdict_code")) for r in verified if measurement_key(r) in keys))
    else:
        result["verdict_reached"] = "verified_csv_required"

    if stats:
        search = [float(r.get("search_seconds") or 0) for r in stats]
        rerank = [float(r.get("rerank_seconds") or 0) for r in stats]
        result["avg_search_seconds"] = round(sum(search) / max(len(search), 1), 4)
        result["avg_rerank_seconds"] = round(sum(rerank) / max(len(rerank), 1), 4)
    else:
        result["avg_search_seconds"] = "stats_csv_required"

    missing = []
    if not any(_text(v.get("gold_tbl_id")) for v in gold.values()):
        missing.append("gold_tbl_id (정답 통계표)")
    if not any(_text(v.get("gold_itm_id")) for v in gold.values()):
        missing.append("gold_itm_id (정답 ITEM 코드)")
    if not any(_text(v.get("gold_obj_l1")) for v in gold.values()):
        missing.append("gold_obj_l1 (정답 분류 코드)")
    result["missing_gold"] = missing
    ready_eval = result.get("ready_coordinate_evaluation", {})
    if missing:
        result["ready_precision"] = GOLD_REQUIRED
    else:
        result["ready_precision"] = ready_eval.get(
            "precision", "validated_csv_required"
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare KOSIS mapping strategies on a fixed sample")
    parser.add_argument("--label", required=True)
    parser.add_argument("--measurements", required=True, help="평가 대상 measurement CSV (예: 1차 READY)")
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--validated", default=None)
    parser.add_argument("--verified", default=None)
    parser.add_argument("--gold", default=None)
    parser.add_argument("--stats", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    keys = {measurement_key(r) for r in read_csv_rows(args.measurements)}
    keys.discard("")
    gold = {}
    if args.gold:
        for row in read_csv_rows(args.gold):
            key = measurement_key(row)
            if key:
                gold[key] = row
    result = evaluate(
        args.label, keys,
        read_csv_rows(args.candidates),
        read_csv_rows(args.validated) if args.validated else [],
        read_csv_rows(args.verified) if args.verified else [],
        gold,
        read_csv_rows(args.stats) if args.stats else [],
    )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"saved={args.output}")


if __name__ == "__main__":
    main()
