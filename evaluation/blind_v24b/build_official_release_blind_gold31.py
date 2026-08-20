#!/usr/bin/env python3
"""Build an ID/URL-disjoint blind retrieval fixture and a separate gold file.

The fixture contains only claim-side fields.  Table/ITEM/OBJ labels are written
to the separate gold CSV and must be verified against KOSIS before evaluation.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "blind_official_release_measurements31.csv"
GOLD = ROOT / "blind_official_release_coordinate_gold31_unverified.csv"
MANIFEST = ROOT / "blind_official_release_gold31_build_manifest.json"


DOCS = [
    ("B26CPI01", "2026년 1월 소비자물가동향", "2026-02-03", "https://mods.go.kr/board.es?act=view&bid=213&list_no=443358&mid=b70203010000&ref_bid=213&tag=", "202601", (0.4, 2.0, 2.3, 2.2)),
    ("B26CPI02", "2026년 2월 소비자물가동향", "2026-03-06", "https://www.mods.go.kr/board.es?act=view&bid=213&list_no=443883&mid=b70203010000&ref_bid=213", "202602", (0.3, 2.0, 2.5, 1.8)),
    ("B26CPI03", "2026년 3월 소비자물가동향", "2026-04-02", "https://www.mods.go.kr/board.es?act=view&bid=213&list_no=444361&mid=a10301040200", "202603", (0.3, 2.2, 2.3, 2.3)),
    ("B26CPI04", "2026년 4월 소비자물가동향", "2026-05-06", "https://www.mods.go.kr/board.es?act=view&bid=213&list_no=444938&mainXml=Y&mid=b70203010000", "202604", (0.5, 2.6, 2.2, 2.9)),
    ("B26EMP01", "2026년 1월 고용동향", "2026-02-11", "https://mods.go.kr/board.es?act=view&bid=210&list_no=443455&mid=a10301030100&ref_bid=&tag=", "202601", (4.1, 6.8, 27986)),
    ("B26EMP02", "2026년 2월 고용동향", "2026-03-18", "https://www.mods.go.kr/board.es?act=view&bid=210&list_no=444083&mid=a10301030200", "202602", (3.4, 7.7, 28413)),
    ("B26EMP03", "2026년 3월 고용동향", "2026-04-15", "https://www.mods.go.kr/board.es?act=view&bid=210&list_no=444572&mid=a10301010000", "202603", (3.0, 7.6, 28795)),
    ("B26EMP04", "2026년 4월 고용동향", "2026-05-13", "https://www.mods.go.kr/board.es?act=view&bid=210&list_no=445107&mid=a10301010000", "202604", (2.9, 7.1, 28961)),
    ("B26EMP05", "2026년 5월 고용동향", "2026-06-11", "https://mods.go.kr/board.es?act=view&bid=210&list_no=445442&mid=a10301030200&ref_bid=&tag=", "202605", (2.9, 7.2, 29120)),
]


INPUT_FIELDS = [
    "claim_id", "claim_measurement_id", "article_id", "title", "date", "url",
    "claim_text", "prev_sentence", "next_sentence", "claim_domain_scope",
    "is_recurring_series", "metric_domain", "indicator", "keywords", "region",
    "age_group", "gender", "industry_or_item", "population_etc",
    "origin_country", "destination_country", "period", "period_end", "prd_se",
    "time_resolution_status", "measurement_text", "measurement_usage",
    "measurement_source", "measurement_indicator", "measurement_item",
    "measurement_period", "measurement_prd_se", "measurement_binding_source",
    "measurement_role", "value", "value_min", "value_max", "value_approximate",
    "unit", "value_type", "direction", "change_base", "evidence_text",
    "extraction_confidence", "needs_review", "review_reason", "measurement_repaired",
    "measurement_fallback_count", "measurement_binding_fallback_count",
    "extraction_model", "prompt_version", "extracted_at", "claim_indicator",
    "claim_industry_or_item", "claim_period", "claim_prd_se",
    "raw_measurement_period", "period_alignment_status", "raw_unit",
    "canonical_unit", "unit_dimension", "semantic_type", "entity_type",
    "comparison_period", "mapping_type", "obj_target_terms", "blind_source_type",
]


GOLD_FIELDS = [
    "claim_id", "claim_measurement_id", "article_id", "title", "date", "url",
    "claim_text", "measurement_text", "measurement_indicator", "measurement_item",
    "value", "unit", "measurement_period", "measurement_prd_se", "gold_ready",
    "gold_org_id", "gold_tbl_id", "gold_tbl_name", "gold_itm_id", "gold_itm_name",
    "gold_obj_l1", "gold_obj_l1_name", "gold_prd_se", "gold_period",
    "gold_source_value", "gold_source_unit", "gold_actual_value", "gold_verdict",
    "gold_coordinate_status", "gold_confidence", "gold_reason", "gold_evidence_url",
    "gold_retrieved_at", "gold_label_source", "human_reviewed", "development_table_overlap",
]


def base_input(doc, suffix: str, claim: str, span: str, indicator: str, item: str,
               value: float, unit: str, role: str, semantic: str, age: str = "-") -> dict[str, str]:
    article_id, title, date, url, period, _ = doc
    claim_id = f"{article_id}-{suffix}"
    return {
        "claim_id": claim_id,
        "claim_measurement_id": f"{claim_id}-m1",
        "article_id": article_id, "title": title, "date": date, "url": url,
        "claim_text": claim, "prev_sentence": "-", "next_sentence": "-",
        "claim_domain_scope": "국내공식통계", "is_recurring_series": "Y",
        "metric_domain": "물가" if article_id.startswith("B26CPI") else "고용",
        "indicator": indicator, "keywords": indicator.replace(" ", ", "),
        "region": "전국", "age_group": age, "gender": "전체",
        "industry_or_item": item, "population_etc": "-", "origin_country": "-",
        "destination_country": "-", "period": period, "period_end": "-", "prd_se": "M",
        "time_resolution_status": "확정", "measurement_text": span,
        "measurement_usage": "KOSIS_VALUE", "measurement_source": "hcx",
        "measurement_indicator": indicator, "measurement_item": item or "-",
        "measurement_period": period, "measurement_prd_se": "M",
        "measurement_binding_source": "hcx", "measurement_role": role,
        "value": str(value), "value_min": "-", "value_max": "-",
        "value_approximate": "N", "unit": unit, "value_type": role,
        "direction": "-", "change_base": "전월" if "전월" in indicator else "전년동월",
        "evidence_text": claim, "extraction_confidence": "high", "needs_review": "N",
        "review_reason": "-", "measurement_repaired": "N",
        "measurement_fallback_count": "0", "measurement_binding_fallback_count": "0",
        "extraction_model": "BLIND_STRUCTURED_OFFICIAL_RELEASE",
        "prompt_version": "blind-v1", "extracted_at": "2026-08-20",
        "claim_indicator": indicator, "claim_industry_or_item": item,
        "claim_period": period, "claim_prd_se": "M", "raw_measurement_period": period,
        "period_alignment_status": "exact", "raw_unit": unit, "canonical_unit": unit,
        "unit_dimension": "rate" if unit == "%" else "count",
        "semantic_type": semantic, "entity_type": "population",
        "comparison_period": "", "mapping_type": "direct",
        "obj_target_terms": age if age != "-" else item,
        "blind_source_type": "OFFICIAL_RELEASE_INDEPENDENT_STRUCTURED_FIXTURE",
    }


def gold_row(inp: dict[str, str], tbl: str, tbl_name: str, itm: str, itm_name: str,
             obj: str, obj_name: str, overlap: str) -> dict[str, str]:
    row = {key: inp.get(key, "") for key in GOLD_FIELDS}
    row.update({
        "gold_ready": "N", "gold_org_id": "101", "gold_tbl_id": tbl,
        "gold_tbl_name": tbl_name, "gold_itm_id": itm, "gold_itm_name": itm_name,
        "gold_obj_l1": obj, "gold_obj_l1_name": obj_name, "gold_prd_se": "M",
        "gold_period": inp["measurement_period"], "gold_source_value": inp["value"],
        "gold_source_unit": inp["unit"], "gold_actual_value": "",
        "gold_verdict": "PENDING_KOSIS_ACTUAL_QUERY",
        "gold_coordinate_status": "PENDING_KOSIS_ACTUAL_QUERY",
        "gold_confidence": "PENDING", "gold_reason": "독립 공식 보도자료에서 후보를 잠근 뒤 KOSIS API 실제 조회 대기",
        "gold_evidence_url": inp["url"], "gold_retrieved_at": "",
        "gold_label_source": "MODS_RELEASE_THEN_KOSIS_API", "human_reviewed": "N",
        "development_table_overlap": overlap,
    })
    return row


def build() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    inputs, gold = [], []
    for doc in DOCS:
        article_id, _, _, _, period, values = doc
        if article_id.startswith("B26CPI"):
            month = int(period[-2:])
            specs = [
                ("CPI-MOM", f"2026년 {month}월 소비자물가지수는 전월보다 {values[0]}% 상승했다.", f"{values[0]}%", "소비자물가지수 전월비", "총지수", values[0], "T02", "전월비", "0", "총지수"),
                ("CPI-YOY", f"2026년 {month}월 소비자물가지수는 전년 동월보다 {values[1]}% 상승했다.", f"{values[1]}%", "소비자물가지수 전년동월비", "총지수", values[1], "T03", "전년동월비(%)", "0", "총지수"),
                ("CORE-YOY", f"2026년 {month}월 농산물및석유류제외지수는 전년 동월보다 {values[2]}% 상승했다.", f"{values[2]}%", "농산물및석유류제외지수 전년동월비", "농산물및석유류제외지수", values[2], "T03", "전년동월비(%)", "3", "농산물및석유류제외지수"),
                ("LIVING-YOY", f"2026년 {month}월 생활물가지수는 전년 동월보다 {values[3]}% 상승했다.", f"{values[3]}%", "생활물가지수 전년동월비", "생활물가지수", values[3], "T03", "전년동월비(%)", "1", "생활물가지수"),
            ]
            for suffix, claim, span, indicator, item, value, itm, itm_name, obj, obj_name in specs:
                inp = base_input(doc, suffix, claim, span, indicator, item, value, "%", "증감률", "rate_change")
                inputs.append(inp)
                gold.append(gold_row(inp, "DT_1J22042", "월별 소비자물가 등락률", itm, itm_name, obj, obj_name, "N"))
        else:
            month = int(period[-2:])
            specs = [
                ("UNEMP", f"2026년 {month}월 전체 실업률은 {values[0]}%였다.", f"{values[0]}%", "전체 실업률", "전체", values[0], "%", "T80", "실업률", "0", "계", "DT_1DA7001S", "성별 경제활동인구 총괄", "-", "Y"),
                ("YOUTH-UNEMP", f"2026년 {month}월 15~29세 청년층 실업률은 {values[1]}%였다.", f"{values[1]}%", "청년층 실업률", "15~29세", values[1], "%", "T80", "실업률", "75", "15 - 29세", "DT_1DA7002S", "연령별 경제활동인구 총괄", "15~29세", "N"),
                ("EMPLOYED", f"2026년 {month}월 전체 취업자는 {values[2]:,}천명이었다.", f"{values[2]:,}천명", "전체 취업자 수", "전체", values[2], "천명", "T30", "취업자", "0", "계", "DT_1DA7001S", "성별 경제활동인구 총괄", "-", "Y"),
            ]
            for suffix, claim, span, indicator, item, value, unit, itm, itm_name, obj, obj_name, tbl, tbl_name, age, overlap in specs:
                inp = base_input(doc, suffix, claim, span, indicator, item, value, unit, "현재값" if unit != "%" else "수준값", "count" if unit != "%" else "rate", age)
                inputs.append(inp)
                gold.append(gold_row(inp, tbl, tbl_name, itm, itm_name, obj, obj_name, overlap))
    assert len(inputs) == len(gold) == 31
    return inputs, gold


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    input_rows, gold_rows = build()
    write_csv(INPUT, INPUT_FIELDS, input_rows)
    write_csv(GOLD, GOLD_FIELDS, gold_rows)
    manifest = {
        "schema_version": "blind-official-release-gold-build-v1",
        "selection_locked_before_prediction": True,
        "documents": len(DOCS), "rows": len(gold_rows),
        "article_ids": [doc[0] for doc in DOCS],
        "input_sha256": sha256(INPUT), "unverified_gold_sha256": sha256(GOLD),
        "development_overlap_policy": "article/url/claim disjoint; table overlap recorded per row",
        "evaluation_scope": "retrieval and coordinate mapping; structured extraction is supplied, not evaluated",
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
