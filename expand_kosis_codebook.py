"""Apply the validated KOSIS codebook to all 1,643 recheck rows in 200-row batches."""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


REPO = Path(__file__).resolve().parent
INPUT = REPO / "outputs/bteam_review/final_verified_filled_2001_remapped_v6.csv"
OUTPUT_DIR = REPO / "outputs/bteam_gold"
CACHE_PATH = OUTPUT_DIR / "expansion_api_cache.json"

sys.path.insert(0, str(REPO))
os.chdir(REPO)
from kosis_api_test import get_stat_data  # noqa: E402


FORECAST_RE = re.compile(r"전망|예상|예측|목표|계획|가능성|것으로\s*(?:봤|내다|예상)|할\s*것")
CONTRIBUTION_RE = re.compile(r"기여도|끌어올렸|끌어내렸")
FOREIGN_RE = re.compile(r"미국|미\s|중국|일본|독일|뉴질랜드|베트남|유럽|영국|프랑스|캐나다|호주")
PRIVATE_RE = re.compile(r"설문|응답\s*기업|개별\s*기업|소비쿠폰|관세율|국채|기대\s*인플레이션")
PRICE_SOURCE_RE = re.compile(
    r"한국소비자원|농수산식품유통공사|\baT\b|소매\s*가격|한\s*통\s*가격|한\s*가마|생필품\s*가격"
)
PERCENT_RE = re.compile(r"(?<!\d)([-+−–]?\d+(?:\.\d+)?)\s*%")
POINT_RE = re.compile(r"%\s*(?:포인트|p)\b", re.IGNORECASE)
EXPLICIT_YM_RE = re.compile(r"(20\d{2})년\s*(\d{1,2})월")
EXPLICIT_YEAR_RE = re.compile(r"(20\d{2})년")
MONTH_RE = re.compile(r"(?<!\d)(1[0-2]|[1-9])월")
PARTIAL_PERIOD_RE = re.compile(
    r"\d{1,2}\s*[~∼~-]\s*\d{1,2}월|\d{1,2}월부터\s*\d{1,2}월|누적|분기|상반기|하반기|"
    r"\d+\s*년\s*전|20\d{2}년[^.]{0,25}[~∼]20\d{2}년"
)
RATIO_OR_RANK_RE = re.compile(
    r"비중|점유율|차지|순위|상위|가운데|절반|비율|구성비|역대|연속|만에|개월\s*만|%\s*대|같았|동일"
)
MULTI_METRIC_RE = re.compile(r"각각|동반|및|와\s+출생아|과\s+출생아")
REGION_RE = re.compile(r"서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주")
CPI_DETAIL_RE = re.compile(r"축산물|농산물|수산물|쌀|소주|공공서비스|개인서비스|집세|전기|가스|수도|통신")
TRADE_DETAIL_RE = re.compile(
    r"대미|대중|대일|대유럽|국가별|지역별|품목|선박|자동차|수입차|화장품|반도체|원유|에너지|"
    r"K푸드|농식품|ICT|중간재|소비재|자본재|수주|투자|관세|무역수지|흑자|적자|WTO"
)


def final_status(row):
    return (
        row.get("remap_final_status")
        or row.get("manual_final_status")
        or row.get("audit_status")
        or row.get("refined_final_status")
        or ""
    )


def to_float(value):
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def month_shift(year, month, delta):
    index = year * 12 + month - 1 + delta
    return index // 12, index % 12 + 1


def article_date(row):
    try:
        return datetime.strptime((row.get("date") or "")[:10], "%Y-%m-%d")
    except ValueError:
        return None


def infer_period(row, period_type):
    text = row.get("claim_text", "") or ""
    date = article_date(row)
    if period_type == "M":
        match = EXPLICIT_YM_RE.search(text)
        if match:
            if date and "지난달" in text and match.start() > text.find("지난달") and "비교" in text:
                year, month = month_shift(date.year, date.month, -1)
                return f"{year:04d}{month:02d}"
            return f"{int(match.group(1)):04d}{int(match.group(2)):02d}"
        month_match = MONTH_RE.search(text)
        if month_match:
            month = int(month_match.group(1))
            if date:
                prefix = text[max(0, month_match.start() - 8):month_match.start()]
                if re.search(r"(?:지난해|작년)\s*$", prefix):
                    year = date.year - 1
                else:
                    year = date.year - 1 if month > date.month else date.year
                return f"{year:04d}{month:02d}"
        if date and "지난달" in text:
            year, month = month_shift(date.year, date.month, -1)
            return f"{year:04d}{month:02d}"
        return ""

    explicit_years = [int(value) for value in EXPLICIT_YEAR_RE.findall(text)]
    if explicit_years:
        if "지난해" in text or "작년" in text:
            return str(date.year - 1) if date else str(explicit_years[0])
        return str(explicit_years[0])
    if date and ("지난해" in text or "작년" in text):
        return str(date.year - 1)
    return ""


def previous_period(target_period, period_type, text):
    if not target_period:
        return ""
    if period_type == "M":
        year, month = int(target_period[:4]), int(target_period[4:6])
        if re.search(r"전월|전달|직전\s*달", text):
            year, month = month_shift(year, month, -1)
        else:
            year -= 1
        return f"{year:04d}{month:02d}"
    return str(int(target_period[:4]) - 1)


def extract_single_percent(row):
    values = []
    for raw in PERCENT_RE.findall(row.get("claim_text", "") or ""):
        value = to_float(raw.replace("−", "-").replace("–", "-"))
        if value is not None:
            values.append(value)
    unique = []
    for value in values:
        if value not in unique:
            unique.append(value)
    if len(unique) == 1:
        return unique[0]
    return None


def domain(row):
    table = row.get("tbl_id", "") or ""
    metric = row.get("metric", "") or ""
    text = row.get("claim_text", "") or ""
    if table.startswith("DT_1R11") or metric == "무역지표":
        return "무역"
    if table.startswith("DT_1DA") or metric == "고용지표":
        return "고용"
    if "B8000" in table or metric == "인구지표":
        return "인구"
    if table in {"DT_1K41012", "DT_1K41018", "DT_1KC2020"} or metric == "판매·생산량" or "소매" in text:
        return "소매"
    if table.startswith("DT_1J22") or metric == "물가지표":
        return "물가"
    return "기타"


def mapping(org, table, obj1, item, period, target, target_period, mode, *, obj2="", prev="", note=""):
    return {
        "org_id": org,
        "tbl_id": table,
        "obj_l1": obj1,
        "obj_l2": obj2,
        "itm_id": item,
        "prd_se": period,
        "target_number": target,
        "target_period": target_period,
        "prev_period": prev,
        "mode": mode,
        "note": note,
    }


def classify_nonverifiable(row, row_domain):
    text = row.get("claim_text", "") or ""
    context = f"{row.get('title', '')} {text}"
    if CONTRIBUTION_RE.search(text):
        return "기여도 미제공", "KOSIS 코드북 표에 물가 기여도 항목이 없음"
    if FORECAST_RE.search(text):
        return "정보 부족", "관측 실적이 아닌 전망·목표 문장"
    if PRIVATE_RE.search(context) or PRICE_SOURCE_RE.search(context):
        return "KOSIS 미제공", "민간 설문·정책·시장가격 지표"
    if row_domain != "무역" and FOREIGN_RE.search(context):
        return "KOSIS 미제공", "대한민국 KOSIS 범위 밖의 해외 통계"
    return None


def map_by_codebook(row):
    text = row.get("claim_text", "") or ""
    context = " ".join(
        str(row.get(field, "") or "")
        for field in ("title", "prev_sentence", "claim_text", "next_sentence")
    )
    row_domain = domain(row)
    nonverifiable = classify_nonverifiable(row, row_domain)
    if nonverifiable:
        return None, nonverifiable
    if PARTIAL_PERIOD_RE.search(text) or MULTI_METRIC_RE.search(text):
        return None, None
    target = extract_single_percent(row)
    if target is None:
        return None, None

    # A rate that "fell to 1.7%" is still +1.7; only explicit amount decreases are negative.
    if target > 0 and re.search(r"%\s*(?:감소|줄|하락|내림)", text):
        target = -target

    if row_domain == "물가":
        if RATIO_OR_RANK_RE.search(text) or REGION_RE.search(context):
            return None, None
        period = infer_period(row, "M")
        if not period:
            return None, None
        if "외식" in text:
            obj2 = "F01"
        elif "석유류" in text:
            obj2 = "B05"
        elif "가공식품" in text:
            obj2 = "B01"
        elif "농축수산물" in text or "농·축·수산물" in text or "농축·수산물" in text:
            obj2 = "A"
        else:
            obj2 = ""
        if obj2:
            if CPI_DETAIL_RE.search(text) or not re.search(r"소비자물가|통계청|전년\s*동월|전월\s*대비", text):
                return None, None
            prev = previous_period(period, "M", text)
            return mapping("101", "DT_1J22112", "T10", "T", "M", target, period, "CHANGE_RATE", obj2=obj2, prev=prev, note=f"품목별 소비자물가 {obj2}"), None
        if "생활물가" in text:
            return mapping("101", "DT_1J22042", "1", "T03", "M", target, period, "LEVEL", note="생활물가 전년동월비 직접값"), None
        if "소비자물가" in text or "물가상승률" in text or "물가 상승률" in text:
            if CPI_DETAIL_RE.search(text):
                return None, None
            return mapping("101", "DT_1J22042", "0", "T03", "M", target, period, "LEVEL", note="소비자물가 총지수 전년동월비 직접값"), None

    if row_domain == "고용":
        if RATIO_OR_RANK_RE.search(text) or REGION_RE.search(context):
            return None, None
        period = infer_period(row, "M")
        if not period:
            return None, None
        if "15~64" in text or "15∼64" in text:
            age = "63"
        elif "청년" in text or "15~29" in text or "15∼29" in text:
            age = "75"
        elif "20대" in text or "20~29" in text:
            age = "20"
        else:
            age = ""
        if "고용률" in text:
            item = "T90"
        elif "실업률" in text:
            item = "T80"
        else:
            return None, None
        table = "DT_1DA7002S" if age else "DT_1DA7001S"
        obj1 = age or "0"
        if POINT_RE.search(text):
            prev = previous_period(period, "M", text)
            return mapping("101", table, obj1, item, "M", target, period, "POINT_CHANGE", prev=prev, note="고용률/실업률 시점 차이"), None
        return mapping("101", table, obj1, item, "M", target, period, "LEVEL", note="고용률/실업률 직접값"), None

    if row_domain == "인구":
        if RATIO_OR_RANK_RE.search(text) or REGION_RE.search(context):
            return None, None
        period_type = "M" if (MONTH_RE.search(text) or "지난달" in text or "전월" in text) else "Y"
        target_period = infer_period(row, period_type)
        if not target_period:
            return None, None
        prev = previous_period(target_period, period_type, text)
        if "합계출산율" in text:
            if period_type != "Y":
                return None, ("KOSIS 미제공", "코드북 표에 분기·월 합계출산율이 없음")
            return mapping("101", "INH_1B8000F_01", "30", "T1", "Y", target, target_period, "LEVEL", note="연간 합계출산율"), None
        if "출생아" in text:
            if period_type == "M":
                return mapping("101", "DT_1B81A01", "00", "T1", "M", target, target_period, "CHANGE_RATE", prev=prev, note="전국 월별 출생아"), None
            return mapping("101", "INH_1B8000F_01", "11", "T1", "Y", target, target_period, "CHANGE_RATE", prev=prev, note="연간 출생아"), None
        if "혼인" in text or "결혼" in text:
            if period_type == "M":
                return mapping("101", "DT_1B83A35", "00", "T3", "M", target, target_period, "CHANGE_RATE", prev=prev, note="전국 월별 혼인"), None
            return mapping("101", "DT_1B8000F", "41", "T1", "Y", target, target_period, "CHANGE_RATE", prev=prev, note="연간 혼인"), None
        if "이혼" in text:
            if period_type == "M":
                return mapping("101", "DT_1B85033", "00", "T4", "M", target, target_period, "CHANGE_RATE", prev=prev, note="전국 월별 이혼"), None
            return mapping("101", "DT_1B8000F", "51", "T1", "Y", target, target_period, "CHANGE_RATE", prev=prev, note="연간 이혼"), None

    if row_domain == "소매":
        if RATIO_OR_RANK_RE.search(text) or REGION_RE.search(context) or FOREIGN_RE.search(context):
            return None, None
        period_type = "M" if (MONTH_RE.search(text) or "지난달" in text) else "Y"
        target_period = infer_period(row, period_type)
        if not target_period:
            return None, None
        prev = previous_period(target_period, period_type, text)
        if "서비스업" in text and "생산" in text:
            if period_type != "M" or not re.search(r"전년\s*동월|전월\s*대비", text):
                return None, None
            item = "T3" if period_type == "M" and re.search(r"전월|전달", text) else "T2"
            return mapping("101", "DT_1KC2020", "T", item, period_type, target, target_period, "CHANGE_RATE", prev=prev, note="서비스업 생산지수"), None
        if "소매" in text and ("판매" in text or "판매액" in text):
            if period_type != "M" or not re.search(r"소매\s*판매(?:액)?\s*지수|전년\s*동월|전월\s*대비", text):
                return None, None
            if re.search(r"서울|부산|대구|인천|광주|대전|울산|경기|강원|충청|전라|경상|제주", text):
                return None, ("지역·분류 불일치", "여러 지역 수치가 함께 있어 단일 지역을 자동 확정하지 않음")
            if "비내구재" in text:
                obj1 = "G3"
            elif "준내구재" in text:
                obj1 = "G2"
            elif "내구재" in text:
                obj1 = "G1"
            else:
                obj1 = "G0"
            item = "T3" if period_type == "M" and re.search(r"전월|전달", text) else "T2"
            return mapping("101", "DT_1K41012", obj1, item, period_type, target, target_period, "CHANGE_RATE", prev=prev, note="소매판매지수"), None

    if row_domain == "무역":
        if FOREIGN_RE.search(text) or TRADE_DETAIL_RE.search(text) or RATIO_OR_RANK_RE.search(text):
            return None, None
        has_export = re.search(r"(?:전체|한국의|우리나라의|연간|한\s*해)\s*수출(?:액)?", text)
        has_import = re.search(r"(?:전체|한국의|우리나라의|연간|한\s*해)\s*수입(?:액)?", text)
        if not has_export and not has_import:
            return None, None
        period_type = "M" if (MONTH_RE.search(text) or "지난달" in text) else "Y"
        target_period = infer_period(row, period_type)
        if not target_period:
            return None, None
        prev = previous_period(target_period, period_type, text)
        item = "13103112831T2" if has_import and not has_export else "13103112831T1"
        return mapping("360", "DT_1R11001_FRM101", "13102112831A.A", item, period_type, target, target_period, "CHANGE_RATE", prev=prev, note="통관 총수출입"), None

    return None, None


def read_cache():
    if not CACHE_PATH.exists():
        return {}
    return json.loads(CACHE_PATH.read_text(encoding="utf-8"))


def write_cache(cache):
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def cache_key(config):
    return "|".join(str(config.get(key, "")) for key in ("org_id", "tbl_id", "obj_l1", "obj_l2", "itm_id", "prd_se"))


def fetch_series(config, cache):
    key = cache_key(config)
    if key in cache:
        return cache[key]
    extra = {"objL2": config["obj_l2"]} if config.get("obj_l2") else {}
    rows = get_stat_data(
        config["org_id"], config["tbl_id"], config["obj_l1"], config["itm_id"],
        config["prd_se"], new_est_prd_cnt=500, **extra,
    )
    compact = [{"period": str(row.get("PRD_DE", "")), "value": row.get("DT"), "unit": row.get("UNIT_NM", "")} for row in rows]
    cache[key] = compact
    write_cache(cache)
    return compact


def period_value(series, period):
    for row in series:
        if row["period"] == period:
            return to_float(row["value"]), row.get("unit", "")
    return None, ""


def verify(config, cache):
    series = fetch_series(config, cache)
    current, unit = period_value(series, config["target_period"])
    if current is None:
        return None, None, None, unit, "목표 시점 값 없음"
    if config["mode"] == "LEVEL":
        actual = current
        previous = None
    else:
        previous, _ = period_value(series, config["prev_period"])
        if previous is None:
            return None, current, None, unit, "비교 시점 값 없음"
        if config["mode"] == "POINT_CHANGE":
            actual = current - previous
        elif previous != 0:
            actual = (current - previous) / previous * 100
        else:
            return None, current, previous, unit, "비교 시점 값이 0"
    diff = abs(actual - config["target_number"])
    verdict = "일치" if diff <= 0.15 else "불일치"
    return actual, current, previous, unit, verdict


def classify_unavailable(row):
    text = row.get("claim_text", "") or ""
    status = final_status(row)
    reason_text = " ".join(
        str(row.get(field, "") or "")
        for field in ("api_error", "audit_reason", "manual_mapping_reason", "remap_reason", "reviewer_note")
    )
    combined = f"{status} {reason_text}"
    if "기여도" in combined or CONTRIBUTION_RE.search(text):
        return "기여도 미제공", "KOSIS 표에 주장한 기여도 항목이 없음"
    if "지역집계없음" in combined or re.search(r"동남아|여러\s*지역|지역\s*집계", combined):
        return "지역·분류 불일치", "필요한 지역·집계 분류가 KOSIS 표에 없음"
    if FORECAST_RE.search(text) or "파라미터미확정" in status or "목표 시점 미확정" in combined:
        return "정보 부족", "시점·대상·파라미터 또는 관측 실적이 확정되지 않음"
    if re.search(r"개별|품목|국가|연령|업종|분류", combined) and "API조회실패" in status:
        return "지역·분류 불일치", "필요한 세부 분류와 기존 매핑이 일치하지 않음"
    return "KOSIS 미제공", "현재 코드북 표에서 같은 정의의 값을 확보하지 못함"


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with INPUT.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        master = list(reader)
        master_fields = list(reader.fieldnames or [])

    recheck = [row for row in master if final_status(row).startswith("재검토필요")]
    unavailable = [row for row in master if final_status(row).startswith("판단불가")]
    if len(recheck) != 1643 or len(unavailable) != 337:
        raise RuntimeError(f"입력 상태 불일치: recheck={len(recheck)}, unavailable={len(unavailable)}")

    cache = read_cache()
    expanded = []
    by_id = {}
    for index, row in enumerate(recheck, start=1):
        out = dict(row)
        out["expansion_no"] = index
        out["expansion_batch"] = (index - 1) // 200 + 1
        out["expansion_domain"] = domain(row)
        config, unavailable_decision = map_by_codebook(row)
        if config:
            out.update({
                "expansion_decision": "코드북_자동검증대상",
                "expansion_org_id": config["org_id"],
                "expansion_tbl_id": config["tbl_id"],
                "expansion_obj_l1": config["obj_l1"],
                "expansion_obj_l2": config["obj_l2"],
                "expansion_itm_id": config["itm_id"],
                "expansion_prd_se": config["prd_se"],
                "expansion_target_number": config["target_number"],
                "expansion_target_period": config["target_period"],
                "expansion_prev_period": config["prev_period"],
                "expansion_mapping_note": config["note"],
                "unavailable_category": "",
                "unavailable_category_reason": "",
            })
            try:
                actual, current, previous, unit, verdict = verify(config, cache)
                if actual is None:
                    raise ValueError(verdict)
                out["expansion_api_success"] = "Y"
                out["expansion_actual_number"] = actual
                out["expansion_current_value"] = current
                out["expansion_previous_value"] = "" if previous is None else previous
                out["expansion_unit"] = unit
                out["expansion_verdict"] = verdict
                out["expansion_final_status"] = f"검증완료_코드북{verdict}"
                out["expansion_evidence"] = (
                    f"{config['tbl_id']} {config['target_period']}={current}; "
                    f"{config['prev_period']}={previous}; actual={actual}; target={config['target_number']}"
                )
                out["expansion_api_error"] = ""
            except Exception as exc:
                out["expansion_api_success"] = "N"
                out["expansion_actual_number"] = ""
                out["expansion_current_value"] = ""
                out["expansion_previous_value"] = ""
                out["expansion_unit"] = ""
                out["expansion_verdict"] = "판단불가"
                out["expansion_final_status"] = "재검토필요_코드북조회실패"
                out["expansion_evidence"] = ""
                out["expansion_api_error"] = str(exc)
        elif unavailable_decision:
            category, reason = unavailable_decision
            out["expansion_decision"] = "코드북_비검증분류"
            out["unavailable_category"] = category
            out["unavailable_category_reason"] = reason
            out["expansion_api_success"] = "N/A"
            out["expansion_verdict"] = "판단불가"
            out["expansion_final_status"] = f"판단불가_{category}"
            for field in (
                "expansion_org_id", "expansion_tbl_id", "expansion_obj_l1", "expansion_obj_l2",
                "expansion_itm_id", "expansion_prd_se", "expansion_target_number",
                "expansion_target_period", "expansion_prev_period", "expansion_mapping_note",
                "expansion_actual_number", "expansion_current_value", "expansion_previous_value",
                "expansion_unit", "expansion_evidence", "expansion_api_error",
            ):
                out[field] = ""
        else:
            out["expansion_decision"] = "수동검토유지"
            out["expansion_final_status"] = final_status(row)
            out["expansion_api_success"] = "N/A"
            out["expansion_verdict"] = ""
            out["unavailable_category"] = ""
            out["unavailable_category_reason"] = ""
            for field in (
                "expansion_org_id", "expansion_tbl_id", "expansion_obj_l1", "expansion_obj_l2",
                "expansion_itm_id", "expansion_prd_se", "expansion_target_number",
                "expansion_target_period", "expansion_prev_period", "expansion_mapping_note",
                "expansion_actual_number", "expansion_current_value", "expansion_previous_value",
                "expansion_unit", "expansion_evidence", "expansion_api_error",
            ):
                out[field] = ""
        expanded.append(out)
        by_id[out["claim_id"]] = out

    expansion_fields = list(expanded[0].keys())
    write_csv(OUTPUT_DIR / "expansion_1643_all.csv", expanded, expansion_fields)
    for batch_number in range(1, 10):
        batch_rows = [row for row in expanded if row["expansion_batch"] == batch_number]
        if batch_rows:
            write_csv(OUTPUT_DIR / f"expansion_batch_{batch_number:03d}.csv", batch_rows, expansion_fields)

    unavailable_rows = []
    unavailable_by_id = {}
    for row in unavailable:
        out = dict(row)
        category, reason = classify_unavailable(row)
        out["unavailable_category"] = category
        out["unavailable_category_reason"] = reason
        unavailable_rows.append(out)
        unavailable_by_id[out["claim_id"]] = out
    unavailable_fields = list(unavailable_rows[0].keys())
    write_csv(OUTPUT_DIR / "unavailable_337_categorized.csv", unavailable_rows, unavailable_fields)

    added_fields = [
        "expansion_no", "expansion_batch", "expansion_domain", "expansion_decision",
        "expansion_org_id", "expansion_tbl_id", "expansion_obj_l1", "expansion_obj_l2",
        "expansion_itm_id", "expansion_prd_se", "expansion_target_number",
        "expansion_target_period", "expansion_prev_period", "expansion_mapping_note",
        "expansion_api_success", "expansion_actual_number", "expansion_current_value",
        "expansion_previous_value", "expansion_unit", "expansion_verdict",
        "expansion_final_status", "expansion_evidence", "expansion_api_error",
        "unavailable_category", "unavailable_category_reason",
    ]
    final_rows = []
    for row in master:
        claim_id = row["claim_id"]
        if claim_id in by_id:
            updated = dict(by_id[claim_id])
            updated["audit_status"] = updated["expansion_final_status"]
            if updated.get("expansion_verdict"):
                updated["refined_verdict"] = updated["expansion_verdict"]
                updated["verdict"] = updated["expansion_verdict"]
            final_rows.append(updated)
        elif claim_id in unavailable_by_id:
            updated = dict(unavailable_by_id[claim_id])
            updated["expansion_final_status"] = f"판단불가_{updated['unavailable_category']}"
            final_rows.append(updated)
        else:
            updated = dict(row)
            for field in added_fields:
                updated.setdefault(field, "")
            final_rows.append(updated)
    final_fields = list(master_fields)
    for field in added_fields:
        if field not in final_fields:
            final_fields.append(field)
    write_csv(OUTPUT_DIR / "final_verified_filled_2001_codebook_v7.csv", final_rows, final_fields)

    decisions = Counter(row["expansion_decision"] for row in expanded)
    auto_rows = [row for row in expanded if row["expansion_decision"] == "코드북_자동검증대상"]
    verdicts = Counter(row["expansion_verdict"] for row in auto_rows if row["expansion_verdict"])
    api = Counter(row["expansion_api_success"] for row in expanded)
    unavailable_counts = Counter(row["unavailable_category"] for row in unavailable_rows)
    expanded_unavailable = Counter(
        row["unavailable_category"] for row in expanded if row["expansion_decision"] == "코드북_비검증분류"
    )
    summary_rows = [
        {"section": "expansion_decision", "label": key, "count": value}
        for key, value in decisions.most_common()
    ] + [
        {"section": "expansion_verdict", "label": key, "count": value}
        for key, value in verdicts.most_common()
    ] + [
        {"section": "existing_unavailable_337", "label": key, "count": value}
        for key, value in unavailable_counts.most_common()
    ] + [
        {"section": "new_unavailable_from_recheck", "label": key, "count": value}
        for key, value in expanded_unavailable.most_common()
    ]
    write_csv(OUTPUT_DIR / "expansion_summary.csv", summary_rows, ["section", "label", "count"])

    api_success_rows = [row for row in auto_rows if row["expansion_api_success"] == "Y"]
    report = [
        "# KOSIS 코드북 1,643건 확대 결과",
        "",
        "## 결론",
        "",
        f"- 전체 재검토 입력: {len(expanded)}건",
        f"- 코드북 자동검증 대상: {len(auto_rows)}건",
        f"- API 성공: {len(api_success_rows)}건 ({len(api_success_rows) / max(len(auto_rows), 1):.1%})",
        f"- 자동 판정: {dict(verdicts)}",
        f"- 비검증 자동분류: {decisions.get('코드북_비검증분류', 0)}건 ({dict(expanded_unavailable)})",
        f"- 수동검토 유지: {decisions.get('수동검토유지', 0)}건",
        f"- 기존 판단불가 337건 분류: {dict(unavailable_counts)}",
        "- 골드셋에서 확인한 것처럼 API 성공은 의미 정확도와 동일하지 않으므로 코드북 규칙에 걸린 행만 확정 판정했다.",
        "",
        "## 배치",
        "",
        "- 001~008: 각 200건",
        "- 009: 43건",
        "",
        "## 산출물",
        "",
        "- `expansion_1643_all.csv`: 전체 확대 결과",
        "- `expansion_batch_001.csv` ~ `expansion_batch_009.csv`: 제출·검토용 배치",
        "- `unavailable_337_categorized.csv`: 기존 판단불가 사유 4분류",
        "- `final_verified_filled_2001_codebook_v7.csv`: 2,001건 통합 최신본",
        "- `expansion_summary.csv`: 요약 집계",
    ]
    (OUTPUT_DIR / "expansion_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    print(f"recheck={len(expanded)} decisions={dict(decisions)}")
    print(f"api={dict(api)} verdicts={dict(verdicts)}")
    print(f"unavailable337={dict(unavailable_counts)}")
    print(f"new_unavailable={dict(expanded_unavailable)}")
    print(OUTPUT_DIR.resolve())


if __name__ == "__main__":
    main()
