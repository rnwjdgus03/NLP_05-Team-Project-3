from scripts.gold.build_mcp_full_gold_200 import canonical_article_id


def test_numeric_source_article_id_uses_article_prefix_and_four_digits():
    assert canonical_article_id("6") == "A0006"
    assert canonical_article_id(41) == "A0041"
    assert canonical_article_id("191") == "A0191"


def test_existing_article_prefix_is_normalized_without_changing_identity():
    assert canonical_article_id("A6") == "A0006"
    assert canonical_article_id("a0268") == "A0268"
    assert canonical_article_id("A12345") == "A12345"
