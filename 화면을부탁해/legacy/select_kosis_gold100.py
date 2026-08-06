import csv
import hashlib
from collections import Counter, defaultdict
from pathlib import Path


REPO = Path(__file__).resolve().parent
INPUT = REPO / "outputs/bteam_review/final_verified_filled_2001_remapped_v6.csv"
OUTPUT = REPO / "outputs/bteam_gold/gold100_selection.csv"
DOMAINS = ("물가", "고용", "무역", "인구", "소매")
ANCHOR_LIMIT = {"물가": 4, "고용": 4, "무역": 2, "인구": 1, "소매": 1}


def final_status(row):
    return (
        row.get("remap_final_status")
        or row.get("manual_final_status")
        or row.get("audit_status")
        or row.get("refined_final_status")
        or ""
    )


def classify_domain(row):
    table = row.get("tbl_id", "")
    metric = row.get("metric", "")
    text = row.get("claim_text", "")
    if table.startswith("DT_1R11") or metric == "무역지표":
        return "무역"
    if table.startswith("DT_1DA") or metric == "고용지표":
        return "고용"
    if "B8000" in table or metric == "인구지표":
        return "인구"
    if table in {"DT_1K41012", "DT_1K41018"} or metric == "판매·생산량" or "소매" in text:
        return "소매"
    if table.startswith("DT_1J22") or metric == "물가지표":
        return "물가"
    return "기타"


def bucket(row):
    status = final_status(row)
    if "확정일치" in status:
        return "확정근거"
    if "정확시점불일치" in status:
        return "정확시점22"
    if "증감률불일치" in status:
        return "증감률재검토"
    if "수준값불일치" in status:
        return "수준값재검토"
    if status.startswith("판단불가"):
        return "판단불가"
    return "기타"


def rank(row, salt):
    value = f"kosis-gold-v1|{salt}|{row.get('claim_id', '')}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def select():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with INPUT.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    domain_rows = defaultdict(list)
    for row in rows:
        row = dict(row)
        row["gold_domain"] = classify_domain(row)
        row["source_status"] = final_status(row)
        row["selection_bucket"] = bucket(row)
        if row["gold_domain"] in DOMAINS:
            domain_rows[row["gold_domain"]].append(row)

    selected = []
    selected_ids = set()
    seen_text = set()

    def add(row, reason, allow_duplicate=False):
        if row["claim_id"] in selected_ids:
            return False
        normalized_text = " ".join((row.get("claim_text") or "").split())
        if not allow_duplicate and normalized_text in seen_text:
            return False
        out = dict(row)
        out["selection_reason"] = reason
        selected.append(out)
        selected_ids.add(row["claim_id"])
        seen_text.add(normalized_text)
        return True

    for domain in DOMAINS:
        exact = [row for row in domain_rows[domain] if row["selection_bucket"] == "정확시점22"]
        for row in sorted(exact, key=lambda item: item["claim_id"]):
            add(row, "기존 정확시점 불일치 22건 포함", allow_duplicate=True)

    for domain in DOMAINS:
        anchors = [row for row in domain_rows[domain] if row["selection_bucket"] == "확정근거"]
        anchors.sort(key=lambda item: rank(item, f"anchor-{domain}"))
        added = 0
        for row in anchors:
            if add(row, "기존 수동확정 근거 앵커"):
                added += 1
            if added >= ANCHOR_LIMIT[domain]:
                break

    pattern = ["증감률재검토", "수준값재검토", "판단불가"]
    for domain in DOMAINS:
        current = sum(row["gold_domain"] == domain for row in selected)
        pools = {}
        for group in pattern:
            pool = [
                row for row in domain_rows[domain]
                if row["selection_bucket"] == group and row["claim_id"] not in selected_ids
            ]
            pool.sort(key=lambda item: rank(item, f"sample-{domain}-{group}"))
            pools[group] = pool
        positions = Counter()
        turn = 0
        while current < 20:
            group = pattern[turn % len(pattern)]
            turn += 1
            pool = pools[group]
            while positions[group] < len(pool):
                candidate = pool[positions[group]]
                positions[group] += 1
                if add(candidate, f"층화표본:{group}"):
                    current += 1
                    break
            else:
                fallback = [
                    row for row in domain_rows[domain]
                    if row["claim_id"] not in selected_ids
                ]
                fallback.sort(key=lambda item: rank(item, f"fallback-{domain}"))
                if not fallback:
                    raise RuntimeError(f"{domain} 분야에서 20건을 확보하지 못했습니다")
                for candidate in fallback:
                    if add(candidate, "층화표본:보충"):
                        current += 1
                        break

    order = {domain: index for index, domain in enumerate(DOMAINS)}
    selected.sort(key=lambda row: (order[row["gold_domain"]], row["claim_id"]))
    for index, row in enumerate(selected, start=1):
        row["gold_no"] = index

    fields = [
        "gold_no", "gold_domain", "selection_reason", "selection_bucket", "source_status",
        "claim_id", "article_id", "title", "date", "url", "claim_text", "metric",
        "org_id", "tbl_id", "obj_l1", "obj_l2", "itm_id", "prd_se",
        "refined_claim_type", "refined_claim_number", "actual_period", "actual_prev_period",
        "refined_actual_number", "refined_verdict", "api_error", "reviewer_note",
        "manual_kosis_evidence", "remap_kosis_evidence",
    ]
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(selected)

    print(f"selected={len(selected)}")
    print("domains=", dict(Counter(row["gold_domain"] for row in selected)))
    print("buckets=", dict(Counter(row["selection_bucket"] for row in selected)))
    print("reasons=", dict(Counter(row["selection_reason"] for row in selected)))
    print(f"output={OUTPUT.resolve()}")


if __name__ == "__main__":
    select()
