from pathlib import Path

def test_v39_runner_policy():
    text = (Path(__file__).parents[1] / 'cloud_setup/run_v39_candidate.sh').read_text()
    assert '--top-k 30' in text
    assert '--beam-width 400' in text
    assert '--coordinate-pool-top-k 400' in text
    assert '--preserve-table-fallback' in text
    assert '--obj-scope-bonus 0.10' in text
    assert '--item-exact-bonus 0.25' in text
