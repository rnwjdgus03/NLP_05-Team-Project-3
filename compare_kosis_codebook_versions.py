"""Compare frozen v1 metrics with codebook v2 development metrics."""

from __future__ import annotations

import csv
from pathlib import Path


REPO = Path(__file__).resolve().parent
BASE = REPO / "outputs/bteam_holdout"
V1 = BASE / "holdout100_metrics.csv"
V2 = BASE / "holdout100_v2_development_metrics.csv"
CSV_OUTPUT = BASE / "codebook_v1_v2_development_comparison.csv"
REPORT_OUTPUT = BASE / "codebook_v1_v2_development_comparison.md"


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {row["metric"]: row for row in csv.DictReader(handle)}


def main():
    v1 = read(V1)
    v2 = read(V2)
    rows = []
    for metric, old in v1.items():
        new = v2[metric]
        old_rate = float(old["rate"])
        new_rate = float(new["rate"])
        rows.append({
            "metric": metric,
            "v1_result": f"{old['correct_or_success']}/{old['denominator']}",
            "v1_rate": old_rate,
            "v2_development_result": f"{new['correct_or_success']}/{new['denominator']}",
            "v2_development_rate": new_rate,
            "delta_percentage_points": (new_rate - old_rate) * 100,
            "definition": new["definition"],
        })
    fields = list(rows[0].keys())
    with CSV_OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    by_metric = {row["metric"]: row for row in rows}
    key_metrics = [
        "자동결정 커버리지",
        "검증 가능 여부 결정구간 정확도",
        "항목·시점 결합 엄격 정확도",
        "자동매핑 항목·시점 정밀도",
        "자동매핑 API 성공률",
    ]
    report = [
        "# KOSIS 코드북 v1-v2 개발 비교",
        "",
        "> v2는 첫 홀드아웃 오류를 보고 개발했으므로 독립 성능이 아니다. 새 holdout2 수동 골드 확정 후 최종 게이트를 다시 계산해야 한다.",
        "",
        "| 지표 | v1 | v2 개발 | 변화 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for metric in key_metrics:
        row = by_metric[metric]
        report.append(
            f"| {metric} | {row['v1_result']} ({row['v1_rate']:.1%}) | "
            f"{row['v2_development_result']} ({row['v2_development_rate']:.1%}) | "
            f"{row['delta_percentage_points']:+.1f}%p |"
        )
    report.extend([
        "",
        "## 해석",
        "",
        "- 항목·시점 결합 엄격 정확도는 18.2%에서 84.8%로 개선됐다.",
        "- 자동매핑 정밀도는 100%를 유지하면서 자동매핑 범위가 6건에서 28건으로 늘었다.",
        "- 새 독립 표본의 gold_* 컬럼이 비어 있으므로 84.8%를 최종 품질 통과로 사용하지 않는다.",
    ])
    REPORT_OUTPUT.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(CSV_OUTPUT.resolve())
    print(REPORT_OUTPUT.resolve())


if __name__ == "__main__":
    main()
