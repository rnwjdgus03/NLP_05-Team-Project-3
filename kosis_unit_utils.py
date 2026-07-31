"""Shared unit normalization helpers for KOSIS mapping/verification.

This module intentionally contains only second-stage-safe utilities.
The old first-stage IN_READY gate script was removed from the main pipeline.
"""

from __future__ import annotations

import re


def _nz(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text in {"-", "nan", "None"} else text


def canonicalize_unit(unit: str) -> str:
    raw = re.sub(r"\s+", "", _nz(unit)).replace("％", "%")
    aliases = {
        "퍼센트": "%",
        "프로": "%",
        "퍼센트포인트": "%p",
        "%포인트": "%p",
        "퍼센트p": "%p",
        "불": "달러",
        "미달러": "달러",
        "미화달러": "달러",
        "개사": "개",
        "사": "개",
        "곳": "개",
        "인": "명",
        "사람": "명",
    }
    return aliases.get(raw, raw)


def unit_dimension(unit: str) -> str:
    value = canonicalize_unit(unit)
    if not value:
        return "unknown"
    if value in {"%", "%p"}:
        return "rate"
    if any(token in value for token in ("원", "달러", "엔", "유로")):
        return "currency"
    if value in {"명", "천명", "만명", "백만명"}:
        return "person_count"
    if value in {"개", "대", "건", "가구", "세대"}:
        return "count"
    if value in {"세", "살"}:
        return "age"
    if value in {"년", "개월", "월", "주", "일", "시간", "분", "초"}:
        return "duration"
    if value in {"배", "배수"}:
        return "multiple"
    if any(token in value for token in ("톤", "kg", "킬로그램", "ha", "헥타르")):
        return "quantity"
    if value in {"위"}:
        return "rank"
    return "unknown"
