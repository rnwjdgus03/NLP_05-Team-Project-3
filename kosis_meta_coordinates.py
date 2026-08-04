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
# 좌표 생성 시 축 상한(DEFAULT_AXIS_VALUE_LIMIT)을 적용해도 집계값이 살아남게 하는 목록.
# 여기를 바꾸면 어떤 좌표가 인덱스에 들어가는지가 바뀌므로 Chroma 인덱스를 재빌드해야 한다.
# 그래서 아래 AGGREGATE_OBJ_NAMES(순위·판정용)와 일부러 분리해 둔다.
AGGREGATE_NAMES = ("계", "전체", "총계", "총액", "전국", "합계")

# 순위·판정에서 '이 좌표가 집계값인가'를 볼 때 쓰는 정식 목록.
# 2026-08-02 이전에는 kosis_meta_coordinates 와 kosis_validate_mapping_candidates 에
# 서로 다른 목록이 각각 있었다. 여기로 모은다.
# '총지수'는 추측이 아니라 실측으로 추가했다 — 골드 정답이 T10(총지수)인데
# 집계로 인정받지 못해 빈 축 후보에 밀린 사례가 있었다.
AGGREGATE_OBJ_NAMES = ("계", "전체", "총계", "합계", "총액", "전국",
                       "소계", "평균", "전산업", "총지수")

# 주장이 세부 대상을 특정하지 않았음을 뜻하는 값들.
AGGREGATE_ITEM_TOKENS = frozenset({"", "-", "전체", "총계", "합계", "총액"})


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_obj_name(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", str(value or "")).lower()


_AGGREGATE_NORMALIZED = frozenset(normalize_obj_name(n) for n in AGGREGATE_OBJ_NAMES)


def is_aggregate_name(value: Any) -> bool:
    """이름이 집계축을 가리키는가.

    완전일치만 인정한다. '전산업생산지수'는 '전산업'으로 시작하지만 별개의 지표이고,
    접두·접미 매칭을 허용하면 이런 것까지 집계로 오인한다.
    반대로 '원화대출금(계)'처럼 실제 집계인데 놓치는 건이 실측으로 확인됐다 —
    확대 여부는 별도 측정 후 결정한다.
    """
    return normalize_obj_name(value) in _AGGREGATE_NORMALIZED


def metadata_is_aggregate(metadata: Mapping[str, Any] | None, max_level: int = 3) -> bool:
    """좌표의 분류축이 전부 집계인가 (축 이름이 하나도 없으면 집계로 본다)."""
    names = [_text((metadata or {}).get(f"obj_l{level}_name"))
             for level in range(1, max_level + 1)]
    names = [name for name in names if name]
    return all(is_aggregate_name(name) for name in names) if names else True


def claim_specifies_target(claim: Mapping[str, Any] | None) -> bool:
    """주장이 세부 대상(품목·업종 등)을 특정했는가."""
    item = _first(claim or {}, "industry_or_item", "measurement_item")
    return bool(normalize_obj_name(item)) and item not in AGGREGATE_ITEM_TOKENS


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
        items = table["items"]
        # 표 상한을 ITEM 개수로 나눠 **모든 ITEM 이 최소 몫을 갖도록** 한다.
        # 2026-07-31 이전에는 상한이 표 누적이라 앞쪽 ITEM 이 예산을 다 쓰면
        # 뒤쪽 itm_id 는 좌표가 0개가 되어 그 ITEM 은 검증 대상조차 될 수 없었다.
        # (axis_value_limit 을 올릴 때 이 굶주림이 실제로 터진다.)
        per_item_budget = max(1, max_coordinates_per_table // max(1, len(items)))
        for item in items:
            made_for_item = 0
            # 축이 없으면 빈 조합 하나, 있으면 축별 후보의 데카르트 곱.
            # itertools.product 는 소모되므로 item 마다 새로 만든다.
            selections: Iterable[tuple] = (
                itertools.product(*(choices for _, choices in axis_choices))
                if axis_choices else [()]
            )
            for selected in selections:
                if made_for_item >= per_item_budget or made >= max_coordinates_per_table:
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
                made_for_item += 1
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

def claim_prd_se(claim: Mapping[str, Any]) -> str:
    """주장의 수록주기 (필드명이 두 가지라 한 곳에서 읽는다)."""
    return _first(claim, "measurement_prd_se", "prd_se")


def prd_se_compatible(claim_prd_se_value: str, coordinate_prd_se: str) -> bool:
    """주기 호환 여부.

    2026-07-31: 이 함수는 더 이상 **hard filter 로 쓰지 않는다**(순위 강등 신호로만 쓴다).
    좌표의 prd_se 는 표당 하나의 값으로만 채워지는데 KOSIS 표는 월·분기·연 수록주기를
    동시에 갖는 경우가 많아, 이걸로 배제하면 정답 좌표까지 통째로 사라진다.
    실측: 정답 좌표 17건이 (M↔Y, Q↔Y) 불일치로 배제됐고 그중 8건은 후보가 0개가 됐다.
    """
    claim_value = _text(claim_prd_se_value).upper()
    coordinate_value = _text(coordinate_prd_se).upper()
    if not claim_value or not coordinate_value:
        return True
    return claim_value == coordinate_value


# 사실상 같은 차원인데 이름만 다른 것들을 하나로 모은다.
DIMENSION_ALIASES = {
    "person_count": "count",
    "persons": "count",
    "people": "count",
    "case_count": "count",
    "quantity": "count",
}

# 증감률/증감폭 주장은 KOSIS 수준값(통화·개수·지수)에서 계산해야 하므로
# 좌표의 단위 차원으로 배제하면 안 된다.
DERIVED_DIMENSIONS = {"rate", "rate_point", "percentage_point", "difference"}
DERIVED_MAPPING_TYPES = {"rate_from_level", "difference_from_level"}


def normalize_dimension(dimension: str) -> str:
    value = _text(dimension).lower()
    return DIMENSION_ALIASES.get(value, value)


def unit_dimension_compatible(claim_dimension: str, coordinate_dimension: str,
                              mapping_type: str = "") -> bool:
    """단위 차원 호환.

    2026-07-31 수정: 예외 조건을 mapping_type 에만 걸어두면 **작동하지 않는다**.
    mapping_type 은 (주장, 좌표) 쌍에서 KOSIS 아이템 단위를 봐야 정해지는 값이라
    검색 단계의 주장 레코드에는 비어 있다. 실측에서 rate 주장 18건이 이 때문에
    수준값 좌표와 호환 불가로 잘렸다. 이제 **주장 차원이 파생값이면 무조건 허용**한다.

    차원을 확정할 수 없으면(unknown/빈값) 배제하지 않는다 — 배제는 API 검증 단계 책임.
    """
    if _text(mapping_type).lower() in DERIVED_MAPPING_TYPES:
        return True
    claim_value = normalize_dimension(claim_dimension)
    coordinate_value = normalize_dimension(coordinate_dimension)
    if claim_value in DERIVED_DIMENSIONS:
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
    # prd_se 는 hard filter 에서 제외한다(표당 단일 값이라 신뢰할 수 없음). 순위 강등으로만 반영.
    mapping_type = _text(_first(claim, "mapping_type")).lower()
    dimension = normalize_dimension(_first(claim, "unit_dimension"))
    if (dimension and dimension not in DERIVED_DIMENSIONS
            and mapping_type not in DERIVED_MAPPING_TYPES):
        allowed = sorted({dimension, "", "unknown"} |
                         {alias for alias, target in DIMENSION_ALIASES.items()
                          if target == dimension})
        clauses.append({"unit_dimension": {"$in": allowed}})
    if not clauses:
        return {}
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def passes_hard_filter(claim: Mapping[str, Any], metadata: Mapping[str, Any],
                       tbl_ids: Sequence[str]) -> bool:
    """Chroma where 와 동일한 규칙의 로컬 검증용 필터(테스트·fallback 경로).

    prd_se 는 여기서 배제하지 않는다. `prd_se_compatible` 은 순위 강등에만 쓴다.
    """
    ids = {_text(t) for t in tbl_ids if _text(t)}
    if ids and _text(metadata.get("tbl_id")) not in ids:
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


# --------------------------------------------------------------------------
# 수록 주기 (2026-08-04)
# --------------------------------------------------------------------------
# KOSIS 는 주기를 **두 어휘**로 답한다. 하나만 처리하면 조용히 어긋난다.
#   자료 행      PRD_SE = 'Y' / 'Q' / 'M'
#   getMeta PRD  PRD_SE = '년' / '분기' / '월'
#
# 그리고 **분기 PRD_DE 는 월간과 모양이 같다.** 실측(DT_1K41012, prdSe=Q):
#   202501 202502 202503 202504 202601 202602
# 분기를 2자리로 채우므로 '202501' 이 1분기인지 1월인지 글자로는 구분이 안 된다.
# 반드시 PRD_SE 를 함께 봐야 한다.
PRD_SE_ALIASES = {
    "Y": "Y", "년": "Y", "연": "Y", "연간": "Y", "년도": "Y",
    "H": "H", "반기": "H",
    "Q": "Q", "분기": "Q",
    "M": "M", "월": "M", "월간": "M",
    "D": "D", "일": "D",
    "IR": "IR", "부정기": "IR",
}


def normalize_periodicity(value) -> str:
    """'월'·'M' 을 모두 'M' 으로. 모르는 값이면 빈 문자열."""
    return PRD_SE_ALIASES.get(str(value or "").strip(), "")
