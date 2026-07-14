"""
enriched 2,001건 자동매핑 보정 스크립트.

목적:
- 기존 자동매핑에서 명백히 오염되는 tbl_id를 빠르게 정리한다.
- 정책/전망/순위/기간 숫자는 KOSIS 직접 검증 대상에서 제외하고 tbl_id를 비운다.
- GDP 등 다른 분야 문장에 무역/물가 tbl_id가 붙은 경우 올바른 tbl_id로 바꾸거나 비운다.
- 전체 수출입 문장은 품목별 세부코드가 아니라 국가별 전체 수출입 코드로 보정한다.

입력:
- outputs/bteam_review/bteam_kosis_review_enriched.csv

출력:
- 같은 파일을 갱신한다. 재실행 전 원본 백업은 outputs/bteam_review/bteam_kosis_review_enriched_before_remap.csv 로 남긴다.
"""

import csv
import re
import shutil
import sys
from pathlib import Path

csv.field_size_limit(sys.maxsize)

BASE = Path("outputs/bteam_review")
INPUT = BASE / "bteam_kosis_review_enriched.csv"
BACKUP = BASE / "bteam_kosis_review_enriched_before_remap.csv"

POLICY_RE = re.compile(r"관세|공약|정책|LTV|DSR|금리|소득\s*130%|우선공급|제도")
FORECAST_RE = re.compile(r"전망|예상|예측|가능성이|할 것|우려|추산|목표|계획")
PERIOD_UNIT_RE = re.compile(r"^(개|개월|년|월|일|분|위)$")
TOTAL_TRADE_RE = re.compile(r"전체\s*(수출|수입)|한 해\s*전체\s*(수출|수입)|한국의\s*\d{4}년\s*(수출|수입)|작년\s*(한국의\s*)?(수출액|수입액)")
GDP_RE = re.compile(r"국내총생산|GDP")
PRICE_RE = re.compile(r"소비자물가|물가\s*상승률|물가|가공식품|외식|가격|값")
TRADE_WORD_RE = re.compile(r"수출|수입|무역수지|대미|대중|교역")
ITEM_TRADE_RE = re.compile(r"반도체|자동차|차부품|부품|선박|화장품|바이오|의약품|농수산|식품|석유|철강|디스플레이|이차전지|배터리|품목")
IMPORT_RE = re.compile(r"수입")
EXPORT_RE = re.compile(r"수출")
US_RE = re.compile(r"대미|미국")
CN_RE = re.compile(r"대중|중국")
JP_RE = re.compile(r"대일|일본")
TRADE_TOTAL_TBL = "DT_1R11006_FRM101"
TRADE_TOTAL_ORG = "360"
TRADE_COUNTRY_CODES = {
    "US": "13102103829E.US",
    "CN": "13102103829E.CN",
    "JP": "13102103829E.JP",
    "ALL": "13102103829E.00",
}
TRADE_ITEMS = {
    "export": "13103103829T1",
    "import": "13103103829T2",
}
GDP_TABLE = {
    "org_id": "301",
    "tbl_id": "DT_200Y113",
    "prd_se": "Y",
}
CPI_RATE_TABLE = {
    "org_id": "101",
    "tbl_id": "DT_1J22042",
    "obj_l1": "0",
    "itm_id": "T03",
    "prd_se": "M",
}
CPI_INDEX_TABLE = {
    "org_id": "101",
    "tbl_id": "DT_1J22003",
    "obj_l1": "0",
    "itm_id": "T1",
    "prd_se": "M",
}


def append_note(row, note):
    old = row.get("reviewer_note", "")
    if note in old:
        return
    row["reviewer_note"] = f"{old} | {note}" if old else note


def clear_kosis_params(row, reason):
    for key in ("org_id", "tbl_id", "obj_l1", "itm_id", "prd_se"):
        row[key] = ""
    append_note(row, f"자동재매핑: tbl_id 제거 - {reason}")


def mark_unverifiable(row, reason):
    row["verifiable"] = "False"
    if row.get("claim_type") not in {"순위", "전망·예측", "개별상품가격"}:
        row["claim_type"] = "전망·예측"
    clear_kosis_params(row, reason)


def set_table(row, table, reason, clear_codes=False):
    row["org_id"] = table.get("org_id", "")
    row["tbl_id"] = table.get("tbl_id", "")
    row["prd_se"] = table.get("prd_se", row.get("prd_se", ""))
    row["obj_l1"] = "" if clear_codes else table.get("obj_l1", row.get("obj_l1", ""))
    row["itm_id"] = "" if clear_codes else table.get("itm_id", row.get("itm_id", ""))
    append_note(row, f"자동재매핑: tbl_id 보정 - {reason}")


def remap_trade_total(row):
    text = row.get("claim_text", "")
    if row.get("metric") != "무역지표":
        return False
    if not TOTAL_TRADE_RE.search(text):
        return False

    country = "ALL"
    if US_RE.search(text):
        country = "US"
    elif CN_RE.search(text):
        country = "CN"
    elif JP_RE.search(text):
        country = "JP"

    item = "import" if IMPORT_RE.search(text) and not EXPORT_RE.search(text) else "export"

    row["org_id"] = TRADE_TOTAL_ORG
    row["tbl_id"] = TRADE_TOTAL_TBL
    row["obj_l1"] = TRADE_COUNTRY_CODES[country]
    row["itm_id"] = TRADE_ITEMS[item]
    if not row.get("prd_se"):
        row["prd_se"] = "Y"
    append_note(row, f"자동재매핑: 전체/국가 수출입 문장 -> 국가별 수출입 표({country}, {item})")
    return True


def remap_by_domain(row):
    text = row.get("claim_text", "")
    tbl_id = row.get("tbl_id", "")

    if GDP_RE.search(text):
        set_table(row, GDP_TABLE, "GDP/국내총생산 문장 -> 국내총생산과 지출 표, 세부 항목 코드는 추가 확인 필요", clear_codes=True)
        return "gdp_table_remap"

    if PRICE_RE.search(text) and tbl_id.startswith("DT_1R"):
        table = CPI_RATE_TABLE if row.get("target_unit") == "%" or row.get("claim_type") == "증감률" else CPI_INDEX_TABLE
        set_table(row, table, "가격/물가 문장인데 무역표가 붙어 소비자물가 표로 보정")
        return "price_table_remap"

    if row.get("metric") == "무역지표" and tbl_id.startswith("DT_1J") and not PRICE_RE.search(text):
        clear_kosis_params(row, "무역지표인데 물가표가 붙음. 후보 재검색 필요")
        return "trade_price_mismatch_cleared"

    if row.get("metric") in {"비율·증감률", "물가지표"} and tbl_id.startswith("DT_1R") and not TRADE_WORD_RE.search(text):
        clear_kosis_params(row, "일반 비율/물가 문장인데 무역표가 붙음. 후보 재검색 필요")
        return "ratio_trade_mismatch_cleared"

    if row.get("metric") == "무역지표" and tbl_id == TRADE_TOTAL_TBL and ITEM_TRADE_RE.search(text) and not TOTAL_TRADE_RE.search(text):
        # 품목 문장인데 국가별 표로 붙은 경우. 품목별 후보가 있으면 품목별 표로 되돌리되
        # 세부 품목 코드는 자동 확정하지 않는다.
        row["org_id"] = "360"
        row["tbl_id"] = "DT_1R11001_FRM101"
        row["obj_l1"] = ""
        row["itm_id"] = TRADE_ITEMS["import"] if IMPORT_RE.search(text) and not EXPORT_RE.search(text) else TRADE_ITEMS["export"]
        append_note(row, "자동재매핑: 품목 수출입 문장 -> 품목별 수출입 표, 품목 코드는 추가 확인 필요")
        return "item_trade_remap"

    return None


def main():
    if not BACKUP.exists():
        shutil.copy2(INPUT, BACKUP)

    with open(INPUT, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames

    counts = {
        "policy_unverifiable": 0,
        "forecast_unverifiable": 0,
        "period_number_unverifiable": 0,
        "trade_total_remap": 0,
        "nonverifiable_tbl_cleared": 0,
        "gdp_table_remap": 0,
        "price_table_remap": 0,
        "trade_price_mismatch_cleared": 0,
        "ratio_trade_mismatch_cleared": 0,
        "item_trade_remap": 0,
    }

    for row in rows:
        text = row.get("claim_text", "")
        target_unit = str(row.get("target_unit", "")).strip()

        if row.get("claim_type") in {"순위", "전망·예측", "개별상품가격"}:
            row["verifiable"] = "False"
            clear_kosis_params(row, "기존 claim_type 기준 KOSIS 직접 검증 제외")
            counts["nonverifiable_tbl_cleared"] += 1

        if POLICY_RE.search(text):
            mark_unverifiable(row, "정책/제도 숫자")
            counts["policy_unverifiable"] += 1
            continue

        if FORECAST_RE.search(text):
            mark_unverifiable(row, "전망/예측/추산 문장")
            counts["forecast_unverifiable"] += 1
            continue

        if PERIOD_UNIT_RE.match(target_unit):
            mark_unverifiable(row, "기간/순서 숫자가 target으로 잡힘")
            counts["period_number_unverifiable"] += 1
            continue

        domain_result = remap_by_domain(row)
        if domain_result:
            counts[domain_result] += 1
            continue

        if remap_trade_total(row):
            counts["trade_total_remap"] += 1

    with open(INPUT, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"완료 -> {INPUT}")
    print(f"백업 -> {BACKUP}")
    print(counts)


if __name__ == "__main__":
    main()
