import json

import pytest

from build_news_chunks import build_chunks, chunk_ranges


def sentence(article_id, number):
    return {
        "claim_id": f"{article_id}-C{number:03d}",
        "article_id": article_id,
        "title": f"title-{article_id}",
        "date": "2026-07-29",
        "url": f"https://example.com/{article_id}",
        "claim_text": f"sentence {number}",
    }


def test_chunk_ranges_keep_final_window_at_least_five_sentences():
    assert chunk_ranges(13, chunk_size=8, overlap=2) == [(0, 8), (6, 13)]
    assert chunk_ranges(9, chunk_size=8, overlap=2) == [(0, 8), (1, 9)]
    assert chunk_ranges(4, chunk_size=8, overlap=2) == [(0, 4)]


def test_chunk_ranges_validate_requested_window():
    with pytest.raises(ValueError, match="between 5 and 8"):
        chunk_ranges(10, chunk_size=4)


def test_chunks_do_not_cross_articles_and_preserve_traceability():
    rows = [
        *[sentence("A1", number) for number in range(1, 10)],
        *[sentence("A2", number) for number in range(1, 4)],
    ]

    chunks = build_chunks(rows)

    assert [row["chunk_id"] for row in chunks] == [
        "A1-CH001",
        "A1-CH002",
        "A2-CH001",
    ]
    assert json.loads(chunks[0]["sentence_ids"])[0] == "A1-C001"
    assert json.loads(chunks[1]["sentence_ids"])[-1] == "A1-C009"
    assert chunks[1]["prev_sentence"] == "sentence 1"
    assert chunks[0]["next_sentence"] == "sentence 9"
    assert all("A2-C" not in row["chunk_text"] for row in chunks[:2])
