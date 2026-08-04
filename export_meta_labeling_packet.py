#!/usr/bin/env python3
"""파이프라인 후보가 아니라 **KOSIS 메타 전체**에서 좌표 후보를 뽑아 문제지를 만든다.

왜 이렇게 해야 하나
-------------------
지금 골드 12건은 파이프라인이 찾아온 후보 중에서 만들어졌다.
그러면 시스템이 못 찾은 좌표는 골드에 절대 들어갈 수 없고,
그런 골드로 recall 을 재면 '찾은 것 중에 정답이 있었나'를 재는 셈이라 과대평가된다.

실측(2026-08-02): 라벨 문제지 12건 중 11건에 정답 후보가 아예 없었다.
예) '석유화학 수출액' 의 후보가 간장·경석·가죽·석면섬유였다.
    같은 표(품목별 수출액, 수입액) 안에 석유화학이 있는데도 후보로 안 올라왔다.

**남는 편향**: 이 메타 인덱스는 상류 표 검색이 뽑은 표들로 만들어졌다.
표 자체가 후보에 없었으면 여기서도 못 찾는다. 좌표 단계 편향은 없앴지만
표 단계 편향은 남아 있고, 골드 manifest 에 그 사실을 적어야 한다.

사용법:
  python export_meta_labeling_packet.py \
    --measurements evaluation_set_v3.csv \
    --meta-index ..._kosis_meta_index.csv \
    --table-candidates ..._kosis_table_candidates.csv \
    --exclude-gold gold_confirmed_v2.csv \
    --output meta_label_batch1.md --limit 10 --offset 0
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from kosis_meta_coordinates import group_meta_rows, read_csv_rows
from kosis_validate_mapping_candidates import AGGREGATE_OBJ_NAMES

AGGREGATE = {re.sub(r"[^0-9A-Za-z가-힣]", "", n).lower() for n in AGGREGATE_OBJ_NAMES}
STOPWORDS = {"증감률", "증가율", "감소율", "비율", "수", "액", "총", "전체", "현황", "규모"}


def text(value) -> str:
    value = str(value or "").strip()
    return "" if value.lower() in {"nan", "none"} else value


def normalize(value) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", str(value or "")).lower()


def keywords(*values) -> list[str]:
    """주장에서 뽑은 검색어. 2자 이상 한글·영문 토큰만 쓴다."""
    tokens: list[str] = []
    for value in values:
        for token in re.findall(r"[가-힣A-Za-z]{2,}", text(value)):
            lowered = token.lower()
            if lowered not in STOPWORDS and lowered not in tokens:
                tokens.append(lowered)
    return tokens


def overlap(name: str, tokens) -> int:
    """이름에 검색어가 몇 개나 들어 있나. 긴 검색어에 가중치를 준다."""
    normalized = normalize(name)
    return sum(len(token) for token in tokens if normalize(token) in normalized)


def is_aggregate(name) -> bool:
    return normalize(name) in AGGREGATE


def rank_coordinates(table, item_tokens, all_tokens, per_table=4):
    """표 하나에서 그럴듯한 (항목, 분류1) 조합을 뽑는다.

    집계값은 항상 하나 남긴다 — 주장이 대상을 특정하지 않으면 그게 정답이기 때문이다.
    """
    items = sorted(table["items"],
                   key=lambda i: -overlap(i.get("name"), all_tokens))[:3]
    axis = table["axes"].get(1)
    values = list(axis["values"]) if axis else []
    scored = sorted(values, key=lambda v: -overlap(v.get("name"), item_tokens))
    best = [v for v in scored if overlap(v.get("name"), item_tokens) > 0][:3]
    aggregates = [v for v in values if is_aggregate(v.get("name"))][:1]
    chosen = best + [v for v in aggregates if v not in best]
    if not chosen:
        chosen = [None]

    out = []
    for item in items or [None]:
        for value in chosen:
            out.append((item, value))
            if len(out) >= per_table:
                return out
    return out


def describe(table, item, value) -> str:
    parts = [f"표 `{table['tbl_id']}` {table['tbl_name']}"]
    if item:
        unit = text(item.get("unit"))
        parts.append(f"항목 {item.get('name')}" + (f" [{unit}]" if unit else " [단위 미상]"))
    if value:
        parts.append(f"분류1={value.get('name')}")
    else:
        parts.append("분류축 없음")
    return " · ".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--measurements", required=True)
    ap.add_argument("--meta-index", required=True)
    ap.add_argument("--table-candidates", default="")
    ap.add_argument("--exclude-gold", default="")
    ap.add_argument("--output", required=True)
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--tables-per-claim", type=int, default=3)
    args = ap.parse_args()

    tables = group_meta_rows(read_csv_rows(args.meta_index))
    labeled = {text(r.get("claim_measurement_id"))
               for r in read_csv_rows(args.exclude_gold)} if args.exclude_gold else set()

    allowed: dict[str, set[str]] = {}
    if args.table_candidates:
        for row in read_csv_rows(args.table_candidates):
            mid = text(row.get("claim_measurement_id"))
            allowed.setdefault(mid, set()).add(text(row.get("tbl_id")))

    claims = [r for r in read_csv_rows(args.measurements)
              if text(r.get("claim_measurement_id")) not in labeled]
    claims.sort(key=lambda r: text(r.get("claim_measurement_id")))
    batch = claims[args.offset:args.offset + args.limit]

    lines = [
        "# 좌표 라벨링 — 메타 인덱스 전체에서 뽑은 후보",
        "",
        "파이프라인이 실제로 가져온 후보가 아니라 **KOSIS 메타에 존재하는 좌표**에서 뽑았다.",
        "따라서 '시스템이 못 찾았지만 정답인 좌표'도 여기 나온다.",
        "",
        "맞는 후보가 없으면 `없음`, 판단이 불가능하면 `모름`.",
        "",
        "---",
        "",
    ]
    key_rows = []
    for index, claim in enumerate(batch, start=args.offset + 1):
        mid = text(claim.get("claim_measurement_id"))
        item_tokens = keywords(claim.get("industry_or_item"), claim.get("measurement_item"))
        all_tokens = keywords(claim.get("indicator"), claim.get("measurement_indicator"),
                              claim.get("industry_or_item"), claim.get("measurement_item"))
        pool = [t for key, t in tables.items()
                if not allowed.get(mid) or key[1] in allowed[mid]]
        ranked = sorted(pool, key=lambda t: -(overlap(t["tbl_name"], all_tokens)))
        ranked = ranked[:args.tables_per_claim]

        options = []
        for table in ranked:
            for item, value in rank_coordinates(table, item_tokens, all_tokens):
                options.append((table, item, value))
        options = options[:10]
        if not options:
            continue

        lines += [
            f"## 문제 {index}",
            "",
            f"> {text(claim.get('claim_text'))}",
            "",
            f"- 지표: {text(claim.get('indicator')) or '-'}",
            f"- 대상: {text(claim.get('industry_or_item')) or '(없음 — 총계로 봐야 함)'}",
            f"- 값: {text(claim.get('value'))} {text(claim.get('unit'))}",
            f"- 기간: {text(claim.get('period'))} ({text(claim.get('prd_se')) or '?'})",
            "",
            "후보:",
            "",
        ]
        for letter, (table, item, value) in zip("ABCDEFGHIJ", options):
            lines.append(f"- **{letter}.** {describe(table, item, value)}")
        lines += ["", f"답: `문제 {index} = ?`", "", "---", ""]

        key_rows.append({
            "question": index, "claim_measurement_id": mid,
            "options": " | ".join(
                f"{letter}={table['tbl_id']}/{(item or {}).get('code', '')}/{(value or {}).get('code', '')}"
                for letter, (table, item, value) in zip("ABCDEFGHIJ", options)),
        })

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text("\n".join(lines), encoding="utf-8")
    key_path = str(Path(args.output).with_suffix("")) + "_key.csv"
    with open(key_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(key_rows[0].keys()))
        writer.writeheader()
        writer.writerows(key_rows)

    print(f"라벨 대상 {len(claims)}건 중 {len(key_rows)}건 출제 "
          f"(offset={args.offset}, limit={args.limit})")
    print(f"문제지 → {args.output}")
    print(f"선택지 매핑 → {key_path}")
    print("\n※ 표 단계 편향은 남아 있다 — 상류 표 검색이 못 찾은 표는 메타에도 없다.")


if __name__ == "__main__":
    main()
