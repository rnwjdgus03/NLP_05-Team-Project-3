"""Rebuild claim-level article context after broad span detection.

Every claim receives the same article lead context plus a claim-local window
and a small set of related sentences from elsewhere in the same article.
Sentence IDs are retained so every context fragment remains auditable.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import OrderedDict
from pathlib import Path
from typing import Iterable


CONTEXT_COLUMNS = [
    "article_context",
    "lead_paragraph",
    "lead_context_source",
    "major_target_hints",
    "local_context",
    "antecedent_context",
    "context_sentence_ids",
    "context_version",
]
CONTEXT_VERSION = "claim-context-v2.0"
TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")
TIME_RE = re.compile(
    r"(?:19|20)\d{2}(?:년)?|\d{1,2}월|전년|지난해|작년|올해|"
    r"같은\s*기간|이\s*기간|전월|전분기|전년\s*동월"
)
REFERENCE_RE = re.compile(
    r"같은\s*기간|이\s*기간|해당|당시|이들|그중|전년|지난해|작년|올해|반면"
)
STOPWORDS = {
    "것으로",
    "대해",
    "대한",
    "관련",
    "따르면",
    "했다",
    "있다",
    "없다",
    "된다",
    "이번",
    "현재",
    "지난",
    "기자",
    "뉴스",
    "정부",
    "관련해",
    "통해",
    "위해",
    "가운데",
    "인상",
    "증가",
    "감소",
    "확대",
    "축소",
    "최대",
    "최소",
    "이상",
    "이하",
    "크게",
    "하염없이",
}
KOREAN_PARTICLES = (
    "으로",
    "에서",
    "에게",
    "까지",
    "부터",
    "보다",
    "처럼",
    "의",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "에",
    "로",
    "와",
    "과",
    "도",
    "만",
)
PREDICATE_ENDINGS = (
    "했다",
    "됐다",
    "한다",
    "된다",
    "있다",
    "없다",
    "밝혔다",
    "나타났다",
    "올랐다",
    "내렸다",
    "늘었다",
    "줄었다",
    "증가했다",
    "감소했다",
    "잃고",
    "기다리던",
)


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def parse_json_ids(value: str) -> list[str]:
    try:
        result = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item).strip() for item in result] if isinstance(result, list) else []


def tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in TOKEN_RE.findall(str(text or ""))
        if token.lower() not in STOPWORDS
    }


def normalize_target_token(token: str) -> str:
    value = token.lower()
    if any(character.isdigit() for character in value):
        return ""
    if value in STOPWORDS or value.endswith(PREDICATE_ENDINGS):
        return ""
    if re.fullmatch(r"[가-힣]+", value):
        for particle in KOREAN_PARTICLES:
            if value.endswith(particle) and len(value) - len(particle) >= 2:
                value = value[: -len(particle)]
                break
    if len(value) < 2 or value in STOPWORDS:
        return ""
    return value


def format_rows(rows: Iterable[dict[str, str]]) -> str:
    return "\n".join(
        f"[{str(row.get('claim_id', '')).strip()}] "
        f"{str(row.get('claim_text', '')).strip()}"
        for row in rows
    )


def lead_rows_for_article(
    rows: list[dict[str, str]], fallback_sentences: int
) -> tuple[list[dict[str, str]], str]:
    if not rows:
        return [], "missing"
    first_paragraph = str(rows[0].get("paragraph_id", "") or "").strip()
    paragraph_count = str(rows[0].get("paragraph_count", "") or "").strip()
    if first_paragraph and paragraph_count not in {"", "0", "1"}:
        selected = [
            row
            for row in rows
            if str(row.get("paragraph_id", "") or "").strip() == first_paragraph
        ]
        return selected[:fallback_sentences], "first_paragraph"
    return rows[:fallback_sentences], "fallback_first_sentences"


def major_target_hints(
    title: str,
    lead_text: str,
    article_rows: list[dict[str, str]],
    limit: int = 8,
) -> str:
    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    order = 0

    def add(text: str, weight: float) -> None:
        nonlocal order
        for token in TOKEN_RE.findall(text or ""):
            normalized = normalize_target_token(token)
            if not normalized:
                continue
            scores[normalized] = scores.get(normalized, 0.0) + weight
            first_seen.setdefault(normalized, order)
            order += 1

    add(title, 5.0)
    add(lead_text, 2.0)
    for row in article_rows:
        add(str(row.get("claim_text", "") or ""), 0.25)
    ranked = sorted(
        scores,
        key=lambda item: (-scores[item], first_seen[item], item),
    )
    return "; ".join(ranked[:limit])


def related_indices(
    rows: list[dict[str, str]],
    claim_text: str,
    excluded: set[int],
    start: int,
    limit: int,
) -> list[int]:
    claim_tokens = tokens(claim_text)
    needs_reference = bool(REFERENCE_RE.search(claim_text or ""))
    scored: list[tuple[float, int]] = []
    for index, row in enumerate(rows):
        if index in excluded:
            continue
        sentence = str(row.get("claim_text", "") or "")
        overlap = len(claim_tokens & tokens(sentence))
        score = overlap * 5.0
        if TIME_RE.search(sentence):
            score += 4.0 if needs_reference else 1.0
        if index < start:
            score += 1.5
        score -= abs(index - start) * 0.05
        if score > 0:
            scored.append((score, index))

    scored.sort(key=lambda item: (-item[0], abs(item[1] - start), item[1]))
    selected = [index for _, index in scored[:limit]]
    if not selected and needs_reference:
        selected = [
            index
            for index in range(start - 1, -1, -1)
            if index not in excluded
        ][:limit]
    return sorted(selected)


def build_context_rows(
    sentence_rows: Iterable[dict[str, str]],
    span_rows: Iterable[dict[str, str]],
    local_window: int = 3,
    related_limit: int = 3,
    lead_sentences: int = 3,
    previous_window: int | None = None,
    next_window: int | None = None,
) -> list[dict[str, str]]:
    previous_window = local_window if previous_window is None else previous_window
    next_window = local_window if next_window is None else next_window
    if (
        local_window < 0
        or previous_window < 0
        or next_window < 0
        or related_limit < 0
        or lead_sentences < 1
    ):
        raise ValueError("invalid context window settings")

    articles: OrderedDict[str, list[dict[str, str]]] = OrderedDict()
    for row in sentence_rows:
        article_id = str(row.get("article_id", "") or "").strip()
        if article_id:
            articles.setdefault(article_id, []).append(row)

    output: list[dict[str, str]] = []
    for source in span_rows:
        article_id = str(source.get("article_id", "") or "").strip()
        rows = articles.get(article_id, [])
        by_id = {
            str(row.get("claim_id", "") or "").strip(): index
            for index, row in enumerate(rows)
        }
        evidence_ids = parse_json_ids(source.get("evidence_sentence_ids", ""))
        evidence_indices = [by_id[item] for item in evidence_ids if item in by_id]

        if evidence_indices:
            start, end = min(evidence_indices), max(evidence_indices)
        else:
            start = end = 0

        local_start = max(0, start - previous_window)
        local_end = min(len(rows), end + next_window + 1)
        local_indices = set(range(local_start, local_end))
        related = related_indices(
            rows,
            str(source.get("claim_text", "") or ""),
            local_indices,
            start,
            related_limit,
        )
        lead_rows, lead_source = lead_rows_for_article(rows, lead_sentences)
        lead_ids = [
            str(row.get("claim_id", "") or "").strip() for row in lead_rows
        ]
        lead = [by_id[item] for item in lead_ids if item in by_id]
        title = str(source.get("title", "") or "").strip()
        lead_paragraph = format_rows(lead_rows)
        lead_plain_text = " ".join(
            str(row.get("claim_text", "") or "").strip() for row in lead_rows
        )
        target_hints = major_target_hints(title, lead_plain_text, rows)
        article_context = "\n".join(
            [
                f"[title] {title}",
                f"[publication_date] {str(source.get('date', '') or '-').strip()}",
                f"[lead_source] {lead_source}",
                f"[major_target_hints] {target_hints or '-'}",
                lead_paragraph,
            ]
        ).strip()

        row = dict(source)
        row.update(
            {
                "article_context": article_context,
                "lead_paragraph": lead_paragraph,
                "lead_context_source": lead_source,
                "major_target_hints": target_hints,
                "local_context": format_rows(rows[local_start:local_end]),
                "antecedent_context": format_rows(rows[index] for index in related),
                "context_sentence_ids": json.dumps(
                    {
                        "evidence": evidence_ids,
                        "lead": [
                            str(rows[index].get("claim_id", "") or "").strip()
                            for index in lead
                        ],
                        "local": [
                            str(rows[index].get("claim_id", "") or "").strip()
                            for index in range(local_start, local_end)
                        ],
                        "antecedent": [
                            str(rows[index].get("claim_id", "") or "").strip()
                            for index in related
                        ],
                    },
                    ensure_ascii=False,
                ),
                "context_version": (
                    f"{CONTEXT_VERSION}-prev{previous_window}-next{next_window}"
                    f"-related{related_limit}-lead{lead_sentences}"
                ),
            }
        )
        output.append(row)
    return output


def write_csv(path: Path, rows: Iterable[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Attach article-shared and claim-local context to claim spans."
    )
    parser.add_argument("--sentences", required=True, type=Path)
    parser.add_argument("--spans", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--local-window", type=int, default=3)
    parser.add_argument(
        "--previous-window",
        type=int,
        help="Number of sentences before the evidence span. Defaults to --local-window.",
    )
    parser.add_argument(
        "--next-window",
        type=int,
        help="Number of sentences after the evidence span. Defaults to --local-window.",
    )
    parser.add_argument("--related-limit", type=int, default=3)
    parser.add_argument("--lead-sentences", type=int, default=3)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.output.exists() and not args.overwrite:
        raise SystemExit(f"output already exists: {args.output} (use --overwrite)")
    sentence_rows, sentence_fields = read_csv(args.sentences)
    span_rows, span_fields = read_csv(args.spans)
    if not {"article_id", "claim_id", "claim_text"} <= set(sentence_fields):
        raise SystemExit("sentence CSV is missing article_id, claim_id, or claim_text")
    if not {"article_id", "claim_id", "claim_text"} <= set(span_fields):
        raise SystemExit("span CSV is missing article_id, claim_id, or claim_text")
    try:
        output = build_context_rows(
            sentence_rows,
            span_rows,
            local_window=args.local_window,
            related_limit=args.related_limit,
            lead_sentences=args.lead_sentences,
            previous_window=args.previous_window,
            next_window=args.next_window,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    fields = [*span_fields, *[field for field in CONTEXT_COLUMNS if field not in span_fields]]
    write_csv(args.output, output, fields)
    print(
        f"created={args.output} claims={len(output)} "
        f"articles={len({row.get('article_id', '') for row in output})}"
    )


if __name__ == "__main__":
    main()
