"""Evaluate complete in_ready outputs against a locked common gold CSV."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter
from pathlib import Path

from prepare_kosis_mapping_input import canonicalize_unit


MISSING = {"", "-", "nan", "none", "null"}


def txt(value: object) -> str:
    raw = "" if value is None else str(value).strip()
    return "" if raw.lower() in MISSING else raw


def norm_value(value: object) -> str:
    raw = txt(value).replace(",", "")
    try:
        number = float(raw)
    except ValueError:
        return raw
    if math.isfinite(number) and number.is_integer():
        return str(int(number))
    return f"{number:.12g}"


def norm_period(value: object) -> str:
    raw = txt(value)
    digits = re.sub(r"\D", "", raw)
    return digits or raw


def norm_role(value: object) -> str:
    role = txt(value)
    return "증감량" if role in {"증감량", "증감값"} else role


def item_bucket(text: str) -> str:
    for pattern, label in [
        (r"반도체", "반도체"),
        (r"자동차", "자동차"),
        (r"선박", "선박"),
        (r"바이오헬스", "바이오헬스"),
        (r"농수산식품", "농수산식품"),
        (r"화장품", "화장품"),
        (r"석유화학", "석유화학"),
        (r"LCC|저비용", "LCC"),
        (r"대형|FSC", "FSC"),
        (r"외국인", "외국인"),
        (r"조선", "조선"),
    ]:
        if re.search(pattern, text, re.I):
            return label
    return "전체"


def indicator_family(row: dict[str, str]) -> str:
    indicator = txt(row.get("measurement_indicator")) or txt(row.get("indicator"))
    item = txt(row.get("measurement_item")) or txt(row.get("industry_or_item"))
    bucket = item_bucket(" ".join([indicator, item]))
    if re.search(r"소비자\s*물가|소비자물가지수", indicator):
        return "소비자물가"
    if re.search(r"산업\s*생산|생산지수", indicator):
        return "산업생산"
    if "소매판매" in indicator:
        return "소매판매"
    if re.search(r"무역수지|무역\s*흑자|흑자\s*폭|^흑자$", indicator):
        return "무역수지"
    if "수입" in indicator:
        return f"수입:{bucket}"
    if "수출" in indicator:
        return f"수출:{bucket}"
    if re.search(r"이용객|여객", indicator):
        return f"항공여객:{bucket}"
    if "정비사" in indicator:
        return f"항공정비사:{bucket}"
    if re.search(r"산업기술인력|외국인\s*(수|비율|인력)", indicator):
        return f"산업기술인력:{bucket}"
    if re.search(r"경제성장|성장률", indicator):
        return "경제성장"
    if re.search(r"취업자", indicator):
        return "취업자"
    if re.search(r"로봇", indicator):
        return "로봇"
    if re.search(r"완성차|판매량", indicator):
        return f"판매량:{bucket}"
    normalized = re.sub(r"[^가-힣A-Za-z0-9]", "", indicator).lower()
    return normalized[:36] or "미분류"


def candidate_key(row: dict[str, str]) -> str:
    return "|".join(
        [
            txt(row.get("article_id")),
            indicator_family(row),
            norm_value(row.get("value")),
            canonicalize_unit(
                txt(row.get("canonical_unit")) or txt(row.get("unit"))
            ),
            norm_period(row.get("measurement_period")),
            txt(row.get("measurement_prd_se")) or txt(row.get("prd_se")),
            norm_role(row.get("measurement_role")),
        ]
    )


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_run(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("--run must be LABEL=CSV_PATH")
    label, path = value.split("=", 1)
    if not label.strip() or not path.strip():
        raise argparse.ArgumentTypeError("--run must be LABEL=CSV_PATH")
    return label.strip(), Path(path)


def ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def score(
    gold_rows: list[dict[str, str]],
    prediction_by_key: dict[str, str],
) -> dict[str, object]:
    tp = fp = fn = tn = 0
    details = []
    for row in gold_rows:
        key = row["candidate_key"]
        override = txt(row.get("human_override")).upper()
        actual = (
            override
            if override in {"Y", "N"}
            else (
                txt(row.get("gold_ready")).upper()
                or txt(row.get("gold_ready_draft")).upper()
            )
        )
        predicted = prediction_by_key.get(key, "N")
        if actual == "Y" and predicted == "Y":
            bucket = "TP"
            tp += 1
        elif actual == "N" and predicted == "Y":
            bucket = "FP"
            fp += 1
        elif actual == "Y":
            bucket = "FN"
            fn += 1
        else:
            bucket = "TN"
            tn += 1
        details.append(
            {
                "candidate_id": row.get("candidate_id", ""),
                "candidate_key": key,
                "gold_ready": actual,
                "predicted_in_ready": predicted,
                "confusion": bucket,
            }
        )
    precision = ratio(tp, tp + fp)
    recall = ratio(tp, tp + fn)
    return {
        "n": len(gold_rows),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "accuracy": ratio(tp + tn, len(gold_rows)),
        "precision": precision,
        "recall": recall,
        "f1": ratio(2 * precision * recall, precision + recall),
        "details": details,
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--run", action="append", required=True, type=parse_run)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--allow-ready-only", action="store_true")
    args = parser.parse_args()

    gold_rows = read_rows(args.gold)
    gold_keys = {row["candidate_key"] for row in gold_rows}
    summaries = []
    all_details = []
    unseen_rows = []

    for label, path in args.run:
        if not path.exists():
            raise SystemExit(f"run CSV not found: {path}")
        rows = read_rows(path)
        labels = Counter(txt(row.get("in_ready")).upper() for row in rows)
        if not args.allow_ready_only and not {"Y", "N"} <= set(labels):
            raise SystemExit(
                f"{label} must contain complete in_ready Y/N rows; found {dict(labels)}"
            )
        prediction_by_key: dict[str, str] = {}
        source_by_key: dict[str, dict[str, str]] = {}
        for row in rows:
            key = candidate_key(row)
            predicted = "Y" if txt(row.get("in_ready")).upper() == "Y" else "N"
            if predicted == "Y" or key not in prediction_by_key:
                prediction_by_key[key] = predicted
                source_by_key[key] = row

        result = score(gold_rows, prediction_by_key)
        unseen = [
            key
            for key, predicted in prediction_by_key.items()
            if predicted == "Y" and key not in gold_keys
        ]
        summary = {
            "method": label,
            "source_rows": len(rows),
            "source_unique_candidates": len(prediction_by_key),
            "source_in_ready_y_rows": labels.get("Y", 0),
            "gold_n": result["n"],
            "tp": result["tp"],
            "fp": result["fp"],
            "fn": result["fn"],
            "tn": result["tn"],
            "accuracy": result["accuracy"],
            "precision": result["precision"],
            "recall": result["recall"],
            "f1": result["f1"],
            "unseen_ready_candidates": len(unseen),
        }
        summaries.append(summary)
        all_details.extend({"method": label, **row} for row in result["details"])
        for key in unseen:
            unseen_rows.append(
                {
                    "method": label,
                    "candidate_key": key,
                    **source_by_key[key],
                }
            )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "context_window_metrics.csv", summaries)
    write_csv(args.out_dir / "context_window_scored_rows.csv", all_details)
    write_csv(args.out_dir / "context_window_unseen_ready.csv", unseen_rows)
    (args.out_dir / "context_window_metrics.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for summary in sorted(summaries, key=lambda row: row["f1"], reverse=True):
        print(
            f"{summary['method']}: F1={summary['f1']:.3f} "
            f"P={summary['precision']:.3f} R={summary['recall']:.3f} "
            f"Acc={summary['accuracy']:.3f} unseenY={summary['unseen_ready_candidates']}"
        )
    print(f"results={args.out_dir}", flush=True)


if __name__ == "__main__":
    main()
