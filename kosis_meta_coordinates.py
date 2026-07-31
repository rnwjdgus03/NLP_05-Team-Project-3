#!/usr/bin/env python3
"""KOSIS 메타 CSV → 검증 가능한 '좌표(coordinate)' 문서 구성 (순수 로직, 무거운 의존성 없음).

메타 행 하나를 그대로 벡터화하면 축 값 하나가 문서가 되어 검증 가능한 단위와 어긋난다.
KOSIS API가 실제로 요구하는 최소 단위는 org_id + tbl_id + itm_id + obj 경로이므로,
그 조합을 하나의 document 로 만든다.

이 모듈은 ChromaDB / sentence-transformers 를 import 하지 않는다.
따라서 로컬에서 fixture 만으로 테스트할 수 있고, Colab GPU 실행 코드와 분리된다.

핵심 계약:
- coordinate_id 는 결정적(deterministic)이다. 같은 입력이면 재생성해도 같은 ID.
- document 텍스트는 사람이 읽을 수 있는 구조화 문장이며 필드명을 드러낸다.
- metadata 는 Chroma hard filter 용으로 스칼라만 담는다(문자열/숫자/불리언).
"""
from __future__ import annotations

import csv
import hashlib
import itertools
import re
from collections import defaultdict
from typing import Any, Iterable, Mapping, Sequence

from prepare_kosis_mapping_input import canonicalize_unit, unit_dimension

SCHEMA_VERSION = "kosis-meta-coordinates-v1"

# obj 축은 KOSIS objL1~objL8 과 1:1 로 대응한다.
MAX_AXIS = 8
# 축이 많은 표에서 조합 폭발을 막기 위한 축별 상한 (집계값 우선 정렬 후 상위 N개).
DEFAULT_AXIS_VALUE_LIMIT = 40
DEFAULT_MAX_COORDINATES_PER_TABLE = 4000
AGGREGATE_NAMES = ("계", "전체", "총계", "총액", "전국", "합계")


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _first(row: Mapping[str, Any], *names: str, default: str = "") -> str:
    for name in names:
        value = _text(row.get(name))
        if value:
            return value
    return default


def _axis_order(row: Mapping[str, Any]) -> int | None:
    raw = _first(row, "axis_order", "OBJ_ID_SN", "obj_id_sn", "obj_level")
    try:
        order = int(float(raw))
    except (TypeError, ValueError):
        return None
    return order if 1 <= order <= MAX_AXIS else None


def _is_item(row: Mapping[str, Any]) -> bool:
    if _first(row, "is_item", "IS_ITEM").upper() in {"Y", "TRUE", "1"}:
        return True
    return _first(row, "axis_id", "OBJ_ID", "obj_id").upper() == "ITEM"


def coordinate_id(org_id: str, tbl_id: str, itm_id: str,
                  obj_codes: Mapping[int, str] | None = None) -> str:
    """결정적 좌표 ID. 같은 좌표면 재생성해도 동일한 값이 나온다.

    축 순서를 정렬해 넣기 때문에 dict 순서에 영향을 받지 않는다.
    """
    parts = [_text(org_id), _text(tbl_id), _text(itm_id)]
    for level in range(1, MAX_AXIS + 1):
        parts.append(_text((obj_codes or {}).get(level, "")))
    payload = "|".join(parts)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return f"{_text(org_id)}:{_text(tbl_id)}:{digest}"


def group_meta_rows(meta_rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], dict]:
    """메타 CSV 행을 (org_id, tbl_id) 별로 items / axes 로 묶는다."""
    tables: dict[tuple[str, str], dict] = {}
    for source in meta_rows or []:
        row = dict(source)
        org_id = _first(row, "org_id", "ORG_ID")
        tbl_id = _first(row, "tbl_id", "TBL_ID")
        code = _first(row, "code_id", "ITM_ID", "itm_id", "code")
        if not (org_id and tbl_id and code):
            continue
        table = tables.setdefault((org_id, tbl_id), {
            "org_id": org_id,
            "tbl_id": tbl_id,
            "tbl_name": _first(row, "tbl_name", "TBL_NM"),
            "category_path": _first(row, "category_path", "path"),
            "items": [],
            "axes": defaultdict(lambda: {"axis_id": "", "axis_name": "", "values": []}),
        })
        name = _first(row, "code_name", "ITM_NM", "itm_nm", "name")
        if _is_item(row):
            table["items"].append({
                "code": code,
                "name": name,
                "unit": _first(row, "unit_name", "UNIT_NM", "unit"),
            })
            continue
        order = _axis_order(row)
        if order is None:
            continue  # 순서를 모르는 축은 objL<n> 으로 안전하게 변환할 수 없다
        axis = table["axes"][order]
        axis["axis_id"] = axis["axis_id"] or _first(row, "axis_id", "OBJ_ID", "obj_id")
        axis["axis_name"] = axis["axis_name"] or _first(row, "axis_name", "OBJ_NM", "obj_nm")
        axis["values"].append({"code": code, "name": name})
    return tables


def _aggregate_first(values: Sequence[Mapping[str, str]]) -> list[dict]:
    """집계값(계/전체/총계)을 앞으로 보내 축 상한을 적용해도 총계 좌표가 남게 한다."""
    def key(value):
        name = _text(value.get("name"))
        return (0 if name in AGGREGATE_NAMES else 1, name)
    return sorted((dict(v) for v in values), key=key)


def build_coordinates(
    meta_rows: Iterable[Mapping[str, Any]],
    *,
    axis_value_limit: int = DEFAULT_AXIS_VALUE_LIMIT,
    max_coordinates_per_table: int = DEFAULT_MAX_COORDINATES_PER_TABLE,
    prd_se_by_table: Mapping[tuple[str, str], str] | None = None,
) -> list[dict]:
    """(org, tbl, itm, obj 경로) 단위 좌표 문서 목록을 만든다."""
    coordinates: list[dict] = []
    for (org_id, tbl_id), table in group_meta_rows(meta_rows).items():
        axes = sorted(table["axes"].items())
        axis_choices = [
            (order, _aggregate_first(axis["values"])[:max(1, axis_value_limit)])
            for order, axis in axes
        ]
        made = 0
        for item in table["items"]:
            # 축이 없으면 빈 조합 하나, 있으면 축별 후보의 데카르트 곱.
            # itertools.product 는 소모되므로 item 마다 새로 만든다.
            selections: Iterable[tuple] = (
                itertools.product(*(choices for _, choices in axis_choices))
                if axis_choices else [()]
            )
            for selected in selections:
                if made >= max_coordinates_per_table:
                    break
                obj_codes = {order: value["code"]
                             for (order, _), value in zip(axis_choices, selected)}
                obj_names = {order: value.get("name", "")
                             for (order, _), value in zip(axis_choices, selected)}
                axis_ids = {order: table["axes"][order]["axis_id"]
                            for order, _ in axis_choices}
                unit = _text(item.get("unit"))
                canonical = canonicalize_unit(unit)
                coordinates.append({
                    "coordinate_id": coordinate_id(org_id, tbl_id, item["code"], obj_codes),
                    "org_id": org_id,
                    "tbl_id": tbl_id,
                    "tbl_name": table["tbl_name"],
                    "category_path": table["category_path"],
                    "itm_id": item["code"],
                    "itm_name": item.get("name", ""),
                    "unit": unit,
                    "canonical_unit": canonical,
                    "unit_dimension": unit_dimension(canonical),
                    "prd_se": _text((prd_se_by_table or {}).get((org_id, tbl_id), "")),
                    "axis_names": {order: table["axes"][order]["axis_name"]
                                   for order, _ in axis_choices},
                    "obj_codes": obj_codes,
                    "obj_names": obj_names,
                    "axis_ids": axis_ids,
                })
                made += 1
            if made >= max_coordinates_per_table:
                break
    return coordinates


def coordinate_document(coordinate: Mapping[str, Any]) -> str:
    """사람이 읽을 수 있고 필드명이 드러나는 구조화 문서 텍스트."""
    lines = [f"통계표: {coordinate.get('tbl_name', '')}"]
    if coordinate.get("category_path"):
        lines.append(f"분류 경로: {coordinate['category_path']}")
    lines.append(f"항목: {coordinate.get('itm_name', '')}")
    obj_names = coordinate.get("obj_names") or {}
    axis_names = coordinate.get("axis_names") or {}
    for order in sorted(obj_names):
        label = _text(axis_names.get(order)) or f"분류{order}"
        value = _text(obj_names.get(order))
        if value:
            lines.append(f"{label}: {value}")
    if coordinate.get("unit"):
        lines.append(f"단위: {coordinate['unit']}")
    if coordinate.get("prd_se"):
        lines.append(f"수록주기: {coordinate['prd_se']}")
    if coordinate.get("org_id"):
        lines.append(f"기관: {coordinate['org_id']}")
    return "\n".join(lines)


def coordinate_metadata(coordinate: Mapping[str, Any]) -> dict[str, Any]:
    """Chroma hard filter 용 스칼라 metadata (리스트/딕셔너리 금지)."""
    meta: dict[str, Any] = {
        "coordinate_id": coordinate["coordinate_id"],
        "org_id": coordinate.get("org_id", ""),
        "tbl_id": coordinate.get("tbl_id", ""),
        "tbl_name": coordinate.get("tbl_name", ""),
        "category_path": coordinate.get("category_path", ""),
        "itm_id": coordinate.get("itm_id", ""),
        "itm_name": coordinate.get("itm_name", ""),
        "unit": coordinate.get("unit", ""),
        "unit_dimension": coordinate.get("unit_dimension", ""),
        "prd_se": coordinate.get("prd_se", ""),
        "schema_version": SCHEMA_VERSION,
    }
    obj_codes = coordinate.get("obj_codes") or {}
    obj_names = coordinate.get("obj_names") or {}
    axis_ids = coordinate.get("axis_ids") or {}
    for level in range(1, MAX_AXIS + 1):
        meta[f"obj_l{level}"] = _text(obj_codes.get(level))
        meta[f"obj_l{level}_name"] = _text(obj_names.get(level))
        meta[f"obj_l{level}_axis_id"] = _text(axis_ids.get(level))
    return meta


# --------------------------------------------------------------------------
# claim → 검색 query
# --------------------------------------------------------------------------

QUERY_FIELDS = (
    ("주장", ("claim_text",)),
    ("지표", ("measurement_indicator", "indicator")),
    ("품목", ("measurement_item", "industry_or_item")),
    ("영역", ("metric_domain",)),
    ("값유형", ("value_type",)),
    ("역할", ("measurement_role",)),
    ("단위", ("unit", "canonical_unit")),
    ("단위차원", ("unit_dimension",)),
    ("시점", ("measurement_period", "period")),
    ("주기", ("measurement_prd_se", "prd_se")),
    ("지역", ("region",)),
    ("연령", ("age_group",)),
    ("성별", ("gender",)),
    ("출발국", ("origin_country",)),
    ("도착국", ("destination_country",)),
)


def build_coordinate_query(claim: Mapping[str, Any], *, claim_text_limit: int = 220) -> str:
    """claim_text 만 쓰지 않고 구조화 필드를 합쳐 필드명이 드러나는 query 를 만든다."""
    parts = []
    for label, names in QUERY_FIELDS:
        value = _first(claim, *names)
        if not value or value == "-":
            continue
        if label == "주장":
            value = value[:claim_text_limit]
        parts.append(f"{label}: {value}")
    return "\n".join(parts)


# --------------------------------------------------------------------------
# hard filter
# --------------------------------------------------------------------------

def prd_se_compatible(claim_prd_se: str, coordinate_prd_se: str) -> bool:
    """주기 호환. 좌표 주기 정보가 없으면 배제하지 않는다(메타에 주기가 없는 표가 많다)."""
    claim_value = _text(claim_prd_se).upper()
    coordinate_value = _text(coordinate_prd_se).upper()
    if not claim_value or not coordinate_value:
        return True
    return claim_value == coordinate_value


def unit_dimension_compatible(claim_dimension: str, coordinate_dimension: str,
                              mapping_type: str = "") -> bool:
    """단위 차원 호환.

    증감률(rate_from_level)은 수준값에서 계산하므로 KOSIS 단위가 통화/개수여도 호환이다.
    차원을 확정할 수 없으면(unknown/빈값) 배제하지 않는다 — 배제는 API 검증 단계 책임.
    """
    claim_value = _text(claim_dimension).lower()
    coordinate_value = _text(coordinate_dimension).lower()
    if _text(mapping_type).lower() in {"rate_from_level", "difference_from_level"}:
        return True
    if not claim_value or not coordinate_value:
        return True
    if "unknown" in (claim_value, coordinate_value):
        return True
    return claim_value == coordinate_value


def build_chroma_where(claim: Mapping[str, Any], tbl_ids: Sequence[str]) -> dict:
    """Chroma metadata hard filter. tbl_id 는 상류 Top-K 로 반드시 제한한다."""
    clauses: list[dict] = []
    ids = [t for t in dict.fromkeys(_text(t) for t in tbl_ids) if t]
    if ids:
        clauses.append({"tbl_id": {"$in": ids}})
    prd_se = _first(claim, "measurement_prd_se", "prd_se")
    if prd_se:
        # 좌표 주기가 비어 있는 문서를 배제하지 않기 위해 '' 도 허용한다.
        clauses.append({"prd_se": {"$in": [prd_se, ""]}})
    mapping_type = _first(claim, "mapping_type")
    dimension = _first(claim, "unit_dimension")
    if dimension and mapping_type not in {"rate_from_level", "difference_from_level"}:
        clauses.append({"unit_dimension": {"$in": [dimension, "", "unknown"]}})
    if not clauses:
        return {}
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def passes_hard_filter(claim: Mapping[str, Any], metadata: Mapping[str, Any],
                       tbl_ids: Sequence[str]) -> bool:
    """Chroma where 와 동일한 규칙의 로컬 검증용 필터(테스트·fallback 경로)."""
    ids = {_text(t) for t in tbl_ids if _text(t)}
    if ids and _text(metadata.get("tbl_id")) not in ids:
        return False
    if not prd_se_compatible(_first(claim, "measurement_prd_se", "prd_se"),
                            _text(metadata.get("prd_se"))):
        return False
    return unit_dimension_compatible(
        _first(claim, "unit_dimension"),
        _text(metadata.get("unit_dimension")),
        _first(claim, "mapping_type"),
    )


def read_csv_rows(path) -> list[dict]:
    csv.field_size_limit(2 ** 31 - 1)
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))
