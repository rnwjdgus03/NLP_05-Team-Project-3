import json

from build_claim_contexts import build_context_rows, major_target_hints


def sentence(article_id, number, text, paragraph_id="2", paragraph_count="3"):
    return {
        "claim_id": f"{article_id}-C{number:03d}",
        "article_id": article_id,
        "title": f"{article_id} passenger report",
        "date": "2025-01-10",
        "url": f"https://example.com/{article_id}",
        "paragraph_id": paragraph_id,
        "paragraph_sentence_index": str(number),
        "paragraph_count": paragraph_count,
        "claim_text": text,
    }


def span(article_id, number, text):
    sentence_id = f"{article_id}-C{number:03d}"
    return {
        "claim_id": f"{article_id}-SPAN{number}",
        "article_id": article_id,
        "title": f"{article_id} passenger report",
        "date": "2025-01-10",
        "claim_text": text,
        "evidence_sentence_ids": json.dumps([sentence_id]),
    }


def test_claim_context_combines_shared_lead_local_and_related_sentences():
    rows = [
        sentence("A1", 1, "International passengers were surveyed.", "1"),
        sentence("A1", 2, "Low-cost carriers were included.", "1"),
        sentence("A1", 3, "Background information.", "2"),
        sentence("A1", 4, "In 2024 passenger count was 100.", "2"),
        sentence("A1", 5, "More background.", "2"),
        sentence("A1", 6, "The transport market changed.", "2"),
        sentence("A1", 7, "During the same period it rose 3 percent.", "3"),
        sentence("A1", 8, "The trend continued.", "3"),
        sentence("A2", 1, "Another article says 999.", "1", "1"),
    ]
    spans = [
        span("A1", 7, "During the same period it rose 3 percent."),
        span("A1", 8, "The trend continued."),
    ]

    result = build_context_rows(
        rows, spans, local_window=1, related_limit=2, lead_sentences=3
    )

    assert result[0]["article_context"] == result[1]["article_context"]
    assert "A1-C001" in result[0]["lead_paragraph"]
    assert "A1-C002" in result[0]["lead_paragraph"]
    assert "A1-C004" in result[0]["antecedent_context"]
    assert "A2-C001" not in result[0]["article_context"]
    assert "A2-C001" not in result[0]["local_context"]
    ids = json.loads(result[0]["context_sentence_ids"])
    assert ids["evidence"] == ["A1-C007"]
    assert ids["local"] == ["A1-C006", "A1-C007", "A1-C008"]
    assert result[0]["lead_context_source"] == "first_paragraph"


def test_single_paragraph_uses_bounded_sentence_fallback():
    rows = [
        sentence("A1", number, f"Sentence {number}.", "1", "1")
        for number in range(1, 7)
    ]

    result = build_context_rows(rows, [span("A1", 5, "Sentence 5.")])

    assert result[0]["lead_context_source"] == "fallback_first_sentences"
    assert "A1-C003" in result[0]["lead_paragraph"]
    assert "A1-C004" not in result[0]["lead_paragraph"]


def test_major_target_hints_drop_ids_numbers_particles_and_predicates():
    rows = [
        sentence(
            "A1",
            1,
            "국제선 여객이 지난해보다 증가했다.",
            "1",
            "1",
        )
    ]

    hints = major_target_hints(
        "LCC 국제선 여객이 9명 증가했다",
        "[A1-C001] 국제선 여객이 증가했다.",
        rows,
    ).split("; ")

    assert "lcc" in hints
    assert "국제선" in hints
    assert "여객" in hints
    assert all("a1" not in hint and not any(c.isdigit() for c in hint) for hint in hints)
    assert "증가했다" not in hints


def test_previous_and_next_windows_can_be_controlled_independently():
    rows = [
        sentence("A1", number, f"Sentence {number}.", "1", "1")
        for number in range(1, 8)
    ]

    result = build_context_rows(
        rows,
        [span("A1", 5, "Sentence 5.")],
        previous_window=2,
        next_window=0,
        related_limit=0,
    )

    ids = json.loads(result[0]["context_sentence_ids"])
    assert ids["local"] == ["A1-C003", "A1-C004", "A1-C005"]
    assert "A1-C006" not in result[0]["local_context"]
    assert "prev2-next0" in result[0]["context_version"]
