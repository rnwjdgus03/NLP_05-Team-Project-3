"""Adjudicate and evaluate a leakage-resistant KOSIS holdout set."""

from __future__ import annotations

import csv
import importlib.util
import json
import math
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path


REPO = Path(__file__).resolve().parent
SELECTION = REPO / "outputs/bteam_holdout/holdout100_selection.csv"
OUTPUT_DIR = REPO / "outputs/bteam_holdout"
GOLD_CACHE_PATH = OUTPUT_DIR / "holdout_gold_api_cache.json"
OUTPUT_STEM = os.environ.get("KOSIS_HOLDOUT_STEM", "holdout100")
AUTO_CACHE_PATH = OUTPUT_DIR / f"{OUTPUT_STEM}_auto_api_cache.json"
CODEBOOK_FILE = os.environ.get("KOSIS_CODEBOOK_FILE", "expand_kosis_codebook.py")

sys.path.insert(0, str(REPO))
os.chdir(REPO)
from kosis_api_test import get_stat_data  # noqa: E402

spec = importlib.util.spec_from_file_location("frozen_codebook", REPO / CODEBOOK_FILE)
codebook = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(codebook)
codebook.CACHE_PATH = AUTO_CACHE_PATH


def output_file(suffix):
    return OUTPUT_DIR / f"{OUTPUT_STEM}_{suffix}"


def cfg(
    org_id,
    table_id,
    obj_l1,
    item_id,
    period_type,
    target_number,
    target_period,
    mode,
    *,
    prev_period="",
    obj_l2="",
    target_periods=None,
    prev_periods=None,
    note="",
    tolerance=0.3,
):
    return {
        "org_id": org_id,
        "tbl_id": table_id,
        "obj_l1": obj_l1,
        "obj_l2": obj_l2,
        "itm_id": item_id,
        "prd_se": period_type,
        "target_number": float(target_number),
        "target_period": target_period,
        "prev_period": prev_period,
        "target_periods": list(target_periods or []),
        "prev_periods": list(prev_periods or []),
        "mode": mode,
        "note": note,
        "tolerance": tolerance,
    }


ELIGIBLE = {
    "C01367": cfg("301", "DT_402Y014", "13102134642ACC_CD.*AA", "13103134642999", "M", 10.7, "202412", "CHANGE_RATE", prev_period="202312", obj_l2="13102134642CRR_CTRT_CD.W", note="원화기준 수출물가 총지수 전년동월비"),
    "C03672": cfg("101", "DT_1J22042", "4", "T03", "M", 1.9, "202501", "LEVEL", note="식료품및에너지제외지수 전년동월비"),
    "C05541": cfg("101", "DT_1J22003", "T10", "T", "Y", 5.1, "2022", "CHANGE_RATE", prev_period="2021", note="전국 소비자물가 연간 지수 증감률"),
    "C15363": cfg("101", "DT_1J22042", "1", "T03", "M", 2.3, "202505", "LEVEL", note="생활물가지수 전년동월비"),
    "C18189": cfg("101", "DT_1J22042", "0", "T03", "M", 2.2, "202506", "LEVEL", note="소비자물가 총지수 전년동월비"),
    "C18204": cfg("101", "DT_1J22112", "T10", "T", "M", 4.6, "202506", "CHANGE_RATE", prev_period="202406", obj_l2="B01", note="가공식품 지수 전년동월비"),
    "C18209": cfg("101", "DT_1J22112", "T10", "T", "M", 4.0, "202506", "CHANGE_RATE", prev_period="202406", obj_l2="F01K01126", note="라면(외식) 지수 전년동월비"),
    "C18575": cfg("101", "DT_1J22112", "T10", "T", "M", 4.6, "202506", "CHANGE_RATE", prev_period="202406", obj_l2="B01", note="가공식품 지수 전년동월비"),
    "C19740": cfg("101", "DT_1J22112", "T10", "T", "M", 26.7, "202509", "CHANGE_RATE", prev_period="202508", obj_l2="E01H03102", note="휴대전화료 지수 전월비"),
    "C05292": cfg("101", "DT_1ES3A03_A01S", "3743", "T12", "H", 1.1, "202402", "POINT_CHANGE", prev_period="202302", obj_l2="000", note="울릉군 전체 고용률 하반기 전년동기차"),
    "C13306": cfg("101", "DT_1DA7002S", "602", "T90", "M", 1.2, "202504", "POINT_CHANGE", prev_period="202404", note="65세 이상 고용률 전년동월차"),
    "C13307": cfg("101", "DT_1DA7002S", "75", "T90", "M", -0.9, "202504", "POINT_CHANGE", prev_period="202404", note="15~29세 고용률 전년동월차"),
    "C19864": cfg("101", "DT_1DA7002S", "20", "T90", "M", -1.2, "202508", "POINT_CHANGE", prev_period="202408", note="20~29세 고용률 전년동월차"),
    "C20443": cfg("360", "DT_1R11001_FRM101", "13102112831A.A", "13103112831T1", "M", 3.6, "202510", "CHANGE_RATE", prev_period="202410", note="통관 총수출 전년동월비"),
    "C06917": cfg("101", "DT_1B81A01", "23", "T1", "M", 11.6, "2024", "SUM_CHANGE", target_periods=[f"2024{month:02d}" for month in range(1, 13)], prev_periods=[f"2023{month:02d}" for month in range(1, 13)], note="인천 연간 출생아 월자료 합계 전년비"),
    "C07961": cfg("101", "DT_1B8000F", "41", "T1", "Y", 222400, "2024", "LEVEL", note="전국 연간 혼인건수"),
    "C11318": cfg("101", "DT_1B83A35", "00", "T3", "M", 14.3, "202502", "CHANGE_RATE", prev_period="202402", note="전국 월별 혼인건수 전년동월비"),
    "C11321": cfg("101", "DT_1B83A35", "00", "T3", "M", 14.3, "202502", "CHANGE_RATE", prev_period="202402", note="전국 월별 혼인건수 전년동월비"),
    "C11329": cfg("101", "DT_1B81A01", "00", "T1", "M", 3.2, "202502", "CHANGE_RATE", prev_period="202402", note="전국 월별 출생아 전년동월비"),
    "C11415": cfg("101", "DT_1B83A35", "00", "T3", "M", 14.3, "202502", "CHANGE_RATE", prev_period="202402", note="전국 월별 혼인건수 전년동월비"),
    "C11421": cfg("101", "DT_1B83A35", "25", "T3", "M", 32.2, "202502", "CHANGE_RATE", prev_period="202402", note="대전 월별 혼인건수 전년동월비"),
    "C11423": cfg("101", "DT_1B81A01", "00", "T1", "M", 3.2, "202502", "CHANGE_RATE", prev_period="202402", note="전국 월별 출생아 전년동월비"),
    "C17364": cfg("101", "DT_1B81A01", "00", "T1", "M", 8.7, "202504", "CHANGE_RATE", prev_period="202404", note="전국 4월 출생아 전년동월비"),
    "C17367": cfg("101", "DT_1B83A35", "00", "T3", "M", 4.9, "202504", "CHANGE_RATE", prev_period="202404", note="전국 4월 혼인건수 전년동월비"),
    "C17456": cfg("101", "DT_1B81A01", "00", "T1", "M", 8.7, "202504", "CHANGE_RATE", prev_period="202404", note="전국 4월 출생아 전년동월비"),
    "C17458": cfg("101", "DT_1B81A01", "00", "T1", "M", 7.8, "202407", "CHANGE_RATE", prev_period="202307", note="전국 7월 출생아 전년동월비"),
    "C00617": cfg("101", "DT_1K41012", "G0", "T2", "Q", -1.9, "202403", "CHANGE_RATE", prev_period="202303", note="소매판매 불변 총지수 3분기 전년동기비"),
    "C01459": cfg("101", "DT_1K41012", "G0", "T2", "M", -2.1, "202401-202411", "AVG_CHANGE", target_periods=[f"2024{month:02d}" for month in range(1, 12)], prev_periods=[f"2023{month:02d}" for month in range(1, 12)], note="소매판매 불변 총지수 1~11월 평균 전년동기비"),
    "C07771": cfg("101", "DT_1KC2020", "R9121", "T2", "M", -8.2, "202501", "CHANGE_RATE", prev_period="202401", note="유원지·테마파크 불변 생산지수 전년동월비"),
    "C12459": cfg("101", "DT_1K41012", "G31", "T2", "Q", -0.3, "202501", "CHANGE_RATE", prev_period="202401", note="음식료품 소매판매 불변지수 1분기 전년동기비"),
    "C14872": cfg("101", "DT_1KC2020", "T", "T3", "M", -0.1, "202504", "CHANGE_RATE", prev_period="202503", note="서비스업 계절조정 총지수 전월비"),
    "C14874": cfg("101", "DT_1K41012", "G0", "T3", "M", -0.9, "202504", "CHANGE_RATE", prev_period="202503", note="소매판매 계절조정 총지수 전월비"),
    "C20191": cfg("101", "DT_1K41012", "G0", "T3", "Q", 1.5, "202503", "CHANGE_RATE", prev_period="202502", note="소매판매 계절조정 총지수 3분기 전분기비"),
}


EXCLUSION_GROUPS = {
    "KOSIS 미제공": {
        "C01659", "C04595", "C04720", "C06335", "C16267", "C18696",
        "C00922", "C06721", "C06935", "C08021", "C14412", "C18303",
        "C00781", "C00807", "C05059", "C07217", "C09047", "C09181", "C09409", "C12782", "C14905", "C15896", "C16196", "C18761",
        "C03660", "C17366", "C17459",
        "C01370", "C08297", "C10732", "C18210", "C18301", "C18305", "C18306", "C19586",
    },
    "정보 부족": {
        "C04596", "C05153", "C05779", "C19807",
        "C04658", "C05293", "C05294", "C05562", "C10453", "C16599", "C16603", "C20111", "C20115", "C20133",
        "C00180", "C01303", "C11549",
        "C05295", "C07962", "C11427", "C17453",
        "C06577", "C12462", "C13081",
    },
    "지역·분류 불일치": {
        "C09082",
        "C00812", "C04941", "C10746", "C13767",
        "C07959",
        "C09080", "C09084",
    },
}


EXCLUSION_REASON = {
    "KOSIS 미제공": "해외·민간·정책·전망·연구모형 자료로 동일 정의의 KOSIS 관측값이 없음",
    "정보 부족": "복수 수치·복수 대상·선행어 또는 기간 표현 때문에 단일 검증 목표를 확정할 수 없음",
    "지역·분류 불일치": "필요한 지역·품목·결합분류를 현재 KOSIS 표에서 단일 코드로 확정하지 못함",
}


def read_cache(path):
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_cache(path, cache):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def series_key(config):
    return "|".join(str(config.get(key, "")) for key in ("org_id", "tbl_id", "obj_l1", "obj_l2", "itm_id", "prd_se"))


def to_float(value):
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def fetch_series(config, cache):
    key = series_key(config)
    if key in cache:
        return cache[key]
    extra = {"objL2": config["obj_l2"]} if config.get("obj_l2") else {}
    rows = get_stat_data(
        config["org_id"], config["tbl_id"], config["obj_l1"], config["itm_id"],
        config["prd_se"], new_est_prd_cnt=500, **extra,
    )
    if rows and rows[0].get("err"):
        raise RuntimeError(rows[0].get("errMsg") or str(rows[0]))
    compact = [
        {"period": str(row.get("PRD_DE", "")), "value": row.get("DT"), "unit": row.get("UNIT_NM", "")}
        for row in rows
    ]
    cache[key] = compact
    write_cache(GOLD_CACHE_PATH, cache)
    return compact


def period_value(series, period):
    for row in series:
        if row["period"] == period:
            return to_float(row["value"]), row.get("unit", "")
    return None, ""


def gold_verify(config, cache):
    series = fetch_series(config, cache)
    mode = config["mode"]
    unit = ""
    current = previous = None
    if mode in {"SUM_CHANGE", "AVG_CHANGE"}:
        current_values = [period_value(series, period)[0] for period in config["target_periods"]]
        previous_values = [period_value(series, period)[0] for period in config["prev_periods"]]
        if any(value is None for value in current_values):
            return None, None, None, unit, "목표 기간 값 없음"
        if any(value is None for value in previous_values):
            return None, None, None, unit, "비교 기간 값 없음"
        if mode == "SUM_CHANGE":
            current = sum(current_values)
            previous = sum(previous_values)
        else:
            current = sum(current_values) / len(current_values)
            previous = sum(previous_values) / len(previous_values)
        actual = (current - previous) / previous * 100 if previous else None
    else:
        current, unit = period_value(series, config["target_period"])
        if current is None:
            return None, None, None, unit, "목표 시점 값 없음"
        if mode == "LEVEL":
            actual = current
        else:
            previous, _ = period_value(series, config["prev_period"])
            if previous is None:
                return None, current, None, unit, "비교 시점 값 없음"
            if mode == "POINT_CHANGE":
                actual = current - previous
            else:
                actual = (current - previous) / previous * 100 if previous else None
    if actual is None:
        return None, current, previous, unit, "계산값 없음"
    target = config["target_number"]
    if mode == "LEVEL" and abs(target) >= 100:
        diff = abs(actual - target) / abs(target)
        verdict = "일치" if diff <= 0.005 else "불일치"
    else:
        diff = abs(actual - target)
        verdict = "일치" if diff <= config["tolerance"] else "불일치"
    return actual, current, previous, unit, verdict


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def same(auto_value, gold_value):
    return str(auto_value or "") == str(gold_value or "")


def rate(correct, denominator):
    return correct / denominator if denominator else 0.0


def main():
    is_development = "development" in OUTPUT_STEM.lower()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with SELECTION.open(encoding="utf-8-sig", newline="") as handle:
        selection = list(csv.DictReader(handle))
    if len(selection) != 100:
        raise RuntimeError(f"holdout rows={len(selection)}")

    exclusion_by_id = {}
    for category, claim_ids in EXCLUSION_GROUPS.items():
        for claim_id in claim_ids:
            exclusion_by_id[claim_id] = category
    selected_ids = {row["claim_id"] for row in selection}
    labelled_ids = set(ELIGIBLE) | set(exclusion_by_id)
    if selected_ids != labelled_ids:
        raise RuntimeError(f"라벨 누락/초과: missing={selected_ids - labelled_ids}, extra={labelled_ids - selected_ids}")

    gold_cache = read_cache(GOLD_CACHE_PATH)
    auto_cache = codebook.read_cache()
    rows = []
    for source in selection:
        out = dict(source)
        claim_id = source["claim_id"]
        gold_config = ELIGIBLE.get(claim_id)
        if gold_config:
            out["gold_verifiable"] = "Y"
            out["gold_exclusion_reason"] = ""
            out["gold_exclusion_note"] = ""
            for key in ("org_id", "tbl_id", "obj_l1", "obj_l2", "itm_id", "prd_se", "target_number", "target_period", "prev_period", "mode", "note"):
                out[f"gold_{key}"] = gold_config.get(key, "")
            if gold_config["target_periods"]:
                out["gold_target_periods"] = ";".join(gold_config["target_periods"])
                out["gold_prev_periods"] = ";".join(gold_config["prev_periods"])
            else:
                out["gold_target_periods"] = ""
                out["gold_prev_periods"] = ""
            try:
                actual, current, previous, unit, verdict = gold_verify(gold_config, gold_cache)
                if actual is None:
                    raise ValueError(verdict)
                out["gold_api_success"] = "Y"
                out["gold_actual_number"] = actual
                out["gold_current_value"] = current
                out["gold_previous_value"] = previous
                out["gold_unit"] = unit
                out["gold_verdict"] = verdict
                out["gold_api_error"] = ""
                out["gold_evidence"] = f"{gold_config['tbl_id']} {gold_config['target_period']} actual={actual}; target={gold_config['target_number']}"
            except Exception as exc:
                out["gold_api_success"] = "N"
                out["gold_actual_number"] = ""
                out["gold_current_value"] = ""
                out["gold_previous_value"] = ""
                out["gold_unit"] = ""
                out["gold_verdict"] = "판단불가"
                out["gold_api_error"] = str(exc)
                out["gold_evidence"] = f"{gold_config['tbl_id']} 매핑은 확정했으나 {exc}"
        else:
            category = exclusion_by_id[claim_id]
            out["gold_verifiable"] = "N"
            out["gold_exclusion_reason"] = category
            out["gold_exclusion_note"] = EXCLUSION_REASON[category]
            for key in (
                "org_id", "tbl_id", "obj_l1", "obj_l2", "itm_id", "prd_se", "target_number",
                "target_period", "prev_period", "mode", "note", "target_periods", "prev_periods",
            ):
                out[f"gold_{key}"] = ""
            out["gold_api_success"] = "N/A"
            out["gold_actual_number"] = ""
            out["gold_current_value"] = ""
            out["gold_previous_value"] = ""
            out["gold_unit"] = ""
            out["gold_verdict"] = "판단불가"
            out["gold_api_error"] = ""
            out["gold_evidence"] = EXCLUSION_REASON[category]

        auto_config, auto_exclusion = codebook.map_by_codebook(source)
        if auto_config:
            out["auto_decision"] = "검증가능"
            out["auto_exclusion_reason"] = ""
            for key in ("org_id", "tbl_id", "obj_l1", "obj_l2", "itm_id", "prd_se", "target_number", "target_period", "prev_period", "mode", "note"):
                out[f"auto_{key}"] = auto_config.get(key, "")
            try:
                actual, current, previous, unit, verdict = codebook.verify(auto_config, auto_cache)
                if actual is None:
                    raise ValueError(verdict)
                out["auto_api_success"] = "Y"
                out["auto_actual_number"] = actual
                out["auto_verdict"] = verdict
                out["auto_api_error"] = ""
            except Exception as exc:
                out["auto_api_success"] = "N"
                out["auto_actual_number"] = ""
                out["auto_verdict"] = "판단불가"
                out["auto_api_error"] = str(exc)
        elif auto_exclusion:
            out["auto_decision"] = "검증불가"
            out["auto_exclusion_reason"] = auto_exclusion[0]
            for key in ("org_id", "tbl_id", "obj_l1", "obj_l2", "itm_id", "prd_se", "target_number", "target_period", "prev_period", "mode", "note"):
                out[f"auto_{key}"] = ""
            out["auto_api_success"] = "N/A"
            out["auto_actual_number"] = ""
            out["auto_verdict"] = "판단불가"
            out["auto_api_error"] = ""
        else:
            out["auto_decision"] = "보류"
            out["auto_exclusion_reason"] = ""
            for key in ("org_id", "tbl_id", "obj_l1", "obj_l2", "itm_id", "prd_se", "target_number", "target_period", "prev_period", "mode", "note"):
                out[f"auto_{key}"] = ""
            out["auto_api_success"] = "N/A"
            out["auto_actual_number"] = ""
            out["auto_verdict"] = ""
            out["auto_api_error"] = ""

        gold_pred = "검증가능" if out["gold_verifiable"] == "Y" else "검증불가"
        out["eligibility_correct"] = "Y" if out["auto_decision"] == gold_pred else "N"
        if gold_config and auto_config:
            out["table_correct"] = "Y" if same(auto_config["org_id"], gold_config["org_id"]) and same(auto_config["tbl_id"], gold_config["tbl_id"]) else "N"
            out["item_correct"] = "Y" if all(same(auto_config[key], gold_config[key]) for key in ("obj_l1", "obj_l2", "itm_id")) else "N"
            out["period_correct"] = "Y" if same(auto_config["prd_se"], gold_config["prd_se"]) and same(auto_config["target_period"], gold_config["target_period"]) else "N"
            out["item_period_correct"] = "Y" if out["item_correct"] == "Y" and out["period_correct"] == "Y" else "N"
        elif gold_config:
            out["table_correct"] = "N"
            out["item_correct"] = "N"
            out["period_correct"] = "N"
            out["item_period_correct"] = "N"
        else:
            out["table_correct"] = "N/A"
            out["item_correct"] = "N/A"
            out["period_correct"] = "N/A"
            out["item_period_correct"] = "N/A"
        out["verdict_correct"] = "Y" if out["auto_verdict"] and out["auto_verdict"] == out["gold_verdict"] else "N"
        rows.append(out)

    fields = list(rows[0].keys())
    write_csv(output_file("evaluation.csv"), rows, fields)
    write_csv(output_file("manual_labels.csv"), rows, fields)

    eligible_rows = [row for row in rows if row["gold_verifiable"] == "Y"]
    covered_rows = [row for row in rows if row["auto_decision"] != "보류"]
    auto_mapped = [row for row in rows if row["auto_decision"] == "검증가능"]
    auto_api_rows = [row for row in auto_mapped if row["auto_api_success"] == "Y"]
    metrics = []

    def add_metric(name, correct, denominator, definition):
        metrics.append({"metric": name, "correct_or_success": correct, "denominator": denominator, "rate": rate(correct, denominator), "definition": definition})

    add_metric("홀드아웃 전체", len(rows), len(rows), "기존 골드 claim/article 중복 0, 분야별 20건")
    add_metric("자동결정 커버리지", len(covered_rows), len(rows), "검증가능 또는 검증불가를 자동 결정한 비율; 보류 제외")
    add_metric("검증 가능 여부 엄격 정확도", sum(row["eligibility_correct"] == "Y" for row in rows), len(rows), "보류를 오답으로 포함")
    add_metric("검증 가능 여부 결정구간 정확도", sum(row["eligibility_correct"] == "Y" for row in covered_rows), len(covered_rows), "자동결정한 행만 평가")
    add_metric("통계표 매핑 엄격 정확도", sum(row["table_correct"] == "Y" for row in eligible_rows), len(eligible_rows), "골드 검증 가능 전체가 분모; 보류는 오답")
    add_metric("항목 매핑 엄격 정확도", sum(row["item_correct"] == "Y" for row in eligible_rows), len(eligible_rows), "obj_l1+obj_l2+itm_id")
    add_metric("시점 매핑 엄격 정확도", sum(row["period_correct"] == "Y" for row in eligible_rows), len(eligible_rows), "주기+목표 시점")
    add_metric("항목·시점 결합 엄격 정확도", sum(row["item_period_correct"] == "Y" for row in eligible_rows), len(eligible_rows), "80% 품질 게이트 기준")
    add_metric("자동매핑 통계표 정밀도", sum(row["table_correct"] == "Y" for row in auto_mapped), len(auto_mapped), "자동 검증가능 판정 행 중 올바른 표")
    add_metric("자동매핑 항목·시점 정밀도", sum(row["item_period_correct"] == "Y" for row in auto_mapped), len(auto_mapped), "자동 검증가능 판정 행 중 올바른 항목·시점")
    add_metric("자동매핑 API 성공률", len(auto_api_rows), len(auto_mapped), "자동 검증가능 판정 행 중 값 조회 성공")
    add_metric("최종 판정 엄격 일치율", sum(row["verdict_correct"] == "Y" for row in rows), len(rows), "보류를 오답으로 포함한 100건 기준")
    add_metric("자동결정 최종 판정 일치율", sum(row["verdict_correct"] == "Y" for row in covered_rows), len(covered_rows), "자동결정한 행만 평가")
    add_metric("골드 API 성공률", sum(row["gold_api_success"] == "Y" for row in eligible_rows), len(eligible_rows), "수동 확정 매핑의 현재 KOSIS 값 조회")
    write_csv(output_file("metrics.csv"), metrics, ["metric", "correct_or_success", "denominator", "rate", "definition"])

    domain_rows = []
    for domain in ("물가", "고용", "무역", "인구", "소매"):
        subset = [row for row in rows if row["holdout_domain"] == domain]
        eligible_subset = [row for row in subset if row["gold_verifiable"] == "Y"]
        mapped_subset = [row for row in subset if row["auto_decision"] == "검증가능"]
        domain_rows.append({
            "domain": domain,
            "sample_count": len(subset),
            "gold_verifiable_count": len(eligible_subset),
            "auto_decision_coverage": rate(sum(row["auto_decision"] != "보류" for row in subset), len(subset)),
            "eligibility_strict_accuracy": rate(sum(row["eligibility_correct"] == "Y" for row in subset), len(subset)),
            "table_strict_accuracy": rate(sum(row["table_correct"] == "Y" for row in eligible_subset), len(eligible_subset)),
            "item_period_strict_accuracy": rate(sum(row["item_period_correct"] == "Y" for row in eligible_subset), len(eligible_subset)),
            "auto_mapping_precision": rate(sum(row["item_period_correct"] == "Y" for row in mapped_subset), len(mapped_subset)),
        })
    write_csv(output_file("metrics_by_domain.csv"), domain_rows, list(domain_rows[0].keys()))

    errors = []
    for row in rows:
        error_types = []
        if row["eligibility_correct"] == "N":
            error_types.append("검증가능여부")
        if row["gold_verifiable"] == "Y" and row["table_correct"] == "N":
            error_types.append("통계표")
        if row["gold_verifiable"] == "Y" and row["item_correct"] == "N":
            error_types.append("항목")
        if row["gold_verifiable"] == "Y" and row["period_correct"] == "N":
            error_types.append("시점")
        if row["verdict_correct"] == "N":
            error_types.append("최종판정")
        if error_types:
            out = dict(row)
            out["error_types"] = ";".join(error_types)
            if row["auto_decision"] == "보류" and row["gold_verifiable"] == "Y":
                out["error_cause"] = "코드북 미지원 또는 엄격 규칙에 따른 검증가능 행 보류"
            elif row["auto_decision"] == "검증가능" and row["gold_verifiable"] == "N":
                out["error_cause"] = "비검증 대상을 통계표에 연결한 과검증"
            elif row["auto_decision"] == "검증불가" and row["gold_verifiable"] == "Y":
                out["error_cause"] = "검증가능 대상을 비검증으로 오분류"
            else:
                out["error_cause"] = "매핑 또는 판정 불일치"
            errors.append(out)
    write_csv(output_file("error_analysis.csv"), errors, list(errors[0].keys()))

    false_negative_rows = [
        row for row in rows
        if row["gold_verifiable"] == "Y" and row["auto_decision"] == "검증불가"
    ]
    eligible_hold_counts = Counter(
        row["holdout_domain"] for row in rows
        if row["gold_verifiable"] == "Y" and row["auto_decision"] == "보류"
    )
    ineligible_hold_counts = Counter(
        row["gold_exclusion_reason"] for row in rows
        if row["gold_verifiable"] == "N" and row["auto_decision"] == "보류"
    )
    auto_api_miss = sum(
        row["auto_decision"] == "검증가능" and row["auto_api_success"] != "Y"
        for row in rows
    )
    gold_api_miss = sum(
        row["gold_verifiable"] == "Y" and row["gold_api_success"] != "Y"
        for row in rows
    )
    backlog = []
    if false_negative_rows:
        backlog.append({
            "priority": "P0",
            "scope": "검증 가능 여부 오분류",
            "count": len(false_negative_rows),
            "evidence": ";".join(row["claim_id"] for row in false_negative_rows),
            "recommended_action": "민간·정책 키워드를 문장 전체의 즉시 배제 조건으로 쓰지 말고, 명시적 KOSIS 지표 매핑을 먼저 시도한 뒤 데이터 출처가 민간일 때만 배제",
            "evaluation_policy": "규칙 수정 후 현재 홀드아웃은 개발 자료로 전환하고 새 독립 홀드아웃에서 재측정",
        })
    for domain in ("물가", "고용", "무역", "인구", "소매"):
        count = eligible_hold_counts.get(domain, 0)
        if count:
            backlog.append({
                "priority": "P1",
                "scope": f"{domain} 검증가능 매핑 커버리지",
                "count": count,
                "evidence": ";".join(
                    row["claim_id"] for row in rows
                    if row["holdout_domain"] == domain
                    and row["gold_verifiable"] == "Y"
                    and row["auto_decision"] == "보류"
                ),
                "recommended_action": "골드 통계표·항목·시점 조합을 반복 지표 코드북 후보로 등록하고 다중 수치·지역·전월/전년동월 문맥 규칙을 단위 테스트",
                "evaluation_policy": "현재 홀드아웃에서는 오류 분석만 수행; 수정 성능은 새 독립 표본에서 평가",
            })
    for reason in ("KOSIS 미제공", "정보 부족", "지역·분류 불일치"):
        count = ineligible_hold_counts.get(reason, 0)
        if count:
            backlog.append({
                "priority": "P1",
                "scope": f"검증불가 자동 분류: {reason}",
                "count": count,
                "evidence": ";".join(
                    row["claim_id"] for row in rows
                    if row["gold_exclusion_reason"] == reason and row["auto_decision"] == "보류"
                ),
                "recommended_action": "검증불가 사유별 표현 사전과 우선순위를 분리하고 과배제 방지용 양성·음성 단위 테스트 추가",
                "evaluation_policy": "자동 확정은 높은 정밀도를 유지하고 애매한 문장은 계속 보류",
            })
    if auto_api_miss or gold_api_miss:
        backlog.append({
            "priority": "P2",
            "scope": "KOSIS API 최신 시점 조회",
            "count": gold_api_miss,
            "evidence": f"자동매핑 실패 {auto_api_miss}건; 골드매핑 실패 {gold_api_miss}건",
            "recommended_action": "출생아 등 최신 잠정치 표를 별도 탐색하고, 표 갱신 지연은 매핑 오류와 분리해 재시도 큐로 관리",
            "evaluation_policy": "API 성공률과 매핑 정확도를 별도 지표로 계속 보고",
        })
    write_csv(
        output_file("improvement_backlog.csv"),
        backlog,
        ["priority", "scope", "count", "evidence", "recommended_action", "evaluation_policy"],
    )

    metric_map = {row["metric"]: row for row in metrics}
    gate_rate = metric_map["항목·시점 결합 엄격 정확도"]["rate"]
    decision_counts = Counter(row["auto_decision"] for row in rows)
    gold_verdicts = Counter(row["gold_verdict"] for row in rows)
    auto_verdicts = Counter(row["auto_verdict"] or "보류" for row in rows)
    exclusion_counts = Counter(row["gold_exclusion_reason"] for row in rows if row["gold_verifiable"] == "N")
    report = [
        f"# KOSIS 홀드아웃 100건 평가 - {OUTPUT_STEM}",
        "",
        "## 결론",
        "",
        "- 기존 개발용 골드 100건과 claim_id 및 article_id 중복 0건",
        f"- 평가 코드북: `{CODEBOOK_FILE}`",
        "- 물가·고용·무역·인구·소매 각 20건",
        f"- 골드 검증 가능: {len(eligible_rows)}건 / 검증 불가: {len(rows) - len(eligible_rows)}건 ({dict(exclusion_counts)})",
        f"- 자동 결정: {dict(decision_counts)}",
        f"- 항목·시점 결합 엄격 정확도: {gate_rate:.1%}",
        f"- 80% 품질 기준: {'개발셋 통과(독립 재평가 필요)' if gate_rate >= 0.8 and is_development else ('통과' if gate_rate >= 0.8 else '실패')}",
        "- 이 표본의 오류를 보고 코드북을 수정했으므로 더 이상 독립 평가셋이 아니다." if is_development else "- 이 평가는 코드북을 수정하지 않은 독립 표본 결과다.",
        "- 게이트 실패 시 1,281건 수동검토 큐의 자동 확정을 확대하지 않고 코드북을 보완한다.",
        "- 인구 분야는 골드 기사 제외 후 남은 독립 기사 수가 적어 8개 신규 기사에서 20개 서로 다른 주장 문장을 사용했다.",
        "",
        "## 지표",
        "",
        "| 지표 | 결과 | 정의 |",
        "| --- | ---: | --- |",
    ]
    for metric in metrics[1:]:
        report.append(f"| {metric['metric']} | {metric['correct_or_success']}/{metric['denominator']} ({metric['rate']:.1%}) | {metric['definition']} |")
    report.extend([
        "",
        "## 판정 분포",
        "",
        f"- 골드: {dict(gold_verdicts)}",
        f"- 자동: {dict(auto_verdicts)}",
        "",
        "## 오류 요약",
        "",
        f"- 자동 보류: {decision_counts.get('보류', 0)}건 (검증 가능 {sum(eligible_hold_counts.values())}건, 검증 불가 {sum(ineligible_hold_counts.values())}건)",
        f"- 검증 가능 대상을 검증 불가로 오분류: {len(false_negative_rows)}건 ({'; '.join(row['claim_id'] for row in false_negative_rows) or '없음'})",
        f"- 검증 가능 보류의 분야별 분포: {dict(eligible_hold_counts)}",
        f"- 검증 불가 보류의 사유별 분포: {dict(ineligible_hold_counts)}",
        f"- API 미조회: 자동 매핑 {auto_api_miss}건, 골드 매핑 {gold_api_miss}건",
        "",
        "## 다음 단계",
        "",
        "1. 개발이 끝난 코드북을 동결하고 현재 표본과 겹치지 않는 새 표본을 수동 확정한다.",
        "2. 새 독립 표본에서 항목·시점 결합 정확도 80%를 다시 측정한다.",
        "3. 최신 출생 잠정치 표 탐색과 API 재시도 큐를 별도 구현한다.",
        "4. 새 독립 평가가 80%를 통과하기 전까지 1,281건 자동 확정 확대는 보류한다.",
        "",
        "## 산출물",
        "",
        f"- `{OUTPUT_STEM}_evaluation.csv`: 골드 라벨과 코드북 예측 전체",
        f"- `{OUTPUT_STEM}_metrics.csv`: 전체 성능 지표",
        f"- `{OUTPUT_STEM}_metrics_by_domain.csv`: 분야별 성능",
        f"- `{OUTPUT_STEM}_error_analysis.csv`: 오류 행과 원인",
        f"- `{OUTPUT_STEM}_improvement_backlog.csv`: 개선 우선순위",
    ])
    output_file("report.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    print(f"eligible={len(eligible_rows)} exclusions={dict(exclusion_counts)}")
    print(f"auto_decisions={dict(decision_counts)}")
    print(f"gold_verdicts={dict(gold_verdicts)} auto_verdicts={dict(auto_verdicts)}")
    for metric in metrics:
        print(f"{metric['metric']}={metric['correct_or_success']}/{metric['denominator']} ({metric['rate']:.1%})")
    print(OUTPUT_DIR.resolve())


if __name__ == "__main__":
    main()
