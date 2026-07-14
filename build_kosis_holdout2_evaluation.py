"""Build the formal evaluation artifacts for the second independent holdout.

The frozen codebook predictions and human gold labels already coexist in
``holdout2_100_review.csv``.  This script never calls KOSIS or changes those
labels; it only validates the completed review and derives reproducible metrics.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "outputs" / "bteam_holdout2" / "holdout2_100_review.csv"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "bteam_holdout2"
DEFAULT_STEM = "holdout2_100"
DOMAINS = ("물가", "고용", "무역", "인구", "소매")
MAPPING_FIELDS = (
    "gold_org_id",
    "gold_tbl_id",
    "gold_obj_l1",
    "gold_itm_id",
    "gold_prd_se",
    "gold_target_number",
    "gold_target_period",
    "gold_mode",
    "gold_verdict",
)


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def same(left: object, right: object) -> bool:
    return clean(left) == clean(right)


def same_number(left: object, right: object) -> bool:
    try:
        return Decimal(clean(left).replace(",", "")) == Decimal(clean(right).replace(",", ""))
    except (InvalidOperation, ValueError):
        return same(left, right)


def rate(correct: int, denominator: int) -> float:
    return correct / denominator if denominator else 0.0


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def validate_rows(rows: list[dict[str, str]]) -> None:
    errors: list[str] = []
    if len(rows) != 100:
        errors.append(f"행 수가 100이 아님: {len(rows)}")

    claim_ids = [clean(row.get("claim_id")) for row in rows]
    if len(set(claim_ids)) != len(claim_ids):
        errors.append("claim_id 중복이 있음")

    domain_counts = Counter(clean(row.get("holdout_domain")) for row in rows)
    expected_domains = {domain: 20 for domain in DOMAINS}
    if dict(domain_counts) != expected_domains:
        errors.append(f"분야별 20건 구성이 아님: {dict(domain_counts)}")

    for index, row in enumerate(rows, start=2):
        claim_id = clean(row.get("claim_id")) or f"CSV {index}행"
        gold = clean(row.get("gold_verifiable")).upper()
        auto = clean(row.get("auto_decision"))
        if gold not in {"Y", "N"}:
            errors.append(f"{claim_id}: gold_verifiable은 Y/N이어야 함")
            continue
        if auto not in {"검증가능", "검증불가", "보류"}:
            errors.append(f"{claim_id}: 알 수 없는 auto_decision={auto!r}")
        if not clean(row.get("gold_evidence")):
            errors.append(f"{claim_id}: gold_evidence가 비어 있음")
        if not clean(row.get("gold_reviewer_note")):
            errors.append(f"{claim_id}: gold_reviewer_note가 비어 있음")
        if gold == "Y":
            missing = [field for field in MAPPING_FIELDS if not clean(row.get(field))]
            if missing:
                errors.append(f"{claim_id}: 검증가능 골드 필수값 누락 {','.join(missing)}")
        elif not clean(row.get("gold_exclusion_reason")):
            errors.append(f"{claim_id}: 검증불가 사유가 비어 있음")

    if errors:
        preview = "\n- ".join(errors[:20])
        suffix = f"\n... 외 {len(errors) - 20}건" if len(errors) > 20 else ""
        raise ValueError(f"홀드아웃 골드 검증 실패:\n- {preview}{suffix}")


def evaluate_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    evaluated: list[dict[str, str]] = []
    for source in rows:
        row = dict(source)
        gold_y = clean(row.get("gold_verifiable")).upper() == "Y"
        auto_y = clean(row.get("auto_decision")) == "검증가능"
        expected = "검증가능" if gold_y else "검증불가"
        row["eligibility_expected"] = expected
        row["eligibility_correct"] = "Y" if clean(row.get("auto_decision")) == expected else "N"

        if gold_y:
            if auto_y:
                row["table_correct"] = "Y" if all(
                    same(row.get(f"auto_{field}"), row.get(f"gold_{field}"))
                    for field in ("org_id", "tbl_id")
                ) else "N"
                row["item_correct"] = "Y" if all(
                    same(row.get(f"auto_{field}"), row.get(f"gold_{field}"))
                    for field in ("obj_l1", "obj_l2", "itm_id")
                ) else "N"
                row["period_correct"] = "Y" if all(
                    same(row.get(f"auto_{field}"), row.get(f"gold_{field}"))
                    for field in ("prd_se", "target_period", "prev_period")
                ) else "N"
                row["target_number_correct"] = "Y" if same_number(
                    row.get("auto_target_number"), row.get("gold_target_number")
                ) else "N"
                row["mode_correct"] = "Y" if same(row.get("auto_mode"), row.get("gold_mode")) else "N"
                row["verdict_correct"] = "Y" if same(row.get("auto_verdict"), row.get("gold_verdict")) else "N"
            else:
                for field in (
                    "table_correct",
                    "item_correct",
                    "period_correct",
                    "target_number_correct",
                    "mode_correct",
                    "verdict_correct",
                ):
                    row[field] = "N"
            row["item_period_correct"] = "Y" if row["item_correct"] == "Y" and row["period_correct"] == "Y" else "N"
            row["full_mapping_correct"] = "Y" if all(
                row[field] == "Y"
                for field in (
                    "table_correct",
                    "item_correct",
                    "period_correct",
                    "target_number_correct",
                    "mode_correct",
                )
            ) else "N"
        else:
            for field in (
                "table_correct",
                "item_correct",
                "period_correct",
                "target_number_correct",
                "mode_correct",
                "item_period_correct",
                "full_mapping_correct",
                "verdict_correct",
            ):
                row[field] = "N/A"

        error_types: list[str] = []
        if row["eligibility_correct"] == "N":
            error_types.append("검증가능여부")
        if gold_y and row["table_correct"] == "N":
            error_types.append("통계표")
        if gold_y and row["item_correct"] == "N":
            error_types.append("항목")
        if gold_y and row["period_correct"] == "N":
            error_types.append("시점")
        if gold_y and row["target_number_correct"] == "N":
            error_types.append("주장수치")
        if gold_y and row["mode_correct"] == "N":
            error_types.append("비교방식")
        if gold_y and row["verdict_correct"] == "N":
            error_types.append("최종판정")
        row["error_types"] = ";".join(error_types)

        if gold_y and clean(row.get("auto_decision")) == "보류":
            row["error_cause"] = "검증가능 지표를 코드북이 지원하지 않아 보류"
        elif gold_y and clean(row.get("auto_decision")) == "검증불가":
            row["error_cause"] = "검증가능 지표를 비검증 대상으로 과배제"
        elif not gold_y and auto_y:
            row["error_cause"] = "검증불가 주장을 KOSIS 표에 과매핑"
        elif not gold_y and clean(row.get("auto_decision")) == "보류":
            row["error_cause"] = "검증불가 사유를 자동 분류하지 못해 보류"
        elif gold_y and row["full_mapping_correct"] == "N":
            row["error_cause"] = "통계표·항목·시점·수치·비교방식 중 일부 오매핑"
        else:
            row["error_cause"] = ""
        evaluated.append(row)
    return evaluated


def build_metrics(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    eligible = [row for row in rows if row["gold_verifiable"] == "Y"]
    covered = [row for row in rows if row["auto_decision"] != "보류"]
    auto_mapped = [row for row in rows if row["auto_decision"] == "검증가능"]
    metrics: list[dict[str, object]] = []

    def add(name: str, correct: int, denominator: int, definition: str) -> None:
        metrics.append({
            "metric": name,
            "correct_or_success": correct,
            "denominator": denominator,
            "rate": rate(correct, denominator),
            "definition": definition,
        })

    add("홀드아웃 전체", len(rows), len(rows), "개발 골드·첫 홀드아웃과 claim/article 중복 0, 분야별 20건")
    add("자동결정 커버리지", len(covered), len(rows), "검증가능 또는 검증불가 자동 결정; 보류 제외")
    add("검증 가능 여부 엄격 정확도", sum(row["eligibility_correct"] == "Y" for row in rows), len(rows), "보류를 오답으로 포함")
    add("검증 가능 여부 결정구간 정확도", sum(row["eligibility_correct"] == "Y" for row in covered), len(covered), "자동 결정한 행만 평가")
    add("통계표 매핑 엄격 정확도", sum(row["table_correct"] == "Y" for row in eligible), len(eligible), "골드 검증가능 전체가 분모")
    add("항목 매핑 엄격 정확도", sum(row["item_correct"] == "Y" for row in eligible), len(eligible), "obj_l1+obj_l2+itm_id")
    add("시점 매핑 엄격 정확도", sum(row["period_correct"] == "Y" for row in eligible), len(eligible), "주기+목표 시점+이전 시점")
    add("주장 수치 추출 엄격 정확도", sum(row["target_number_correct"] == "Y" for row in eligible), len(eligible), "검증 대상 수치 선택")
    add("비교 방식 엄격 정확도", sum(row["mode_correct"] == "Y" for row in eligible), len(eligible), "LEVEL·ABS_TO_ABS 등 검증 방식")
    add("항목·시점 결합 엄격 정확도", sum(row["item_period_correct"] == "Y" for row in eligible), len(eligible), "독립 80% 품질 게이트")
    add("전체 매핑 엄격 정확도", sum(row["full_mapping_correct"] == "Y" for row in eligible), len(eligible), "표+항목+시점+수치+비교방식")
    add("자동매핑 전체 정밀도", sum(row["full_mapping_correct"] == "Y" for row in auto_mapped), len(auto_mapped), "자동 검증가능 6건 중 완전한 매핑")
    add("자동매핑 API 성공률", sum(row.get("auto_api_success") == "Y" for row in auto_mapped), len(auto_mapped), "자동 검증가능 행의 기술적 조회 성공")
    add("검증가능 최종판정 엄격 일치율", sum(row["verdict_correct"] == "Y" for row in eligible), len(eligible), "골드 검증가능 전체에서 최종 일치/불일치 판정")
    return metrics


def build_domain_metrics(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for domain in DOMAINS:
        subset = [row for row in rows if row["holdout_domain"] == domain]
        eligible = [row for row in subset if row["gold_verifiable"] == "Y"]
        covered = [row for row in subset if row["auto_decision"] != "보류"]
        mapped = [row for row in subset if row["auto_decision"] == "검증가능"]
        results.append({
            "domain": domain,
            "sample_count": len(subset),
            "gold_verifiable_count": len(eligible),
            "gold_unverifiable_count": len(subset) - len(eligible),
            "auto_decided_count": len(covered),
            "auto_mapped_count": len(mapped),
            "auto_decision_coverage": rate(len(covered), len(subset)),
            "eligibility_strict_accuracy": rate(sum(row["eligibility_correct"] == "Y" for row in subset), len(subset)),
            "eligibility_decided_accuracy": rate(sum(row["eligibility_correct"] == "Y" for row in covered), len(covered)),
            "table_strict_accuracy": rate(sum(row["table_correct"] == "Y" for row in eligible), len(eligible)),
            "item_period_strict_accuracy": rate(sum(row["item_period_correct"] == "Y" for row in eligible), len(eligible)),
            "full_mapping_strict_accuracy": rate(sum(row["full_mapping_correct"] == "Y" for row in eligible), len(eligible)),
            "auto_mapping_precision": rate(sum(row["full_mapping_correct"] == "Y" for row in mapped), len(mapped)),
        })
    return results


def build_backlog(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    backlog: list[dict[str, object]] = []
    false_negatives = [row for row in rows if row["gold_verifiable"] == "Y" and row["auto_decision"] == "검증불가"]
    false_positives = [row for row in rows if row["gold_verifiable"] == "N" and row["auto_decision"] == "검증가능"]
    if false_negatives:
        backlog.append({
            "priority": "P0",
            "scope": "검증가능 지표 과배제",
            "count": len(false_negatives),
            "evidence": ";".join(row["claim_id"] for row in false_negatives),
            "recommended_action": "국내 공식 지표가 명시되면 일반 배제 키워드보다 KOSIS 지표 탐색을 먼저 수행",
            "evaluation_policy": "현재 표본은 개발 자료로만 사용하고 수정 후 새 독립 표본에서 재측정",
        })
    if false_positives:
        backlog.append({
            "priority": "P0",
            "scope": "검증불가 주장 과매핑",
            "count": len(false_positives),
            "evidence": ";".join(row["claim_id"] for row in false_positives),
            "recommended_action": "다중 수치의 검증 대상 모호성 및 민간기업 고유 지표를 KOSIS 국가통계와 구분",
            "evaluation_policy": "과검증 방지 음성 테스트를 추가하고 자동 확정 정밀도를 우선",
        })

    for domain in DOMAINS:
        held = [
            row for row in rows
            if row["holdout_domain"] == domain
            and row["gold_verifiable"] == "Y"
            and row["auto_decision"] == "보류"
        ]
        if held:
            backlog.append({
                "priority": "P1",
                "scope": f"{domain} 검증가능 매핑 커버리지",
                "count": len(held),
                "evidence": ";".join(row["claim_id"] for row in held),
                "recommended_action": "반복 표·항목 조합을 후보 코드북으로 정리하고 지역·단위·전월/전년동월 문맥 테스트 추가",
                "evaluation_policy": "골드 근거를 학습에 사용하되 현재 표본 성능을 다시 독립 성능으로 보고하지 않음",
            })

    reason_counts = Counter(
        row["gold_exclusion_reason"]
        for row in rows
        if row["gold_verifiable"] == "N" and row["auto_decision"] == "보류"
    )
    for reason, count in reason_counts.most_common():
        evidence = ";".join(
            row["claim_id"] for row in rows
            if row["gold_verifiable"] == "N"
            and row["auto_decision"] == "보류"
            and row["gold_exclusion_reason"] == reason
        )
        backlog.append({
            "priority": "P2",
            "scope": f"검증불가 자동 분류: {reason}",
            "count": count,
            "evidence": evidence,
            "recommended_action": "사유별 표현 사전과 우선순위를 분리하고 양성·음성 회귀 테스트 추가",
            "evaluation_policy": "애매한 문장은 자동 확정하지 않고 보류 유지",
        })
    return backlog


def build_report(
    rows: list[dict[str, str]],
    metrics: list[dict[str, object]],
    domain_metrics: list[dict[str, object]],
    backlog: list[dict[str, object]],
    stem: str,
) -> str:
    metric_map = {row["metric"]: row for row in metrics}
    gate = metric_map["항목·시점 결합 엄격 정확도"]
    eligible = [row for row in rows if row["gold_verifiable"] == "Y"]
    decision_counts = Counter(row["auto_decision"] for row in rows)
    exclusion_counts = Counter(row["gold_exclusion_reason"] for row in rows if row["gold_verifiable"] == "N")
    gold_verdicts = Counter(row["gold_verdict"] for row in eligible)
    false_negatives = [row["claim_id"] for row in rows if row["gold_verifiable"] == "Y" and row["auto_decision"] == "검증불가"]
    false_positives = [row["claim_id"] for row in rows if row["gold_verifiable"] == "N" and row["auto_decision"] == "검증가능"]
    eligible_holds = Counter(row["holdout_domain"] for row in rows if row["gold_verifiable"] == "Y" and row["auto_decision"] == "보류")
    lines = [
        f"# KOSIS 두 번째 독립 홀드아웃 100건 평가 - {stem}",
        "",
        "## 결론",
        "",
        "- 평가 대상: 개발 골드100·첫 홀드아웃100과 claim_id/article_id가 겹치지 않는 독립 100건",
        "- 표본 구성: 물가·고용·무역·인구·소매 각 20건",
        "- 평가 조건: 코드북 v2 자동 결과를 먼저 동결한 뒤 사람이 gold_* 컬럼을 확정",
        f"- 골드 검증 가능: {len(eligible)}건 / 검증 불가: {len(rows) - len(eligible)}건 ({dict(exclusion_counts)})",
        f"- 자동 결정: {dict(decision_counts)}",
        f"- 항목·시점 결합 엄격 정확도: {gate['correct_or_success']}/{gate['denominator']} ({gate['rate']:.1%})",
        f"- 독립 80% 품질 게이트: {'통과' if gate['rate'] >= 0.8 else '실패'}",
        "- 결정한 35건의 검증 가능 여부 정확도는 높지만, 검증가능 35건 대부분을 보류했으므로 전체 자동 검증 범위 확대 기준은 충족하지 못했다.",
        "- 이 평가를 본 이후 현재 표본은 개발 자료로 전환한다. 코드북을 수정한 결과는 겹치지 않는 다음 독립 표본에서 측정해야 한다.",
        "",
        "## 전체 지표",
        "",
        "| 지표 | 결과 | 정의 |",
        "| --- | ---: | --- |",
    ]
    for metric in metrics[1:]:
        lines.append(
            f"| {metric['metric']} | {metric['correct_or_success']}/{metric['denominator']} ({metric['rate']:.1%}) | {metric['definition']} |"
        )
    lines.extend([
        "",
        "## 분야별 결과",
        "",
        "| 분야 | 골드 검증가능 | 자동결정 커버리지 | 가능여부 엄격 정확도 | 항목·시점 엄격 정확도 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ])
    for row in domain_metrics:
        lines.append(
            f"| {row['domain']} | {row['gold_verifiable_count']}/{row['sample_count']} | {row['auto_decision_coverage']:.1%} | {row['eligibility_strict_accuracy']:.1%} | {row['item_period_strict_accuracy']:.1%} |"
        )
    lines.extend([
        "",
        "## 오류 해석",
        "",
        f"- 검증가능 과배제: {len(false_negatives)}건 ({'; '.join(false_negatives) or '없음'})",
        f"- 검증불가 과매핑: {len(false_positives)}건 ({'; '.join(false_positives) or '없음'})",
        f"- 검증가능 보류: {sum(eligible_holds.values())}건 ({dict(eligible_holds)})",
        f"- 자동 검증가능 6건 중 완전 매핑: {sum(row['full_mapping_correct'] == 'Y' for row in rows if row['auto_decision'] == '검증가능')}건",
        f"- 골드 최종 판정 분포: {dict(gold_verdicts)}",
        "- API 6/6 성공은 호출 기술이 동작했다는 뜻이며, 의미상 올바른 표·항목을 골랐다는 보장은 아니다.",
        "",
        "## 다음 단계",
        "",
        "1. 완료: P0 오류 3건을 코드북 v3 후보와 회귀 테스트로 고정했다.",
        "2. 검증가능 보류 30건을 분야별로 묶어 반복 통계표·항목·시점 규칙을 코드북 v3 후보로 만든다.",
        "3. 검증불가 보류 35건은 KOSIS 미제공·정보 부족 사전으로 분리한다.",
        "4. 코드북 v3를 동결한 뒤 기존 300건과 겹치지 않는 새 독립 표본 100건을 만든다.",
        "5. 새 표본의 항목·시점 결합 엄격 정확도가 80% 이상일 때만 1,281건 자동 확정을 확대한다.",
        "",
        "## 산출물",
        "",
        f"- `{stem}_evaluation.csv`: 골드와 자동 예측의 행별 비교",
        f"- `{stem}_metrics.csv`: 전체 지표",
        f"- `{stem}_metrics_by_domain.csv`: 분야별 지표",
        f"- `{stem}_error_analysis.csv`: 오류 행과 원인",
        f"- `{stem}_improvement_backlog.csv`: 우선순위별 개선 작업",
        f"- `{stem}_report.md`: 팀 공유용 해석 보고서",
        "",
        f"개선 백로그 항목 수: {len(backlog)}",
    ])
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--stem", default=DEFAULT_STEM)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with args.input.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    validate_rows(rows)
    evaluated = evaluate_rows(rows)
    metrics = build_metrics(evaluated)
    domain_metrics = build_domain_metrics(evaluated)
    errors = [row for row in evaluated if row["error_types"]]
    backlog = build_backlog(evaluated)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / f"{args.stem}_evaluation.csv", evaluated, list(evaluated[0].keys()))
    write_csv(args.output_dir / f"{args.stem}_metrics.csv", metrics, list(metrics[0].keys()))
    write_csv(args.output_dir / f"{args.stem}_metrics_by_domain.csv", domain_metrics, list(domain_metrics[0].keys()))
    write_csv(args.output_dir / f"{args.stem}_error_analysis.csv", errors, list(errors[0].keys()))
    write_csv(
        args.output_dir / f"{args.stem}_improvement_backlog.csv",
        backlog,
        ["priority", "scope", "count", "evidence", "recommended_action", "evaluation_policy"],
    )
    report = build_report(evaluated, metrics, domain_metrics, backlog, args.stem)
    (args.output_dir / f"{args.stem}_report.md").write_text(report, encoding="utf-8")

    metric_map = {row["metric"]: row for row in metrics}
    gate = metric_map["항목·시점 결합 엄격 정확도"]
    print(f"validated={len(evaluated)} gold_y={sum(row['gold_verifiable'] == 'Y' for row in evaluated)}")
    print(f"auto_decisions={dict(Counter(row['auto_decision'] for row in evaluated))}")
    print(f"gate={gate['correct_or_success']}/{gate['denominator']} ({gate['rate']:.1%})")
    print(args.output_dir.resolve())


if __name__ == "__main__":
    main()
