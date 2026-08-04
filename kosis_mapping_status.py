#!/usr/bin/env python3
"""Central READY / REVIEW / NOT_KOSIS decision helpers for KOSIS mapping.

This module does not replace legacy candidate_status, mapping_status, or
verdict_code.  It adds a public final_status contract while keeping old columns
available for compatibility and debugging.
"""
from __future__ import annotations

from typing import Any, Mapping

READY = "READY"
REVIEW = "REVIEW"
NOT_KOSIS = "NOT_KOSIS"

TRUTHY = {"true", "1", "y", "yes", "t", "Y", "True", "TRUE"}
NOT_KOSIS_SCOPES = {"기업통계", "개별기업", "해외통계", "정책값", "민간통계"}
NOT_KOSIS_MAPPING_STATUSES = {"NO_KOSIS_TABLE"}


def truthy(value: Any) -> bool:
    return str(value).strip() in TRUTHY or str(value).strip().lower() in TRUTHY


def _first(row: Mapping[str, Any], *names: str, default: Any = "") -> Any:
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip() != "":
            return value
    return default


def kosis_scope_status(row: Mapping[str, Any]) -> dict[str, str]:
    """Classify obvious non-KOSIS inputs without using gold labels."""
    scope = str(_first(row, "claim_domain_scope", default="")).strip()
    usage = str(_first(row, "measurement_usage", default="")).strip()
    role = str(_first(row, "measurement_role", default="")).strip()
    if scope in NOT_KOSIS_SCOPES:
        return {"final_status": NOT_KOSIS, "not_kosis_reason": f"claim_domain_scope={scope}", "review_reason": ""}
    if usage and usage != "KOSIS_VALUE":
        if usage in {"POLICY_VALUE", "CONDITION", "CONTEXT", "PRIVATE_VALUE"}:
            return {"final_status": NOT_KOSIS, "not_kosis_reason": f"measurement_usage={usage}", "review_reason": ""}
    if role == "목표값":
        return {"final_status": NOT_KOSIS, "not_kosis_reason": "목표값은 관측 통계가 아님", "review_reason": ""}
    return {"final_status": "", "not_kosis_reason": "", "review_reason": ""}


def decide_final_status(row: Mapping[str, Any], *, require_value: bool = False) -> dict[str, str]:
    """Return final_status plus human-readable reason columns.

    READY requires all evidence gates to be true.  API success alone is never
    enough: official metadata, ITEM/OBJ combination validity, coordinate exact
    match, unit/period compatibility, value presence, and semantic gate must all
    pass.
    """
    scope = kosis_scope_status(row)
    if scope["final_status"] == NOT_KOSIS:
        return scope

    mapping_status = str(_first(row, "mapping_status", default="")).strip()
    mapping_reason = str(_first(row, "mapping_reason", "status_reason", default="")).strip()
    verdict_code = str(_first(row, "verdict_code", default="")).strip()

    if mapping_status in NOT_KOSIS_MAPPING_STATUSES:
        return {"final_status": NOT_KOSIS, "not_kosis_reason": mapping_reason or mapping_status, "review_reason": ""}

    gates = [
        ("kosis_verifiable", not scope["not_kosis_reason"]),
        ("table_can_represent_claim", str(_first(row, "table_can_represent_claim", default="Y")).strip() != "N"),
        ("capability_reviewed_or_direct_meta", (
            str(_first(row, "capability_review_status", default="OFFICIAL_REVIEWED")).strip() != "UNREVIEWED"
            or truthy(_first(row, "direct_coordinate_official_meta_evidence", default=""))
        )),
        ("formula_valid", str(_first(row, "formula_valid", default="Y")).strip() != "N"),
        ("period_scope_valid", str(_first(row, "period_scope_valid", "period_scope_exact_match", default="Y")).strip() != "N"),
        ("codeset_valid", str(_first(row, "requires_codeset", default="N")).strip() != "Y" or truthy(_first(row, "codeset_valid", default=""))),
        ("metadata_combination_valid", truthy(_first(row, "metadata_combination_valid", "metadata_valid", default=""))),
        ("item_meta_valid", truthy(_first(row, "item_meta_valid", "metadata_valid", default=""))),
        ("obj_meta_valid", truthy(_first(row, "obj_meta_valid", "metadata_valid", default=""))),
        ("api_request_success", truthy(_first(row, "api_request_success", "api_valid", default=""))),
        ("api_coordinate_exact_match", truthy(_first(row, "api_coordinate_exact_match", "response_code_valid", default=""))),
        ("unit_compatible", truthy(_first(row, "unit_compatible", "unit_valid", default=""))),
        ("period_compatible", truthy(_first(row, "period_compatible", "period_valid", default=""))),
        ("semantic_ready_gate_passed", truthy(_first(row, "semantic_ready_gate_passed", "semantic_gate_valid", default=""))),
    ]
    if require_value or "api_value_exists" in row:
        gates.append(("api_value_exists", truthy(_first(row, "api_value_exists", default=""))))

    missing = [name for name, ok in gates if not ok]
    if mapping_status == "READY" and not missing:
        return {"final_status": READY, "not_kosis_reason": "", "review_reason": ""}

    if verdict_code in {"MATCH", "VALUE_MISMATCH"} and not missing and mapping_status == "READY":
        return {"final_status": READY, "not_kosis_reason": "", "review_reason": ""}

    reason_parts = []
    if str(_first(row, "table_can_represent_claim", default="")).strip() == "N":
        reason_parts.append("TABLE_CANNOT_REPRESENT_CLAIM")
        representation = str(_first(row, "representation_reason", default="")).strip()
        if representation:
            reason_parts.append(representation)
    if (
        str(_first(row, "capability_review_status", default="")).strip() == "UNREVIEWED"
        and not truthy(_first(row, "direct_coordinate_official_meta_evidence", default=""))
    ):
        reason_parts.append("TABLE_CAPABILITY_UNREVIEWED")
    if mapping_status and mapping_status != "READY":
        reason_parts.append(mapping_reason or mapping_status)
    if missing:
        reason_parts.append("missing gates: " + ",".join(missing))
    if verdict_code and verdict_code not in {"MATCH", "VALUE_MISMATCH"}:
        reason_parts.append(f"verdict_code={verdict_code}")
    return {"final_status": REVIEW, "not_kosis_reason": "", "review_reason": " / ".join(reason_parts) or "insufficient evidence"}
