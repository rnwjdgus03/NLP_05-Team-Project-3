"""Period range normalization shared by local and MCP KOSIS preflight.

KOSIS metadata uses several human-readable range formats (for example
``1965.02~2026.07``), while API coordinates use compact digit-only periods.
This module converts both sides to periodicity-specific ordinals before
comparison so a monthly bound is never compared with a four-digit year.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _periodicity(value: Any) -> str:
    raw = _text(value).upper()
    aliases = {
        "YEAR": "Y", "YEARLY": "Y", "연": "Y", "연간": "Y",
        "QUARTER": "Q", "QUARTERLY": "Q", "분기": "Q",
        "MONTH": "M", "MONTHLY": "M", "월": "M", "월간": "M",
    }
    return aliases.get(raw, raw[:1])


def period_ordinals(value: Any, prd_se: Any) -> list[int]:
    """Return every valid period occurrence as a comparable ordinal."""
    raw = _text(value)
    periodicity = _periodicity(prd_se)
    if not raw:
        return []
    if periodicity == "Y":
        return [int(year) for year in re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", raw)]
    if periodicity == "M":
        matches = re.findall(
            r"((?:19|20)\d{2})\s*(?:[.\-/년]\s*)?(0[1-9]|1[0-2])(?=\D|$)",
            raw,
        )
        return [int(year) * 12 + int(month) - 1 for year, month in matches]
    if periodicity == "Q":
        patterns = (
            r"((?:19|20)\d{2})\s*(?:[.\-/년]\s*)?[Qq]\s*([1-4])",
            r"((?:19|20)\d{2})\s*(?:[.\-/년]\s*)?([1-4])\s*(?:/\s*4|분기)",
            r"((?:19|20)\d{2})\s*0([1-4])(?=\D|$)",
        )
        matches: list[tuple[str, str]] = []
        for pattern in patterns:
            matches.extend(re.findall(pattern, raw))
        return [int(year) * 4 + int(quarter) - 1 for year, quarter in matches]
    return []


def period_in_ranges(
    target: Any,
    rows: Sequence[Mapping[str, Any]],
    prd_se: Any,
) -> bool | None:
    """Return whether ``target`` is inside any matching official range.

    ``None`` means that either the target or the official range could not be
    parsed. It is intentionally distinct from ``False`` so the verification
    gate can abstain instead of inventing an out-of-range result.
    """
    periodicity = _periodicity(prd_se)
    target_values = period_ordinals(target, periodicity)
    if len(target_values) != 1:
        return None
    target_ordinal = target_values[0]
    parsed_ranges: list[tuple[int, int]] = []
    for row in rows:
        if _periodicity(row.get("prd_se")) != periodicity:
            continue
        values = period_ordinals(row.get("range_text"), periodicity)
        if len(values) < 2:
            continue
        start, end = values[0], values[-1]
        parsed_ranges.append((min(start, end), max(start, end)))
    if not parsed_ranges:
        return None
    return any(start <= target_ordinal <= end for start, end in parsed_ranges)
