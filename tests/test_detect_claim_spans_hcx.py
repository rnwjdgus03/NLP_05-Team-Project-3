import json

from detect_claim_spans_hcx import build_span_rows, span_key, stable_span_id


def chunk():
    return {
        "chunk_id": "A1-CH001",
        "article_id": "A1",
        "title": "Employment",
        "date": "2026-07-29",
        "url": "https://example.com/a1",
        "sentence_ids": json.dumps(["A1-C001", "A1-C002", "A1-C003"]),
        "sentences_json": json.dumps(
            [
                "Employment was surveyed.",
                "The number rose by 3 percent.",
                "The increase continued.",
            ]
        ),
        "prev_sentence": "Outside previous sentence.",
        "next_sentence": "Outside next sentence.",
    }


def test_build_span_rows_uses_original_contiguous_evidence():
    response = {
        "spans": [
            {
                "start_sentence_id": "A1-C002",
                "end_sentence_id": "A1-C003",
                "claim_text": "model wording",
                "claim_type": "numeric_change",
                "reason": "contains a measured change",
                "confidence": "high",
            }
        ]
    }

    rows = build_span_rows(chunk(), response, "HCX-007", "2026-07-29")

    assert len(rows) == 1
    assert rows[0]["claim_text"] == (
        "The number rose by 3 percent. The increase continued."
    )
    assert rows[0]["detected_claim_text"] == "model wording"
    assert rows[0]["prev_sentence"] == "Employment was surveyed."
    assert rows[0]["next_sentence"] == "Outside next sentence."
    assert rows[0]["is_claim"] == "True"


def test_invalid_or_duplicate_boundaries_are_discarded():
    base = {
        "start_sentence_id": "A1-C001",
        "end_sentence_id": "A1-C001",
        "claim_text": "value",
        "claim_type": "numeric_level",
        "reason": "value",
        "confidence": "high",
    }
    response = {
        "spans": [
            base,
            dict(base),
            {**base, "start_sentence_id": "UNKNOWN"},
            {
                **base,
                "start_sentence_id": "A1-C003",
                "end_sentence_id": "A1-C002",
            },
        ]
    }

    assert len(build_span_rows(chunk(), response, "HCX-007", "2026-07-29")) == 1


def test_span_id_is_stable_for_overlapping_chunk_deduplication():
    key = span_key("A1", "A1-C002", "A1-C003")
    assert stable_span_id(key) == stable_span_id(key)
    assert stable_span_id(key).startswith("SP")
