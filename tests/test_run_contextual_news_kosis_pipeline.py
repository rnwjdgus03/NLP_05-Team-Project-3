from pathlib import Path

from run_contextual_news_kosis_pipeline import output_paths, should_stop


def test_numbered_output_contract_is_stable():
    paths = output_paths(Path("run"))
    assert paths["sentences"] == Path("run/01_sentences.csv")
    assert paths["spans"] == Path("run/03_claim_spans.csv")
    assert paths["contexts"] == Path("run/03_claim_contexts.csv")
    assert paths["in_ready_all"] == Path("run/06_in_ready_all.csv")
    assert paths["ready"] == Path("run/06_mapping_ready.csv")
    assert paths["mapping"] == Path("run/07_mapping")


def test_stop_after_uses_pipeline_order():
    assert not should_stop("chunks", "retrieval")
    assert should_stop("retrieval", "retrieval")
    assert should_stop("mapping", "retrieval")
