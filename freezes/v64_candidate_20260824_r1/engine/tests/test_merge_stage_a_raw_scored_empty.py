from __future__ import annotations

import sys
from pathlib import Path

import merge_stage_a_raw_scored as merge


def test_all_missing_stage_a_channels_produce_empty_output(
    tmp_path: Path, monkeypatch,
) -> None:
    output = tmp_path / "merged.jsonl"
    arguments = ["merge_stage_a_raw_scored.py"]
    for name in (
        "legacy",
        "balanced",
        "legacy-raw",
        "balanced-raw",
        "legacy-scored",
        "balanced-scored",
    ):
        arguments.extend([f"--{name}", str(tmp_path / f"{name}.jsonl")])
    arguments.extend(["--output", str(output)])

    monkeypatch.setattr(sys, "argv", arguments)
    merge.main()

    assert output.is_file()
    assert output.read_text(encoding="utf-8") == ""


def test_partial_missing_stage_a_channel_still_fails(
    tmp_path: Path, monkeypatch,
) -> None:
    packet = tmp_path / "legacy.jsonl"
    packet.write_text(
        '{"claim_measurement_id":"claim-1","table_candidates":[]}\n',
        encoding="utf-8",
    )
    output = tmp_path / "merged.jsonl"
    arguments = ["merge_stage_a_raw_scored.py", "--legacy", str(packet)]
    for name in (
        "balanced",
        "legacy-raw",
        "balanced-raw",
        "legacy-scored",
        "balanced-scored",
    ):
        arguments.extend([f"--{name}", str(tmp_path / f"{name}.jsonl")])
    arguments.extend(["--output", str(output)])

    monkeypatch.setattr(sys, "argv", arguments)
    try:
        merge.main()
    except ValueError as error:
        assert str(error) == "Stage A channel claim sets differ"
    else:
        raise AssertionError("partial channel loss must not be silently accepted")
