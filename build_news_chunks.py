"""Build overlapping article-local chunks from sentence-level news CSV.

The chunk stage keeps the original sentence IDs and article metadata so a
later claim-span detector can return exact evidence boundaries. Chunks never
cross article boundaries.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import OrderedDict
from pathlib import Path
from typing import Iterable

from build_claim_contexts import major_target_hints


OUTPUT_COLUMNS = [
    "chunk_id",
    "article_id",
    "title",
    "date",
    "url",
    "sentence_count",
    "sentence_ids",
    "sentences_json",
    "chunk_text",
    "prev_sentence",
    "next_sentence",
    "article_context",
    "article_context_sentence_ids",
    "lead_paragraph",
    "lead_context_source",
    "major_target_hints",
    "context_version",
]

CONTEXT_VERSION = "article-shared-v2.0"


def lead_rows_for_article(
    rows: list[dict[str, str]], fallback_sentences: int
) -> tuple[list[dict[str, str]], str]:
    first_paragraph = str(rows[0].get("paragraph_id", "") or "").strip()
    paragraph_count = str(rows[0].get("paragraph_count", "") or "").strip()
    if first_paragraph:
        selected = [
            row
            for row in rows
            if str(row.get("paragraph_id", "") or "").strip() == first_paragraph
        ]
        if paragraph_count not in {"", "0", "1"}:
            return selected[:fallback_sentences], "first_paragraph"
    return rows[:fallback_sentences], "fallback_first_sentences"


def chunk_ranges(
    sentence_count: int,
    chunk_size: int = 8,
    overlap: int = 2,
    min_chunk_size: int = 5,
) -> list[tuple[int, int]]:
    """Return half-open overlapping windows with a non-tiny final chunk."""
    if sentence_count <= 0:
        return []
    if not 5 <= chunk_size <= 8:
        raise ValueError("chunk_size must be between 5 and 8")
    if not 0 < min_chunk_size <= chunk_size:
        raise ValueError("min_chunk_size must be between 1 and chunk_size")
    if not 0 <= overlap < chunk_size:
        raise ValueError("overlap must be between 0 and chunk_size - 1")
    if sentence_count <= chunk_size:
        return [(0, sentence_count)]

    step = chunk_size - overlap
    starts = list(range(0, sentence_count, step))
    ranges: list[tuple[int, int]] = []
    for start in starts:
        end = min(start + chunk_size, sentence_count)
        if end - start < min_chunk_size:
            start = max(0, sentence_count - chunk_size)
            end = sentence_count
        window = (start, end)
        if window not in ranges:
            ranges.append(window)
        if end == sentence_count:
            break
    return ranges


def build_chunks(
    sentence_rows: Iterable[dict[str, str]],
    chunk_size: int = 8,
    overlap: int = 2,
    min_chunk_size: int = 5,
    lead_sentences: int = 3,
) -> list[dict[str, str]]:
    if lead_sentences < 1:
        raise ValueError("lead_sentences must be at least 1")
    articles: OrderedDict[str, list[dict[str, str]]] = OrderedDict()
    for row in sentence_rows:
        article_id = str(row.get("article_id", "") or "").strip()
        claim_id = str(row.get("claim_id", "") or "").strip()
        claim_text = str(row.get("claim_text", "") or "").strip()
        if not article_id or not claim_id or not claim_text:
            continue
        articles.setdefault(article_id, []).append(row)

    output: list[dict[str, str]] = []
    for article_id, rows in articles.items():
        lead_rows, lead_source = lead_rows_for_article(rows, lead_sentences)
        lead_ids = [str(row["claim_id"]).strip() for row in lead_rows]
        title = str(rows[0].get("title", "") or "").strip()
        date = str(rows[0].get("date", "") or "").strip()
        lead_paragraph = "\n".join(
            f"[{sentence_id}] {str(row.get('claim_text', '') or '').strip()}"
            for sentence_id, row in zip(lead_ids, lead_rows)
        )
        lead_plain_text = " ".join(
            str(row.get("claim_text", "") or "").strip() for row in lead_rows
        )
        target_hints = major_target_hints(title, lead_plain_text, rows)
        article_context = "\n".join(
            [
                f"[title] {title}",
                f"[publication_date] {date or '-'}",
                f"[lead_source] {lead_source}",
                f"[major_target_hints] {target_hints or '-'}",
                lead_paragraph,
            ]
        )
        for chunk_number, (start, end) in enumerate(
            chunk_ranges(len(rows), chunk_size, overlap, min_chunk_size),
            1,
        ):
            selected = rows[start:end]
            sentence_ids = [str(row["claim_id"]).strip() for row in selected]
            sentences = [str(row["claim_text"]).strip() for row in selected]
            first = selected[0]
            output.append(
                {
                    "chunk_id": f"{article_id}-CH{chunk_number:03d}",
                    "article_id": article_id,
                    "title": str(first.get("title", "") or "").strip(),
                    "date": str(first.get("date", "") or "").strip(),
                    "url": str(first.get("url", "") or "").strip(),
                    "sentence_count": str(len(selected)),
                    "sentence_ids": json.dumps(sentence_ids, ensure_ascii=False),
                    "sentences_json": json.dumps(sentences, ensure_ascii=False),
                    "chunk_text": "\n".join(
                        f"[{sentence_id}] {sentence}"
                        for sentence_id, sentence in zip(sentence_ids, sentences)
                    ),
                    "prev_sentence": (
                        str(rows[start - 1].get("claim_text", "") or "").strip()
                        if start > 0
                        else ""
                    ),
                    "next_sentence": (
                        str(rows[end].get("claim_text", "") or "").strip()
                        if end < len(rows)
                        else ""
                    ),
                    "article_context": article_context,
                    "article_context_sentence_ids": json.dumps(
                        lead_ids, ensure_ascii=False
                    ),
                    "lead_paragraph": lead_paragraph,
                    "lead_context_source": lead_source,
                    "major_target_hints": target_hints,
                    "context_version": CONTEXT_VERSION,
                }
            )
    return output


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"article_id", "claim_id", "claim_text"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"missing required columns: {sorted(missing)}")
        return list(reader)


def write_csv(path: Path, rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build overlapping 5-8 sentence chunks without crossing articles."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--chunk-size", type=int, default=8)
    parser.add_argument("--overlap", type=int, default=2)
    parser.add_argument("--min-chunk-size", type=int, default=5)
    parser.add_argument("--lead-sentences", type=int, default=3)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.input.is_file():
        raise SystemExit(f"input CSV not found: {args.input}")
    if args.output.exists() and not args.overwrite:
        raise SystemExit(f"output already exists: {args.output} (use --overwrite)")
    try:
        rows = read_csv(args.input)
        chunks = build_chunks(
            rows,
            chunk_size=args.chunk_size,
            overlap=args.overlap,
            min_chunk_size=args.min_chunk_size,
            lead_sentences=args.lead_sentences,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    write_csv(args.output, chunks)
    article_count = len({row["article_id"] for row in chunks})
    print(
        f"created={args.output} articles={article_count} "
        f"sentences={len(rows)} chunks={len(chunks)}"
    )


if __name__ == "__main__":
    main()
