#!/usr/bin/env python3
"""표 라벨링 문제지 — 우리 후보와 공식검색을 **섞고 출처를 가린다** (2026-08-04).

## 왜 이렇게 만드는가

독립 골드를 만들려는데, 우리 후보만 보여주면 그 골드는 다시 순환이 된다.
그래서 두 출처를 합집합으로 놓고 **어디서 왔는지 숨긴다.**

    우리 후보 TOP5  +  공식 통합검색 TOP5   →  섞어서 A, B, C...

출처를 보이면 라벨하는 쪽이 무의식적으로 한쪽에 기운다.
사람이든 LLM이든 마찬가지다. 채점 뒤에 `_key.csv` 로 출처를 되살린다.

실측 근거: 우리 후보 885개와 공식검색 793개가 **11개만 겹쳤다.**
둘 중 하나가 크게 틀렸다는 뜻인데, 라벨 없이는 어느 쪽인지 모른다.

## 규칙

- 정답이 여럿일 수 있다(같은 통계가 여러 표에 수록). `A,C` 처럼 쓴다.
- 맞는 표가 없으면 `없음`, 판단이 불가능하면 `모름`.
- 섞는 순서는 `claim_measurement_id` 로 결정한다. **다시 만들어도 같은 순서**가 나온다.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import random
from pathlib import Path


def read(path: Path) -> list[dict]:
    if not path or not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def nz(value) -> str:
    return str(value or "").strip()


def rank_of(row) -> int:
    for key in ("candidate_rank", "search_rank", "table_rank", "rank"):
        raw = nz(row.get(key))
        if raw.isdigit():
            return int(raw)
    return 10**6


def group(rows) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for row in rows:
        key = nz(row.get("claim_measurement_id"))
        if key:
            out.setdefault(key, []).append(row)
    for items in out.values():
        items.sort(key=rank_of)
    return out


def take(rows, limit, source) -> list[dict]:
    picked, seen = [], set()
    for row in rows:
        tbl = nz(row.get("tbl_id"))
        if not tbl or tbl in seen:
            continue
        seen.add(tbl)
        picked.append({
            "tbl_id": tbl,
            "org_id": nz(row.get("org_id")),
            "tbl_name": nz(row.get("tbl_name")),
            "stat_name": nz(row.get("stat_name")),
            "source": source,
            "source_rank": rank_of(row),
        })
        if len(picked) >= limit:
            break
    return picked


def shuffled(options, key) -> list[dict]:
    """섞되 재현 가능하게. 같은 문제지를 다시 만들어도 순서가 같아야 한다."""
    seed = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16)
    out = list(options)
    random.Random(seed).shuffle(out)
    return out


LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--claims", required=True, type=Path)
    parser.add_argument("--ours", required=True, type=Path,
                        help="우리 표 후보 (05_..._table_candidates.csv)")
    parser.add_argument("--official", type=Path, help="공식검색 후보")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--key-output", type=Path)
    parser.add_argument("--per-source", type=int, default=5)
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()

    claims = read(args.claims)
    ours = group(read(args.ours))
    official = group(read(args.official)) if args.official else {}

    seen: set[str] = set()
    unique = []
    for claim in claims:
        key = nz(claim.get("claim_measurement_id"))
        if key and key not in seen:
            seen.add(key)
            unique.append(claim)
    batch = unique[args.offset:args.offset + args.limit]

    lines = ["# 표 라벨링 — 이 주장을 확인할 수 있는 통계표는?", "",
             "후보는 **두 출처를 섞었고 어디서 왔는지 가렸다.**",
             "출처를 보이면 한쪽에 기울기 때문이다.", "",
             "- 정답이 여럿이면 `A,C` 처럼 쓴다 (같은 통계가 여러 표에 수록될 수 있다)",
             "- 맞는 표가 없으면 `없음`, 판단이 불가능하면 `모름`",
             "- **표 이름만 보고 고른다.** 값이 맞는지는 다음 단계에서 본다", ""]
    key_rows = []

    for number, claim in enumerate(batch, start=1):
        mid = nz(claim.get("claim_measurement_id"))
        options = take(ours.get(mid, []), args.per_source, "ours")
        have = {opt["tbl_id"] for opt in options}
        for opt in take(official.get(mid, []), args.per_source, "official"):
            if opt["tbl_id"] not in have:
                options.append(opt)
        if not options:
            continue
        options = shuffled(options, mid)

        lines += ["---", "", f"## 문제 {number}", "",
                  f"> {nz(claim.get('claim_text'))[:220]}", "",
                  f"- 지표: {nz(claim.get('indicator')) or '(없음)'}",
                  f"- 대상: {nz(claim.get('industry_or_item')) or '(없음)'}",
                  f"- 값: {nz(claim.get('value'))} {nz(claim.get('unit'))}",
                  f"- 기간: {nz(claim.get('period'))} ({nz(claim.get('prd_se'))})", "",
                  "후보:", ""]
        for letter, opt in zip(LETTERS, options):
            extra = f" · {opt['stat_name']}" if opt["stat_name"] else ""
            lines.append(f"- **{letter}.** `{opt['tbl_id']}` {opt['tbl_name']}{extra}")
            key_rows.append({"question": number, "claim_measurement_id": mid,
                             "letter": letter, **opt})
        lines += ["", f"답: `문제 {number} = ?`", ""]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")

    key_path = args.key_output or args.output.with_name(args.output.stem + "_key.csv")
    with key_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "question", "claim_measurement_id", "letter", "tbl_id", "org_id",
            "tbl_name", "stat_name", "source", "source_rank"])
        writer.writeheader()
        writer.writerows(key_rows)

    from collections import Counter
    counts = Counter(row["source"] for row in key_rows)
    print(f"문제 {len(batch)}개 (offset={args.offset}) → {args.output}")
    print(f"선택지 {len(key_rows)}개 | 출처 {dict(counts)}")
    print(f"정답표 → {key_path}")
    print("\n채점 뒤 출처별로 갈라 보면 어느 검색이 정답을 담고 있었는지 나온다.")


if __name__ == "__main__":
    main()
