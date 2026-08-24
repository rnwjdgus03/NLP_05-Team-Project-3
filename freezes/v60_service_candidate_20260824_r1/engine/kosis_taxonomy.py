"""Role-aware taxonomy checks for structured KOSIS coordinates.

This module intentionally contains no table or measurement identifiers.  It
compares claims with official axis labels so the same rules can be reused for
different surveys and metadata versions.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping


INDUSTRY = "INDUSTRY"
POPULATION_ATTRIBUTE = "POPULATION_ATTRIBUTE"
SEX = "SEX"
EMPLOYMENT_TYPE = "EMPLOYMENT_TYPE"
REGION = "REGION"
COMPANY_SIZE = "COMPANY_SIZE"
CATEGORY = "CATEGORY"
UNKNOWN = "UNKNOWN"

CURRENT_TOTAL = "CURRENT_TOTAL"
FOREIGN = "FOREIGN"
WOMEN = "WOMEN"

_AGGREGATES = frozenset({"계", "전체", "총계", "합계", "전국", "전산업"})
_GENERIC_INDUSTRY_BASES = frozenset({"산업", "업", "제조", "제조업"})
_ADMIN_REGIONS = (
    "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시",
    "대전광역시", "울산광역시", "세종특별자치시", "경기도", "강원특별자치도",
    "강원도", "충청북도", "충청남도", "전북특별자치도", "전라북도",
    "전라남도", "경상북도", "경상남도", "제주특별자치도", "제주도",
)
_REGION_ALIASES = {
    "서울": "서울", "부산": "부산", "대구": "대구", "인천": "인천",
    "광주": "광주", "대전": "대전", "울산": "울산", "세종": "세종",
    "경기": "경기", "강원": "강원", "충북": "충청북", "충남": "충청남",
    "전북": "전라북", "전남": "전라남", "경북": "경상북", "경남": "경상남",
    "제주": "제주",
}


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _normalize(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", _text(value)).lower()


def _claim_text(claim: Mapping[str, Any] | str | None) -> str:
    if isinstance(claim, str):
        return claim
    row = claim or {}
    return " ".join(
        _text(row.get(field))
        for field in (
            "claim_text",
            "indicator",
            "measurement_indicator",
            "industry_or_item",
            "measurement_item",
            "population",
            "measurement_population",
            "population_etc",
            "population_scope",
            "measurement_population_scope",
            "sex",
            "gender",
        )
    )


def infer_axis_role(axis_name: Any) -> str:
    """Infer a semantic role from an official axis name, conservatively."""
    name = _normalize(axis_name)
    if not name:
        return UNKNOWN
    if any(marker in name for marker in ("산업", "업종")):
        return INDUSTRY
    if any(marker in name for marker in ("지역", "권역", "시도", "시군구", "소재지")):
        return REGION
    if any(
        marker in name
        for marker in ("기업규모", "종사자규모", "사업체규모", "고용규모", "인원규모")
    ):
        return COMPANY_SIZE
    if any(marker in name for marker in ("고용형태", "근로형태", "종사상지위")):
        return EMPLOYMENT_TYPE
    # ``특성별`` contains the characters ``성별`` but is not a sex axis.
    # Require an actual sex-axis prefix instead of a substring occurrence.
    if name.startswith(("성별", "남녀별")):
        return SEX
    if any(
        marker in name
        for marker in (
            "특성", "내외국인", "국적", "인구집단", "인력구분", "인력별", "인원별"
        )
    ):
        return POPULATION_ATTRIBUTE
    if any(
        marker in name
        for marker in ("분류", "품목", "상품", "직업", "규모", "유형", "종류")
    ):
        return CATEGORY
    return UNKNOWN


def explicit_table_region(table_name: Any) -> str:
    """Return an explicit province/city prefix from a regional KOSIS table."""
    name = _text(table_name)
    return next((region for region in _ADMIN_REGIONS if name.startswith(region)), "")


def _region_base(value: Any) -> str:
    normalized = _normalize(value)
    for suffix in ("특별자치도", "특별자치시", "특별시", "광역시", "도", "시"):
        if normalized.endswith(suffix) and len(normalized) > len(suffix):
            normalized = normalized[: -len(suffix)]
            break
    return _REGION_ALIASES.get(normalized, normalized)


def regional_table_scope_matches(
    claim: Mapping[str, Any], table_name: Any,
) -> bool:
    """Reject province-specific tables for national or unspecified claims."""
    table_region = explicit_table_region(table_name)
    if not table_region:
        return True
    claim_region = _text(claim.get("measurement_region") or claim.get("region"))
    if _normalize(claim_region) in {"", "전국", "대한민국", "한국"}:
        return False
    return _region_base(claim_region) == _region_base(table_region)


def _industry_base(value: Any) -> str:
    label = _normalize(value)
    if label.endswith("산업") and len(label) > len("산업"):
        return label[: -len("산업")]
    if label.endswith("업") and len(label) > len("업"):
        return label[:-1]
    return label


def industry_label_equivalent(claim: Any, official: Any) -> bool:
    """Allow only a conservative trailing ``업``/``산업`` normalization.

    The comparison is meant exclusively for INDUSTRY axes.  Generic labels
    such as ``제조업`` are not reduced because ``제조`` is an activity, not a
    sufficiently scoped official industry concept.
    """
    def comparable(value: Any) -> str:
        text = _text(value)
        text = re.sub(r"^\s*[A-Z]\s+", "", text)
        text = re.sub(r"\([^)]*\)\s*$", "", text)
        return _normalize(text).replace("및", "")

    claim_label = comparable(claim)
    official_label = comparable(official)
    if not claim_label or not official_label:
        return False
    if claim_label == official_label:
        return True

    claim_base = _industry_base(claim_label)
    official_base = _industry_base(official_label)
    if claim_base != official_base or len(claim_base) < 2:
        return False
    if claim_label in _GENERIC_INDUSTRY_BASES or official_label in _GENERIC_INDUSTRY_BASES:
        return False
    if claim_base.endswith("제조"):
        return False
    return True


def claim_population_requirements(
    claim: Mapping[str, Any] | str | None,
) -> frozenset[str]:
    """Extract the exact population slice required by a claim."""
    text = _normalize(_claim_text(claim))
    requirements: set[str] = set()
    if "외국인" in text:
        requirements.add(FOREIGN)
    if any(marker in text for marker in ("여성", "여자인력", "여자인원")):
        requirements.add(WOMEN)

    workforce_markers = (
        "산업기술인력",
        "현재인원",
        "현원",
        "인력수",
        "근로자수",
        "종사자수",
    )
    if not requirements and any(marker in text for marker in workforce_markers):
        requirements.add(CURRENT_TOTAL)
    return frozenset(requirements)


def _object_field(obj: Mapping[str, Any], *names: str) -> str:
    for name in names:
        value = _text(obj.get(name))
        if value:
            return value
    return ""


def _is_aggregate(value: Any) -> bool:
    return _normalize(value) in {_normalize(name) for name in _AGGREGATES}


def _population_traits(role: str, name: Any) -> frozenset[str]:
    normalized = _normalize(name)
    if not normalized or _is_aggregate(name):
        return frozenset()
    if role == SEX:
        if normalized in {"여", "여성", "여자"}:
            return frozenset({WOMEN})
        return frozenset({f"SEX:{normalized}"})

    if normalized in {"현재인원", "현원", "전체인원", "총인원"}:
        return frozenset({CURRENT_TOTAL})
    if "외국인" in normalized:
        traits = {FOREIGN}
        if "여성" in normalized or normalized.endswith("여"):
            traits.add(WOMEN)
        return frozenset(traits)
    if normalized in {"여", "여성", "여자", "여성인력", "여자인력"}:
        return frozenset({WOMEN})
    return frozenset({f"POPULATION:{normalized}"})


def role_aware_coordinate_scope(
    claim: Mapping[str, Any] | str | None,
    target_terms: Iterable[Any],
    selected_objects: Iterable[Mapping[str, Any]],
) -> bool:
    """Require exact industry and population scope by official axis role."""
    industry_targets = tuple(_text(term) for term in target_terms if _text(term))
    selected_industries: list[str] = []
    selected_population: set[str] = set()

    for obj in selected_objects:
        axis_name = _object_field(obj, "axis_name", "obj_name", "OBJ_NM")
        value_name = _object_field(
            obj, "name", "value_name", "obj_name", "code_name", "ITM_NM"
        )
        role = infer_axis_role(axis_name)

        if role == INDUSTRY:
            if not _is_aggregate(value_name):
                selected_industries.append(value_name)
            continue
        if role in {POPULATION_ATTRIBUTE, SEX}:
            selected_population.update(_population_traits(role, value_name))
            continue
        if role in {REGION, COMPANY_SIZE, CATEGORY, EMPLOYMENT_TYPE, UNKNOWN} and not _is_aggregate(
            value_name
        ):
            return False

    if industry_targets:
        if len(selected_industries) != 1:
            return False
        official = selected_industries[0]
        if not all(
            industry_label_equivalent(target, official)
            for target in industry_targets
        ):
            return False
    elif selected_industries:
        return False

    required_population = claim_population_requirements(claim)
    return frozenset(selected_population) == required_population
