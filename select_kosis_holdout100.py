"""Select a leakage-resistant, balanced 100-claim holdout set."""

from __future__ import annotations

import csv
import hashlib
from collections import Counter, defaultdict
from pathlib import Path


REPO = Path(__file__).resolve().parent
INPUT = REPO / "outputs/bteam_review/final_verified_filled_2001_remapped_v6.csv"
GOLD = REPO / "outputs/bteam_gold/gold100_selection.csv"
OUTPUT = REPO / "outputs/bteam_holdout/holdout100_selection.csv"
DOMAINS = ("물가", "고용", "무역", "인구", "소매")
BUCKET_TARGET = {"증감률재검토": 7, "수준값재검토": 7, "판단불가": 6}


def final_status(row):
    return (
        row.get("remap_final_status")
        or row.get("manual_final_status")
        or row.get("audit_status")
        or row.get("refined_final_status")
        or ""
    )


def classify_domain(row):
    table = row.get("tbl_id", "") or ""
    metric = row.get("metric", "") or ""
    text = row.get("claim_text", "") or ""
    if table.startswith("DT_1R11") or metric == "무역지표":
        return "무역"
    if table.startswith("DT_1DA") or metric == "고용지표":
        return "고용"
    if "B8000" in table or metric == "인구지표":
        return "인구"
    if table in {"DT_1K41012", "DT_1K41018", "DT_1KC2020"} or metric == "판매·생산량" or "소매" in text:
        return "소매"
    if table.startswith("DT_1J22") or metric == "물가지표":
        return "물가"
    return "기타"


def bucket(row):
    status = final_status(row)
    if "증감률불일치" in status:
        return "증감률재검토"
    if "수준값불일치" in status:
        return "수준값재검토"
    if status.startswith("판단불가"):
        return "판단불가"
    return "기타"


def normalized(text):
    return " ".join((text or "").split())


def rank(row, salt):
    payload = f"kosis-holdout-v1|{salt}|{row.get('claim_id', '')}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def main():
    with GOLD.open(encoding="utf-8-sig", newline="") as handle:
        gold_rows = list(csv.DictReader(handle))
    gold_ids = {row["claim_id"] for row in gold_rows}
    gold_articles = {row.get("article_id", "") for row in gold_rows if row.get("article_id")}
    gold_texts = {normalized(row.get("claim_text", "")) for row in gold_rows}

    with INPUT.open(encoding="utf-8-sig", newline="") as handle:
        source_rows = list(csv.DictReader(handle))

    pools = defaultdict(lambda: defaultdict(list))
    for source in source_rows:
        if source.get("claim_id") in gold_ids:
            continue
        if source.get("article_id") in gold_articles:
            continue
        if normalized(source.get("claim_text", "")) in gold_texts:
            continue
        row = dict(source)
        row["holdout_domain"] = classify_domain(row)
        row["selection_bucket"] = bucket(row)
        row["source_status"] = final_status(row)
        if row["holdout_domain"] in DOMAINS and row["selection_bucket"] in BUCKET_TARGET:
            pools[row["holdout_domain"]][row["selection_bucket"]].append(row)

    selected = []
    selected_ids = set()
    selected_texts = set()

    def add(row, reason):
        claim_id = row.get("claim_id", "")
        text = normalized(row.get("claim_text", ""))
        if claim_id in selected_ids or text in selected_texts:
            return False
        out = dict(row)
        out["selection_reason"] = reason
        selected.append(out)
        selected_ids.add(claim_id)
        selected_texts.add(text)
        return True

    for domain in DOMAINS:
        for bucket_name, target in BUCKET_TARGET.items():
            candidates = pools[domain][bucket_name]
            candidates.sort(key=lambda row: rank(row, f"{domain}-{bucket_name}"))
            added = 0
            for row in candidates:
                if add(row, f"독립층화:{bucket_name}"):
                    added += 1
                if added == target:
                    break

        domain_count = sum(row["holdout_domain"] == domain for row in selected)
        if domain_count < 20:
            fallback = []
            for candidates in pools[domain].values():
                fallback.extend(candidates)
            fallback.sort(key=lambda row: rank(row, f"{domain}-fallback"))
            for row in fallback:
                if add(row, "독립층화:보충"):
                    domain_count += 1
                if domain_count == 20:
                    break
        if domain_count != 20:
            raise RuntimeError(f"{domain} holdout 확보 실패: {domain_count}/20")

    domain_order = {domain: index for index, domain in enumerate(DOMAINS)}
    selected.sort(key=lambda row: (domain_order[row["holdout_domain"]], row["claim_id"]))
    for index, row in enumerate(selected, start=1):
        row["holdout_no"] = index

    fields = [
        "holdout_no", "holdout_domain", "selection_reason", "selection_bucket", "source_status",
        "claim_id", "article_id", "title", "date", "url", "prev_sentence", "claim_text", "next_sentence",
        "metric", "metric_all", "numbers", "units", "year", "region", "population",
        "org_id", "tbl_id", "obj_l1", "obj_l2", "itm_id", "prd_se",
        "refined_claim_type", "refined_claim_number", "actual_period", "actual_prev_period",
        "refined_actual_number", "refined_verdict", "api_error", "reviewer_note",
    ]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(selected)

    print(f"selected={len(selected)}")
    print("domains=", dict(Counter(row["holdout_domain"] for row in selected)))
    print("buckets=", dict(Counter(row["selection_bucket"] for row in selected)))
    print(f"excluded_gold_claims={len(gold_ids)} articles={len(gold_articles)}")
    print(OUTPUT.resolve())


if __name__ == "__main__":
    main()
