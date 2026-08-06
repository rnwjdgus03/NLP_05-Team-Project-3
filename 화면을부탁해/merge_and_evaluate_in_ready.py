"""Merge in_ready N/Y gold data and evaluate in_ready against gold_verifiable."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


DEFAULT_N_INPUT = Path(r"C:\Users\ogy87\바탕 화면\gold_measurement_in_ready_N_top100.csv")
DEFAULT_Y_INPUT = Path(
    r"C:\Users\ogy87\문서\카카오톡 받은 파일"
    r"\gold_measurement_in_ready_Y_top100_merged.csv"
)
DEFAULT_OUTPUT = Path("gold_measurement_in_ready_NY_top200_merged.csv")

REQUIRED_COLUMNS = {
    "claim_measurement_id",
    "in_ready",
    "gold_verifiable",
}


def read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"입력 파일이 없습니다: {path.resolve()}")
    return pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)


def validate_columns(frame: pd.DataFrame, path: Path) -> None:
    missing = sorted(REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError(f"{path}에 필수 컬럼이 없습니다: {', '.join(missing)}")


def safe_divide(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else float("nan")


def merge_and_evaluate(
    n_input: Path,
    y_input: Path,
    output: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    n_rows = read_csv(n_input)
    y_rows = read_csv(y_input)
    validate_columns(n_rows, n_input)
    validate_columns(y_rows, y_input)

    if list(n_rows.columns) != list(y_rows.columns):
        raise ValueError("두 입력 파일의 컬럼 또는 컬럼 순서가 서로 다릅니다.")

    merged = pd.concat([n_rows, y_rows], ignore_index=True)

    invalid = merged.loc[
        ~merged["in_ready"].isin(["Y", "N"])
        | ~merged["gold_verifiable"].isin(["Y", "N"])
    ]
    if not invalid.empty:
        raise ValueError(
            "in_ready 또는 gold_verifiable에 Y/N 이외의 값이 있습니다: "
            f"{len(invalid)}행"
        )

    duplicate_mask = merged["claim_measurement_id"].duplicated(keep=False)
    duplicate_count = int(duplicate_mask.sum())

    output.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(output, index=False, encoding="utf-8-sig")

    confusion = (
        pd.crosstab(
            merged["gold_verifiable"],
            merged["in_ready"],
            rownames=["actual_gold_verifiable"],
            colnames=["predicted_in_ready"],
            dropna=False,
        )
        .reindex(index=["Y", "N"], columns=["Y", "N"], fill_value=0)
        .astype(int)
    )

    tp = int(confusion.loc["Y", "Y"])
    fn = int(confusion.loc["Y", "N"])
    fp = int(confusion.loc["N", "Y"])
    tn = int(confusion.loc["N", "N"])

    metrics = pd.Series(
        {
            "accuracy": safe_divide(tp + tn, len(merged)),
            "precision_ready_Y": safe_divide(tp, tp + fp),
            "recall_ready_Y": safe_divide(tp, tp + fn),
            "specificity_ready_N": safe_divide(tn, tn + fp),
            "f1_ready_Y": safe_divide(2 * tp, 2 * tp + fp + fn),
        },
        name="score",
    )

    print(f"N 입력 행: {len(n_rows)}")
    print(f"Y 입력 행: {len(y_rows)}")
    print(f"합본 행: {len(merged)}")
    print(f"claim_measurement_id 중복 행: {duplicate_count}")
    print(f"저장 경로: {output.resolve()}")
    print("\n혼동행렬 (행=gold_verifiable, 열=in_ready)")
    print(confusion)
    print("\n평가 지표")
    for name, value in metrics.items():
        print(f"{name}: {value:.2%}")

    return merged, confusion, metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="in_ready N/Y 골드 데이터를 합치고 gold_verifiable 기준 성능을 계산합니다."
    )
    parser.add_argument("--n-input", type=Path, default=DEFAULT_N_INPUT)
    parser.add_argument("--y-input", type=Path, default=DEFAULT_Y_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    merge_and_evaluate(args.n_input, args.y_input, args.output)


if __name__ == "__main__":
    main()
