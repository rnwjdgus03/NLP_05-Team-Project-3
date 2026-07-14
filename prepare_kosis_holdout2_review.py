"""Apply frozen codebook v2 to the fresh holdout2 and prepare gold review."""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

import kosis_codebook_v2 as codebook


REPO = Path(__file__).resolve().parent
OUTPUT_DIR = REPO / "outputs/bteam_holdout2"
INPUT = OUTPUT_DIR / "holdout2_100_selection.csv"
REVIEW_OUTPUT = OUTPUT_DIR / "holdout2_100_review.csv"
REPORT_OUTPUT = OUTPUT_DIR / "holdout2_100_review_report.md"
codebook.CACHE_PATH = OUTPUT_DIR / "holdout2_auto_api_cache.json"
csv.field_size_limit(sys.maxsize)

AUTO_FIELDS = [
    "auto_decision", "auto_exclusion_reason", "auto_org_id", "auto_tbl_id", "auto_obj_l1",
    "auto_obj_l2", "auto_itm_id", "auto_prd_se", "auto_target_number", "auto_target_period",
    "auto_prev_period", "auto_mode", "auto_note", "auto_api_success", "auto_actual_number",
    "auto_current_value", "auto_previous_value", "auto_unit", "auto_verdict", "auto_api_error",
]
GOLD_FIELDS = [
    "gold_verifiable", "gold_exclusion_reason", "gold_org_id", "gold_tbl_id", "gold_obj_l1",
    "gold_obj_l2", "gold_itm_id", "gold_prd_se", "gold_target_number", "gold_target_period",
    "gold_prev_period", "gold_mode", "gold_verdict", "gold_evidence", "gold_reviewer_note",
]


def main():
    with INPUT.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        selection = list(reader)
        input_fields = list(reader.fieldnames or [])
    if len(selection) != 100:
        raise RuntimeError(f"holdout2 rows={len(selection)}")

    cache = codebook.read_cache()
    rows = []
    for source in selection:
        out = dict(source)
        config, exclusion = codebook.map_by_codebook(source)
        if config:
            out["auto_decision"] = "검증가능"
            out["auto_exclusion_reason"] = ""
            for key in ("org_id", "tbl_id", "obj_l1", "obj_l2", "itm_id", "prd_se", "target_number", "target_period", "prev_period", "mode", "note"):
                out[f"auto_{key}"] = config.get(key, "")
            try:
                actual, current, previous, unit, verdict = codebook.verify(config, cache)
                if actual is None:
                    raise ValueError(verdict)
                out["auto_api_success"] = "Y"
                out["auto_actual_number"] = actual
                out["auto_current_value"] = current
                out["auto_previous_value"] = previous
                out["auto_unit"] = unit
                out["auto_verdict"] = verdict
                out["auto_api_error"] = ""
            except Exception as exc:
                out["auto_api_success"] = "N"
                out["auto_actual_number"] = ""
                out["auto_current_value"] = ""
                out["auto_previous_value"] = ""
                out["auto_unit"] = ""
                out["auto_verdict"] = "판단불가"
                out["auto_api_error"] = str(exc)
        elif exclusion:
            out["auto_decision"] = "검증불가"
            out["auto_exclusion_reason"] = exclusion[0]
            for field in AUTO_FIELDS[2:]:
                out[field] = ""
            out["auto_api_success"] = "N/A"
            out["auto_verdict"] = "판단불가"
            out["auto_api_error"] = exclusion[1]
        else:
            out["auto_decision"] = "보류"
            out["auto_exclusion_reason"] = ""
            for field in AUTO_FIELDS[2:]:
                out[field] = ""
            out["auto_api_success"] = "N/A"
            out["auto_verdict"] = ""
            out["auto_api_error"] = ""
        for field in GOLD_FIELDS:
            out[field] = ""
        rows.append(out)

    fields = input_fields + AUTO_FIELDS + GOLD_FIELDS
    with REVIEW_OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    decision_counts = Counter(row["auto_decision"] for row in rows)
    domain_counts = Counter(row["holdout_domain"] for row in rows)
    source_counts = Counter(row["source_dataset"] for row in rows)
    mapped = [row for row in rows if row["auto_decision"] == "검증가능"]
    api_counts = Counter(row["auto_api_success"] for row in mapped)
    report = [
        "# KOSIS 코드북 v2 새 독립 표본 검토 준비",
        "",
        "## 상태",
        "",
        "- 골드100과 첫 홀드아웃100의 claim_id·article_id 중복 0건",
        f"- 표본: {len(rows)}건, 분야별 {dict(domain_counts)}",
        f"- 모집단 출처: {dict(source_counts)}",
        f"- 코드북 v2 자동 결정: {dict(decision_counts)}",
        f"- 자동 매핑 API 결과: {dict(api_counts)}",
        "- 현재 파일의 gold_* 컬럼은 비어 있으며 사람이 확정하기 전까지 품질 게이트를 계산하지 않는다.",
        "",
        "## 수동 확정 순서",
        "",
        "1. KOSIS 검증 가능 여부와 판단불가 사유를 확정한다.",
        "2. 검증 가능하면 올바른 기관·통계표·분류·항목·주기를 입력한다.",
        "3. 목표 수치와 정확 시점·비교 시점을 입력한다.",
        "4. KOSIS 값과 최종 판정 및 근거를 기록한다.",
        "5. 100건을 모두 확정한 뒤 코드북 v2를 수정하지 않은 상태로 80% 게이트를 계산한다.",
        "",
        "## 파일",
        "",
        "- `holdout2_100_selection.csv`: 새 독립 표본",
        "- `holdout2_100_review.csv`: 자동 예측 + 수동 골드 입력용",
        "- `holdout2_auto_api_cache.json`: 자동 매핑 API 캐시",
    ]
    REPORT_OUTPUT.write_text("\n".join(report) + "\n", encoding="utf-8")

    print(f"rows={len(rows)} domains={dict(domain_counts)}")
    print(f"sources={dict(source_counts)}")
    print(f"auto_decisions={dict(decision_counts)} api={dict(api_counts)}")
    print(REVIEW_OUTPUT.resolve())


if __name__ == "__main__":
    main()
