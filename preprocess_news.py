"""Convert article-level news CSV data into sentence-level HCX input CSV.

Example:
    python preprocess_news.py \
        --input data/raw/news_articles.csv \
        --output data/inputs/news_sentences.csv

Only an article body column is required. Common Korean and English column
names are detected automatically, and explicit column names can be supplied
with the ``--*-col`` options when needed.
"""

from __future__ import annotations

import argparse
import csv
import html
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable


csv.field_size_limit(2**31 - 1)

OUTPUT_COLUMNS = [
    "claim_id",
    "article_id",
    "title",
    "date",
    "url",
    "claim_text",
    "prev_sentence",
    "next_sentence",
]

COLUMN_ALIASES = {
    "article_id": ["article_id", "articleId", "기사ID", "기사_id"],
    "title": ["title", "headline", "기사제목", "제목"],
    "date": [
        "date",
        "published_at",
        "publish_date",
        "작성일",
        "등록일",
        "기사작성일",
    ],
    "url": ["url", "URL", "link", "기사URL", "기사_url"],
    "body": [
        "body",
        "content",
        "article_body",
        "article_text",
        "text",
        "본문",
        "기사본문",
        "기사 본문 전체",
        "내용",
    ],
}

BLOCK_TAGS = {
    "article",
    "blockquote",
    "br",
    "div",
    "figcaption",
    "h1",
    "h2",
    "h3",
    "h4",
    "li",
    "p",
    "section",
}
SKIP_TAGS = {"script", "style", "noscript"}

NOISE_LINE_PATTERNS = [
    re.compile(r"^\s*(?:copyright|all rights reserved)\b", re.IGNORECASE),
    re.compile(r"^\s*[ⓒ©]"),
    re.compile(r"^\s*(?:무단\s*전재|재배포\s*금지)"),
    re.compile(r"^\s*(?:관련\s*기사|추천\s*기사|많이\s*본\s*뉴스)\s*$"),
    re.compile(r"^\s*(?:기사\s*제보|제보는)\b"),
    re.compile(
        r"^\s*(?:\[[^\]]*(?:기자|특파원)[^\]]*\]|"
        r"[가-힣]{2,5}\s*(?:기자|특파원))\s*(?:[=:]\s*)?"
        r"[\w.+-]+@[\w.-]+\s*$"
    ),
]

HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
SPACE_RE = re.compile(r"[\t\v\f ]+")
MULTI_NEWLINE_RE = re.compile(r"\n{2,}")
VISIBLE_TEXT_RE = re.compile(r"[0-9A-Za-z가-힣]")
SENTENCE_BOUNDARY_RE = re.compile(
    r"([.!?…]+[\"'”’」』)\]]*)\s+"
    r"(?=(?:[\"“‘「『(\[]*)[0-9A-Za-z가-힣▲△◆◇■□▶▷※])"
)
BYLINE_TIMESTAMP_RE = re.compile(
    r"(?P<author>[가-힣]{2,5})\s+(?:기자|특파원)\s+"
    r"입력\s+\d{4}\.\d{1,2}\.\d{1,2}\.?\s+\d{1,2}:\d{2}"
    r"(?:\s+업데이트\s+\d{4}\.\d{1,2}\.\d{1,2}\.?\s+\d{1,2}:\d{2})?"
)
LEADING_MEDIA_COUNT_RE = re.compile(
    r"^\s*\d{1,3}\s+(?=(?:[\"“‘'(\[]*)[가-힣A-Za-z])"
)
FOOTER_PATTERNS = [
    re.compile(r"\s+#\S+"),
    re.compile(r"\s+[가-힣]{2,5}\s+(?:기자|특파원)\s+구독수\b"),
    re.compile(r"\s+[가-힣]{2,5}\s+(?:기자|특파원)\s+(?:조선일보|[가-힣]+부|[가-힣]+팀)\b"),
    re.compile(r"\s+100자평\b"),
    re.compile(r"\s+AI\s+추천\b"),
    re.compile(r"\s+회사소개\s+기자채용\b"),
    re.compile(r"\s+(?:Copyright|COPYRIGHT)\s+조선일보\b"),
]


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self.skip_depth += 1
        elif not self.skip_depth and tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
        elif not self.skip_depth and tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


def _strip_html(value: str) -> str:
    if not HTML_TAG_RE.search(value):
        return html.unescape(value)
    parser = _HTMLTextExtractor()
    parser.feed(value)
    parser.close()
    return parser.text()


def clean_article_body(value: object, title: str = "") -> str:
    """Remove markup and common article footer noise without rewriting text."""
    text = "" if value is None else str(value)
    text = _strip_html(text)
    text = (
        text.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\u00a0", " ")
        .replace("\u200b", "")
        .replace("\ufeff", "")
    )

    # Some crawlers store the whole page before the article. The repeated title
    # and the following byline timestamp provide a stable start marker.
    normalized_title = SPACE_RE.sub(" ", title).strip()
    if normalized_title:
        title_position = text.find(normalized_title)
        if title_position >= 0:
            text = text[title_position + len(normalized_title):]
    byline = BYLINE_TIMESTAMP_RE.search(text[:1500])
    if byline:
        text = text[byline.end():]
        text = LEADING_MEDIA_COUNT_RE.sub("", text, count=1)

    footer_starts = [
        match.start()
        for pattern in FOOTER_PATTERNS
        if (match := pattern.search(text)) is not None
    ]
    if footer_starts:
        text = text[: min(footer_starts)]

    cleaned_lines = []
    for line in text.split("\n"):
        line = SPACE_RE.sub(" ", line).strip()
        if not line:
            cleaned_lines.append("")
            continue
        if any(pattern.search(line) for pattern in NOISE_LINE_PATTERNS):
            continue
        cleaned_lines.append(line)

    return MULTI_NEWLINE_RE.sub("\n", "\n".join(cleaned_lines)).strip()


def split_sentences_regex(text: str) -> list[str]:
    """Conservative fallback splitter for punctuated Korean news prose."""
    marked = text.replace("\n", "\u241e")
    marked = SENTENCE_BOUNDARY_RE.sub(lambda match: f"{match.group(1)}\u241e", marked)
    return [part.strip() for part in marked.split("\u241e") if part.strip()]


def get_sentence_splitter(name: str) -> tuple[Callable[[str], list[str]], str]:
    if name not in {"auto", "kss", "regex"}:
        raise ValueError(f"Unknown splitter: {name}")

    if name in {"auto", "kss"}:
        try:
            from kss import split_sentences as kss_split_sentences

            def split_with_kss(text: str) -> list[str]:
                return [str(sentence).strip() for sentence in kss_split_sentences(text)]

            return split_with_kss, "kss"
        except ImportError:
            if name == "kss":
                raise RuntimeError(
                    "The kss package is not installed. Run 'pip install kss' "
                    "or use '--splitter regex'."
                ) from None

    return split_sentences_regex, "regex"


def resolve_columns(
    fieldnames: Iterable[str], explicit: dict[str, str | None]
) -> dict[str, str | None]:
    fields = list(fieldnames)
    casefolded = {field.casefold(): field for field in fields}
    resolved: dict[str, str | None] = {}

    for standard_name, aliases in COLUMN_ALIASES.items():
        requested = explicit.get(standard_name)
        if requested:
            if requested not in fields:
                raise ValueError(
                    f"Column '{requested}' was not found. Available columns: {fields}"
                )
            resolved[standard_name] = requested
            continue

        resolved[standard_name] = next(
            (casefolded[alias.casefold()] for alias in aliases if alias.casefold() in casefolded),
            None,
        )

    if not resolved["body"]:
        raise ValueError(
            "Article body column was not found. Use --body-col. "
            f"Available columns: {fields}"
        )
    return resolved


def _cell(row: dict[str, str], column: str | None) -> str:
    if not column:
        return ""
    return str(row.get(column, "") or "").strip()


def preprocess_articles(
    articles: Iterable[dict[str, str]],
    columns: dict[str, str | None],
    splitter: Callable[[str], list[str]],
    min_chars: int = 2,
    article_prefix: str = "A",
    claim_prefix: str = "C",
    claim_id_style: str = "article",
) -> tuple[list[dict[str, str]], int]:
    output: list[dict[str, str]] = []
    empty_articles = 0
    claim_number = 1
    generated_article_number = 1

    for article in articles:
        title = _cell(article, columns.get("title"))
        body = clean_article_body(_cell(article, columns["body"]), title=title)
        sentences = [
            sentence
            for sentence in splitter(body)
            if len(sentence) >= min_chars and VISIBLE_TEXT_RE.search(sentence)
        ]
        if not sentences:
            empty_articles += 1
            continue

        source_article_id = _cell(article, columns.get("article_id"))
        article_id = source_article_id or f"{article_prefix}{generated_article_number:04d}"
        generated_article_number += 1
        date = _cell(article, columns.get("date"))
        url = _cell(article, columns.get("url"))

        for sentence_index, sentence in enumerate(sentences):
            if claim_id_style == "article":
                claim_id = f"{article_id}-{claim_prefix}{sentence_index + 1:03d}"
            else:
                claim_id = f"{claim_prefix}{claim_number:05d}"
            output.append(
                {
                    "claim_id": claim_id,
                    "article_id": article_id,
                    "title": title,
                    "date": date,
                    "url": url,
                    "claim_text": sentence,
                    "prev_sentence": sentences[sentence_index - 1]
                    if sentence_index > 0
                    else "",
                    "next_sentence": sentences[sentence_index + 1]
                    if sentence_index + 1 < len(sentences)
                    else "",
                }
            )
            claim_number += 1

    return output, empty_articles


def read_articles(
    path: Path, encoding: str, limit: int = 0
) -> tuple[list[dict[str, str]], list[str], str]:
    encodings = [encoding] if encoding != "auto" else ["utf-8-sig", "utf-8", "cp949"]
    last_error: UnicodeDecodeError | None = None

    for candidate in encodings:
        try:
            with path.open(encoding=candidate, newline="") as file:
                reader = csv.DictReader(file)
                if not reader.fieldnames:
                    raise ValueError("Input CSV has no header row.")
                rows = []
                for index, row in enumerate(reader):
                    if limit and index >= limit:
                        break
                    rows.append(row)
                return rows, list(reader.fieldnames), candidate
        except UnicodeDecodeError as error:
            last_error = error

    raise ValueError(f"Could not decode input CSV: {last_error}")


def write_sentences(path: Path, rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert article-level news CSV data to sentence-level HCX input."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--encoding", default="auto", choices=["auto", "utf-8-sig", "utf-8", "cp949"])
    parser.add_argument("--splitter", default="auto", choices=["auto", "kss", "regex"])
    parser.add_argument("--limit", type=int, default=0, help="Process only the first N articles.")
    parser.add_argument("--min-chars", type=int, default=2)
    parser.add_argument("--article-prefix", default="A")
    parser.add_argument("--claim-prefix", default="C")
    parser.add_argument("--claim-id-style", default="article", choices=["article", "global"])
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--article-id-col")
    parser.add_argument("--title-col")
    parser.add_argument("--date-col")
    parser.add_argument("--url-col")
    parser.add_argument("--body-col")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.min_chars < 1:
        raise SystemExit("--min-chars must be at least 1.")
    if not args.input.is_file():
        raise SystemExit(f"Input CSV not found: {args.input}")
    if args.output.exists() and not args.overwrite:
        raise SystemExit(f"Output already exists: {args.output} (use --overwrite)")

    try:
        articles, fieldnames, detected_encoding = read_articles(
            args.input, args.encoding, limit=args.limit
        )
        columns = resolve_columns(
            fieldnames,
            {
                "article_id": args.article_id_col,
                "title": args.title_col,
                "date": args.date_col,
                "url": args.url_col,
                "body": args.body_col,
            },
        )
        splitter, splitter_name = get_sentence_splitter(args.splitter)
    except (RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from error

    rows, empty_articles = preprocess_articles(
        articles,
        columns,
        splitter,
        min_chars=args.min_chars,
        article_prefix=args.article_prefix,
        claim_prefix=args.claim_prefix,
        claim_id_style=args.claim_id_style,
    )
    write_sentences(args.output, rows)

    article_count = len(articles)
    print(f"Created: {args.output}")
    print(
        f"Articles: {article_count} | Sentences: {len(rows)} | "
        f"Empty articles: {empty_articles}"
    )
    print(f"Encoding: {detected_encoding} | Splitter: {splitter_name}")


if __name__ == "__main__":
    main()
