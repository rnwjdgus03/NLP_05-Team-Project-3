"""Build the 100-claim KOSIS gold set, rerun live values, and score the baseline."""

from __future__ import annotations

import csv
import json
import math
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path


REPO = Path(__file__).resolve().parent
SELECTION = REPO / "outputs/bteam_gold/gold100_selection.csv"
OUTPUT_DIR = REPO / "outputs/bteam_gold"
CACHE_PATH = OUTPUT_DIR / "gold100_api_cache.json"

sys.path.insert(0, str(REPO))
os.chdir(REPO)
from kosis_api_test import get_stat_data  # noqa: E402


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
    scale=1.0,
    tolerance=0.3,
    tolerance_mode="absolute",
    note="",
    denominator=None,
    baseline_value=None,
):
    return {
        "org_id": org_id,
        "tbl_id": table_id,
        "obj_l1": obj_l1,
        "obj_l2": obj_l2,
        "itm_id": item_id,
        "prd_se": period_type,
        "target_number": target_number,
        "target_period": target_period,
        "prev_period": prev_period,
        "calculation_mode": mode,
        "scale": scale,
        "tolerance": tolerance,
        "tolerance_mode": tolerance_mode,
        "note": note,
        "denominator": denominator,
        "baseline_value": baseline_value,
    }


ELIGIBLE = {
    # Inflation
    "C00381": cfg("101", "DT_1J22003", "T10", "T", "Y", 2.3, "2024", "CHANGE_RATE", prev_period="2023", note="연간 전국 소비자물가지수 증감률"),
    "C04611": cfg("101", "DT_1J22112", "T10", "T", "M", 3.2, "202501", "CHANGE_RATE", prev_period="202401", obj_l2="B01A01116", note="빵 전년동월비"),
    "C06679": cfg("101", "DT_1J22042", "1", "T03", "M", 1.2, "202410", "LEVEL", tolerance=0.05, note="생활물가지수 전년동월비 직접값"),
    "C09334": cfg("101", "DT_1J22112", "T10", "T", "M", 3.0, "202503", "CHANGE_RATE", prev_period="202403", obj_l2="F01", note="외식 전년동월비"),
    "C15304": cfg("101", "DT_1J22112", "T10", "T", "M", -2.3, "202505", "CHANGE_RATE", prev_period="202405", obj_l2="B05", note="석유류 전년동월비"),
    "C15308": cfg("101", "DT_1J22112", "T10", "T", "M", 0.1, "202505", "CHANGE_RATE", prev_period="202405", obj_l2="A", note="농축수산물 전년동월비"),
    "C15315": cfg("101", "DT_1J22112", "T10", "T", "M", 3.2, "202505", "CHANGE_RATE", prev_period="202405", obj_l2="F01", note="외식 전년동월비"),
    "C16718": cfg("101", "DT_1J22005", "T10", "T", "M", 19.1, "202505", "CHANGE_FROM_BASE", prev_period="2020=100", obj_l2="110", baseline_value=100.0, note="생활물가지수 2020=100 기준 누적 변화"),
    "C18109": cfg("101", "DT_1J22042", "1", "T03", "M", 0.2, "202506", "POINT_CHANGE", prev_period="202505", note="생활물가 전년동월비 발표값의 전월 차이"),
    "C20252": cfg("101", "DT_1J22112", "T10", "T", "M", 3.4, "202510", "CHANGE_RATE", prev_period="202410", obj_l2="F01", note="외식 전년동월비"),
    "C20278": cfg("101", "DT_1J22112", "T10", "T", "M", 3.1, "202510", "CHANGE_RATE", prev_period="202410", obj_l2="A", note="농축수산물 전년동월비"),
    # Employment
    "C01478": cfg("101", "DT_1DA7002S", "75", "T80", "M", 5.9, "202412", "LEVEL", tolerance=0.05, note="15~29세 실업률"),
    "C02892": cfg("101", "DT_1DA7002S", "75", "T90", "M", 44.4, "202105", "LEVEL", tolerance=0.05, note="15~29세 고용률"),
    "C04584": cfg("101", "DT_1DA7002S", "75", "T90", "M", -0.7, "202405", "POINT_CHANGE", prev_period="202305", note="15~29세 고용률 전년동월 차이"),
    "C09229": cfg("101", "DT_1DA7001S", "0", "T90", "Y", 62.7, "2024", "LEVEL", tolerance=0.05, note="15세 이상 연간 고용률"),
    "C09952": cfg(
        "101", "DT_1DA7002S", "75", "T80", "M", 2.4, "202503", "RATIO",
        tolerance=0.1,
        note="청년 실업률 / 전체 실업률",
        denominator={"org_id": "101", "tbl_id": "DT_1DA7001S", "obj_l1": "0", "obj_l2": "", "itm_id": "T80", "prd_se": "M"},
    ),
    "C09996": cfg("101", "DT_1DA7002S", "75", "T40", "M", 289.0, "202503", "LEVEL", tolerance=0.05, tolerance_mode="relative", note="15~29세 실업자 천명"),
    "C15966": cfg("101", "DT_1DA7001S", "0", "T30", "M", 29160.0, "202505", "LEVEL", tolerance=0.05, tolerance_mode="relative", note="전체 취업자 천명"),
    "C15980": cfg("101", "DT_1DA7001S", "0", "T80", "M", 2.8, "202505", "LEVEL", tolerance=0.05, note="전체 실업률"),
    "C19439": cfg("101", "DT_1DA7002S", "63", "T90", "M", 70.3, "202506", "LEVEL", tolerance=0.05, note="15~64세 고용률"),
    "C19960": cfg("101", "DT_1DA7002S", "20", "T90", "M", -0.2, "202509", "POINT_CHANGE", prev_period="202409", note="20~29세 고용률 전년동월 차이"),
    # Trade
    "C00078": cfg("360", "DT_1R11001_FRM101", "13102112831A.A", "13103112831T1", "Y", 6838.0, "2024", "LEVEL", scale=0.00001, tolerance=0.05, tolerance_mode="relative", note="통관 기준 총수출, 천달러를 억달러로 변환"),
    "C00090": cfg("360", "DT_1R11001_FRM101", "13102112831A.A", "13103112831T1", "M", 6.6, "202412", "CHANGE_RATE", prev_period="202312", note="통관 기준 총수출 전년동월비"),
    "C01375": cfg("360", "DT_1R11001_FRM101", "13102112831A.A", "13103112831T1", "M", 1.4, "202411", "CHANGE_RATE", prev_period="202311", note="통관 기준 총수출 전년동월비"),
    "C01924": cfg("360", "DT_1R11001_FRM101", "13102112831A.A", "13103112831T1", "Y", 8.2, "2024", "CHANGE_RATE", prev_period="2023", note="통관 기준 총수출 전년비"),
    "C03779": cfg("301", "DT_301Y013", "13102134519ACC_CD.110000", "13103134519999", "M", 633.0, "202412", "LEVEL", scale=0.01, tolerance=0.05, tolerance_mode="relative", note="국제수지 상품수출, 백만달러를 억달러로 변환"),
    "C03850": cfg("301", "DT_301Y013", "13102134519ACC_CD.110000", "13103134519999", "M", 633.0, "202412", "LEVEL", scale=0.01, tolerance=0.05, tolerance_mode="relative", note="국제수지 상품수출, 백만달러를 억달러로 변환"),
    "C04394": cfg("360", "DT_1R11001_FRM101", "13102112831A.A", "13103112831T1", "Y", 8.2, "2024", "CHANGE_RATE", prev_period="2023", note="통관 기준 총수출 전년비"),
    # Population
    "C02004": cfg("101", "DT_1B81A01", "00", "T1", "M", 3.0, "202401-202411", "SUM_CHANGE", prev_period="202301-202311", note="전국 1~11월 출생아 합계 전년비"),
    "C02005": cfg("101", "INH_1B8000F_01", "11", "T1", "Y", -7.7, "2023", "CHANGE_RATE", prev_period="2022", note="연간 출생아수 전년비"),
    "C02109": cfg("101", "DT_1B81A01", "00", "T1", "M", 7.9, "202407", "CHANGE_RATE", prev_period="202307", note="전국 7월 출생아수 전년동월비"),
    "C02110": cfg("101", "INH_1B8000F_01", "11", "T1", "Y", -7.7, "2023", "CHANGE_RATE", prev_period="2022", note="연간 출생아수 전년비"),
    "C02115": cfg("101", "DT_1B83A35", "00", "T3", "M", 24.6, "202404", "CHANGE_RATE", prev_period="202304", note="전국 혼인건수 전년동월비"),
    "C05780": cfg("101", "INH_1B8000F_01", "11", "T1", "Y", 3.6, "2024", "CHANGE_RATE", prev_period="2023", note="연간 출생아수 전년비"),
    "C05830": cfg("101", "DT_1B8000F", "41", "T1", "Y", 15.0, "2024", "CHANGE_RATE", prev_period="2023", note="연간 혼인건수 전년비"),
    "C05915": cfg("101", "DT_1B8000F", "41", "T1", "Y", 14.9, "2024", "CHANGE_RATE", prev_period="2023", note="연간 혼인건수 전년비"),
    "C08572": cfg("101", "DT_1B83A35", "00", "T3", "M", 11.6, "202401", "CHANGE_RATE", prev_period="202301", note="전국 혼인건수 전년동월비"),
    "C08708": cfg("101", "INH_1B8000F_01", "30", "T1", "Y", 1.74, "1984", "LEVEL", tolerance=0.05, note="연간 합계출산율"),
    "C14590": cfg("101", "INH_1B8000F_01", "30", "T1", "Y", 0.75, "2024", "LEVEL", tolerance=0.05, note="연간 합계출산율"),
    "C20157": cfg("101", "DT_1B85033", "00", "T4", "M", -5.5, "202508", "CHANGE_RATE", prev_period="202408", note="전국 이혼건수 전년동월비"),
    # Retail and services
    "C00234": cfg("101", "DT_1K41012", "G0", "T2", "M", -1.9, "202411", "CHANGE_RATE", prev_period="202311", note="소매판매 불변지수 전년동월비"),
    "C03489": cfg("101", "DT_1K41012", "G0", "T2", "Y", -2.2, "2024", "CHANGE_RATE", prev_period="2023", note="연간 소매판매 불변지수"),
    "C03495": cfg("101", "DT_1K41012", "G0", "T2", "Y", -1.5, "2023", "CHANGE_RATE", prev_period="2022", note="연간 소매판매 불변지수"),
    "C03497": cfg("101", "DT_1K41012", "G0", "T2", "Y", -3.2, "2003", "CHANGE_RATE", prev_period="2002", note="연간 소매판매 불변지수"),
    "C03498": cfg("101", "DT_1K41012", "G3", "T2", "Y", -1.4, "2024", "CHANGE_RATE", prev_period="2023", note="비내구재 연간 불변지수"),
    "C05090": cfg("101", "DT_1K41012", "G0", "T2", "Y", -1.5, "2023", "CHANGE_RATE", prev_period="2022", note="연간 소매판매 불변지수"),
    "C05091": cfg("101", "DT_1K41018", "11", "T2", "Y", -4.4, "2024", "CHANGE_RATE", prev_period="2023", obj_l2="A0", note="서울 소매판매 총지수"),
    "C05093": cfg("101", "DT_1KC2020", "T", "T2", "Y", 1.4, "2024", "CHANGE_RATE", prev_period="2023", note="서비스업 생산 불변지수"),
    "C09020": cfg("101", "DT_1K41012", "G0", "T3", "M", -0.7, "202501", "CHANGE_RATE", prev_period="202412", note="소매판매 계절조정지수 전월비"),
    "C14809": cfg("101", "DT_1KC2020", "T", "T3", "M", -0.1, "202504", "CHANGE_RATE", prev_period="202503", note="서비스업 생산 계절조정지수 전월비"),
    "C19703": cfg("101", "DT_1K41012", "G0", "T3", "M", -2.4, "202508", "CHANGE_RATE", prev_period="202507", note="소매판매 계절조정지수 전월비"),
}


INELIGIBLE = {
    # KOSIS does not provide the cited foreign/private/policy statistic.
    "C04329": ("KOSIS 미제공", "미국 소비자물가"),
    "C04369": ("KOSIS 미제공", "미국 소비자물가"),
    "C05531": ("KOSIS 미제공", "미국 기대인플레이션"),
    "C10196": ("KOSIS 미제공", "독일 국채 가격"),
    "C10977": ("KOSIS 미제공", "주한미군 방위비 분담금"),
    "C00962": ("KOSIS 미제공", "미국 실업률"),
    "C01848": ("KOSIS 미제공", "일자리 사업 예산 집행 목표"),
    "C05072": ("KOSIS 미제공", "뉴질랜드 실업률"),
    "C05876": ("KOSIS 미제공", "기업 채용계획 설문"),
    "C05892": ("KOSIS 미제공", "기업 채용계획 설문"),
    "C07324": ("KOSIS 미제공", "평균 구직기간 인용문"),
    "C14392": ("KOSIS 미제공", "개별 기업 외국인 채용 비중"),
    "C14427": ("KOSIS 미제공", "70세 재취업자 조사 비율"),
    "C02176": ("KOSIS 미제공", "GDP 성장기여도"),
    "C05519": ("KOSIS 미제공", "미국 자동차 관세 예고"),
    "C10228": ("KOSIS 미제공", "미중 관세율"),
    "C18644": ("KOSIS 미제공", "미국 관세율 발언"),
    "C06389": ("KOSIS 미제공", "베트남 합계출산율"),
    "C14609": ("KOSIS 미제공", "해당 KOSIS 표는 분기 합계출산율을 제공하지 않음"),
    "C14615": ("KOSIS 미제공", "해당 KOSIS 표는 분기 합계출산율을 제공하지 않음"),
    "C00510": ("KOSIS 미제공", "샤인머스캣 설 가격"),
    "C02244": ("KOSIS 미제공", "aT 일별 마른김 소매가격"),
    "C16772": ("KOSIS 미제공", "aT 일별 쌀 소매가격"),
    "C18903": ("KOSIS 미제공", "aT 일별 수박 소매가격"),
    "C19700": ("KOSIS 미제공", "소비쿠폰 사용액 연구 결과"),
    "C19768": ("KOSIS 미제공", "시장 쌀 소매가격"),
    # Current KOSIS table lacks the required region/item/source cross-classification.
    "C01491": ("지역·분류 불일치", "커피 수입가격은 무역 수입액 표와 지표가 다름"),
    "C07664": ("지역·분류 불일치", "ICT 품목과 국가를 동시에 교차한 분류가 현재 코드북에 없음"),
    "C08645": ("지역·분류 불일치", "자동차 품목과 미국 국가를 동시에 교차해야 함"),
    "C10172": ("지역·분류 불일치", "중소기업 여부와 화장품 품목을 동시에 구분할 수 없음"),
    "C19610": ("지역·분류 불일치", "자동차 품목과 미국 국가를 동시에 교차해야 함"),
    "C20480": ("지역·분류 불일치", "광제조업 분류와 관세청 품목 분류 기준이 다름"),
    "C15981": ("지역·분류 불일치", "비경제활동 사유 '쉬었음'은 경제활동인구 총괄 표 항목이 아님"),
    "C19540": ("지역·분류 불일치", "20대와 '쉬었음' 사유를 동시에 구분하는 별도 표가 필요"),
    "C09699": ("지역·분류 불일치", "현재 인구동태 총괄 표에는 대전 지역 축이 없음"),
    "C20159": ("지역·분류 불일치", "국내 인구이동은 출생·혼인 인구동태 표와 다른 통계"),
    "C20346": ("지역·분류 불일치", "다문화 혼인 유형은 별도 통계표가 필요"),
    "C20348": ("지역·분류 불일치", "다문화 혼인 유형은 별도 통계표가 필요"),
    "C20353": ("지역·분류 불일치", "다문화 출생 유형은 별도 통계표가 필요"),
    "C03563": ("지역·분류 불일치", "개별 자동차 모델 판매량은 소매판매 상품군 표에 없음"),
    # Contributions are not exposed by the selected KOSIS CPI tables.
    "C19718": ("기여도 미제공", "가공식품의 전체 물가 기여도 0.36%p"),
    "C20277": ("기여도 미제공", "농축수산물의 전체 물가 기여도 0.25%p"),
    # The sentence does not determine a single observed target.
    "C04610": ("정보 부족", "여러 품목과 7~8% 범위가 함께 있어 단일 목표 수치가 불명확"),
    "C15156": ("정보 부족", "관세 시나리오에 따른 전망 문장"),
    "C00515": ("정보 부족", "경제성장률 전망이며 관측 수출 실적이 아님"),
    "C04067": ("정보 부족", "분석 모형의 예상 감소율"),
    "C11172": ("정보 부족", "정량 목표값이 없는 전망 설명"),
    "C03562": ("정보 부족", "문장만으로 비교 대상 상품군과 기준월을 확정할 수 없음"),
    "C20212": ("정보 부족", "0.9%가 어떤 전망 지표인지 문장만으로 확정할 수 없음"),
}


CODEBOOK = [
    ("CPI_TOTAL_INDEX", "물가", "전국 소비자물가지수", "101", "DT_1J22003", "시도=T10", "T", "Y/M", "지수 두 시점 증감률"),
    ("CPI_HEADLINE_RATE", "물가", "총지수·생활물가 등락률", "101", "DT_1J22042", "지수종류=0/1/2/3/4", "T02/T03/T04", "M", "KOSIS 발표 등락률 직접 사용"),
    ("CPI_ITEM_INDEX", "물가", "외식·석유류·가공식품·농축수산물", "101", "DT_1J22112", "시도=T10; 품목=F01/B05/B01/A", "T", "M", "전년동월 지수 증감률"),
    ("CPI_LIVING_INDEX", "물가", "생활물가지수 누적 변화", "101", "DT_1J22005", "시도=T10; 품목=110", "T", "M", "지정 두 시점 지수 증감률"),
    ("EMPLOYMENT_TOTAL", "고용", "전체 취업자·실업률·고용률", "101", "DT_1DA7001S", "성별=0", "T30/T80/T90", "Y/M", "수준값 또는 시점 차이"),
    ("EMPLOYMENT_AGE", "고용", "청년·20대·15~64세 고용", "101", "DT_1DA7002S", "연령=75/20/63", "T30/T40/T80/T90", "M", "수준값·전년동월 차이·비율"),
    ("POPULATION_BIRTH_FERTILITY", "인구", "출생아·합계출산율", "101", "INH_1B8000F_01", "기본항목=11/30", "T1", "Y/M", "수준값·전년비·월 합계"),
    ("POPULATION_MARRIAGE_DIVORCE", "인구", "혼인·이혼 건수", "101", "DT_1B8000F", "기본항목=41/51", "T1", "Y/M", "수준값 또는 전년비"),
    ("POPULATION_BIRTH_MONTHLY", "인구", "월별 출생아", "101", "DT_1B81A01", "시군구=00", "T1", "M", "월 수준값·전년동월비·기간 합계"),
    ("POPULATION_MARRIAGE_MONTHLY", "인구", "월별 혼인", "101", "DT_1B83A35", "시군구=00", "T3", "M", "월 수준값 또는 전년동월비"),
    ("POPULATION_DIVORCE_MONTHLY", "인구", "월별 이혼", "101", "DT_1B85033", "시군구=00", "T4", "M", "월 수준값 또는 전년동월비"),
    ("TRADE_CUSTOMS_ITEM", "무역", "통관 총수출·품목 수출입", "360", "DT_1R11001_FRM101", "품목=총액 또는 확정 품목", "수출/수입", "Y/M", "천달러 단위 변환 또는 증감률"),
    ("TRADE_CUSTOMS_COUNTRY", "무역", "국가별 총수출입", "360", "DT_1R11006_FRM101", "국가=확정 국가", "수출/수입", "Y/M", "천달러 단위 변환 또는 증감률"),
    ("TRADE_BOP_EXPORT", "무역", "국제수지 상품수출", "301", "DT_301Y013", "계정=상품수출", "국제수지", "M", "백만달러를 억달러로 변환"),
    ("RETAIL_TOTAL", "소매", "소매판매 총지수·재별", "101", "DT_1K41012", "상품군=G0/G1/G2/G3", "T2/T3", "Y/M", "불변지수 전년비 또는 계절조정 전월비"),
    ("RETAIL_REGION", "소매", "지역별 소매판매", "101", "DT_1K41018", "지역; 업종=A0", "T2", "Y", "지역 총지수 전년비"),
    ("SERVICE_PRODUCTION", "소매", "서비스업 생산", "101", "DT_1KC2020", "업종=T", "T2/T3", "Y/M", "불변지수 전년비 또는 계절조정 전월비"),
]


def read_selection():
    path = SELECTION if SELECTION.exists() else Path.cwd() / SELECTION.name
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_cache():
    if not CACHE_PATH.exists():
        return {}
    return json.loads(CACHE_PATH.read_text(encoding="utf-8"))


def write_cache(cache):
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def cache_key(mapping):
    return "|".join(
        str(mapping.get(key, ""))
        for key in ("org_id", "tbl_id", "obj_l1", "obj_l2", "itm_id", "prd_se")
    )


def fetch_series(mapping, cache):
    key = cache_key(mapping)
    if key in cache:
        return cache[key]
    extra = {}
    if mapping.get("obj_l2"):
        extra["objL2"] = mapping["obj_l2"]
    rows = get_stat_data(
        mapping["org_id"], mapping["tbl_id"], mapping["obj_l1"], mapping["itm_id"],
        mapping["prd_se"], new_est_prd_cnt=500, **extra,
    )
    compact = [
        {"period": str(row.get("PRD_DE", "")), "value": row.get("DT"), "unit": row.get("UNIT_NM", "")}
        for row in rows
    ]
    cache[key] = compact
    write_cache(cache)
    return compact


def to_float(value):
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def period_value(series, period):
    for row in series:
        if row["period"] == period:
            return to_float(row["value"]), row.get("unit", "")
    return None, ""


def sum_period_range(series, period_range):
    start, end = period_range.split("-")
    values = [to_float(row["value"]) for row in series if start <= row["period"] <= end]
    values = [value for value in values if value is not None]
    expected = int(end[-2:]) - int(start[-2:]) + 1
    return (sum(values), len(values)) if len(values) == expected else (None, len(values))


def calculate_actual(config, cache):
    series = fetch_series(config, cache)
    mode = config["calculation_mode"]
    unit = next((row.get("unit", "") for row in series if row.get("unit")), "")
    if mode == "SUM_CHANGE":
        current, current_count = sum_period_range(series, config["target_period"])
        previous, previous_count = sum_period_range(series, config["prev_period"])
        if current is None or previous in (None, 0):
            return None, current, previous, unit, f"월 합계 부족: {current_count}/{previous_count}"
        actual = (current - previous) / previous * 100
        return actual, current, previous, unit, "월별 합계의 전년비"

    current, current_unit = period_value(series, config["target_period"])
    if current is None:
        return None, None, None, unit, "목표 시점 값 없음"
    current *= config.get("scale", 1.0)
    unit = current_unit or unit

    if mode == "LEVEL":
        return current, current, None, unit, "KOSIS 수준값"

    if mode == "CHANGE_FROM_BASE":
        baseline = config.get("baseline_value")
        if baseline in (None, 0):
            return None, current, baseline, unit, "기준값 없음"
        return (current - baseline) / baseline * 100, current, baseline, unit, "고정 기준값 대비 증감률"

    if mode == "RATIO":
        denominator = config["denominator"]
        denominator_series = fetch_series(denominator, cache)
        denominator_value, _ = period_value(denominator_series, config["target_period"])
        if denominator_value in (None, 0):
            return None, current, denominator_value, unit, "분모 값 없음"
        return current / denominator_value, current, denominator_value, unit, "분자/분모 비율"

    previous, _ = period_value(series, config["prev_period"])
    if previous is None:
        return None, current, None, unit, "비교 시점 값 없음"
    previous *= config.get("scale", 1.0)
    if mode == "CHANGE_RATE":
        if previous == 0:
            return None, current, previous, unit, "비교 시점 값이 0"
        return (current - previous) / previous * 100, current, previous, unit, "두 시점 증감률"
    if mode == "POINT_CHANGE":
        return current - previous, current, previous, unit, "두 시점 차이"
    raise ValueError(f"지원하지 않는 계산 방식: {mode}")


def judge(config, actual):
    if actual is None:
        return "판단불가", None
    target = config["target_number"]
    if config["tolerance_mode"] == "relative":
        diff = abs(actual - target) / max(abs(target), 1e-12)
    else:
        diff = abs(actual - target)
    return ("일치" if diff <= config["tolerance"] else "불일치"), diff


def status_value(row):
    return row.get("source_status", "")


def baseline_verifiable(row):
    return not status_value(row).startswith("판단불가")


def normalize(value):
    return str(value or "").strip()


def score_rows(rows):
    eligible_rows = [row for row in rows if row["gold_verifiable"] == "Y"]
    api_rows = [row for row in eligible_rows if row["codebook_api_success"] == "Y"]
    verdict_rows = [row for row in rows if row["gold_verdict"]]
    metrics = [
        ("골드셋 전체", len(rows), len(rows), 1.0, "5개 분야 각 20건"),
        (
            "검증 가능 여부 분류 정확도", sum(row["baseline_eligibility_correct"] == "Y" for row in rows), len(rows),
            sum(row["baseline_eligibility_correct"] == "Y" for row in rows) / len(rows),
            "기존 판단불가 여부를 시스템 예측으로 사용",
        ),
        (
            "통계표 매핑 정확도", sum(row["baseline_table_correct"] == "Y" for row in eligible_rows), len(eligible_rows),
            sum(row["baseline_table_correct"] == "Y" for row in eligible_rows) / max(len(eligible_rows), 1),
            "골드 검증 가능 건 기준 org_id+tbl_id",
        ),
        (
            "항목 매핑 정확도", sum(row["baseline_item_correct"] == "Y" for row in eligible_rows), len(eligible_rows),
            sum(row["baseline_item_correct"] == "Y" for row in eligible_rows) / max(len(eligible_rows), 1),
            "obj_l1+obj_l2+itm_id",
        ),
        (
            "시점 매핑 정확도", sum(row["baseline_period_correct"] == "Y" for row in eligible_rows), len(eligible_rows),
            sum(row["baseline_period_correct"] == "Y" for row in eligible_rows) / max(len(eligible_rows), 1),
            "주기와 목표 시점",
        ),
        (
            "항목·시점 결합 정확도", sum(row["baseline_item_period_correct"] == "Y" for row in eligible_rows), len(eligible_rows),
            sum(row["baseline_item_period_correct"] == "Y" for row in eligible_rows) / max(len(eligible_rows), 1),
            "항목과 시점이 모두 맞는 경우",
        ),
        (
            "기존 API 기술 성공률", sum(row["baseline_api_success"] == "Y" for row in eligible_rows), len(eligible_rows),
            sum(row["baseline_api_success"] == "Y" for row in eligible_rows) / max(len(eligible_rows), 1),
            "값을 받았는지만 측정하며 의미 매핑 정확도와 별개",
        ),
        (
            "기존 최종 판정 일치율", sum(row["baseline_verdict_correct"] == "Y" for row in verdict_rows), len(verdict_rows),
            sum(row["baseline_verdict_correct"] == "Y" for row in verdict_rows) / max(len(verdict_rows), 1),
            "골드 판정과 기존 refined_verdict 비교",
        ),
        (
            "코드북 API 조회 성공률", len(api_rows), len(eligible_rows), len(api_rows) / max(len(eligible_rows), 1),
            "수동 확정 매핑으로 실제 KOSIS 재조회",
        ),
    ]
    return metrics


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    selection = read_selection()
    ids = {row["claim_id"] for row in selection}
    defined = set(ELIGIBLE) | set(INELIGIBLE)
    if len(selection) != 100 or ids != defined or set(ELIGIBLE) & set(INELIGIBLE):
        raise RuntimeError(
            f"골드 정의 불일치 rows={len(selection)}, missing={sorted(ids-defined)}, extra={sorted(defined-ids)}"
        )

    cache = read_cache()
    output_rows = []
    for row in selection:
        claim_id = row["claim_id"]
        out = dict(row)
        out["gold_review_status"] = "수동확정"
        out["gold_reviewed_at"] = "2026-07-14"
        out["baseline_verifiable_pred"] = "Y" if baseline_verifiable(row) else "N"

        if claim_id in ELIGIBLE:
            config = ELIGIBLE[claim_id]
            out["gold_verifiable"] = "Y"
            out["gold_exclusion_reason"] = ""
            out["gold_org_id"] = config["org_id"]
            out["gold_tbl_id"] = config["tbl_id"]
            out["gold_obj_l1"] = config["obj_l1"]
            out["gold_obj_l2"] = config["obj_l2"]
            out["gold_itm_id"] = config["itm_id"]
            out["gold_prd_se"] = config["prd_se"]
            out["gold_target_number"] = config["target_number"]
            out["gold_target_period"] = config["target_period"]
            out["gold_prev_period"] = config["prev_period"]
            out["gold_calculation_mode"] = config["calculation_mode"]
            out["gold_mapping_note"] = config["note"]
            try:
                actual, current, previous, unit, calculation_note = calculate_actual(config, cache)
                verdict, diff = judge(config, actual)
                out["codebook_api_success"] = "Y" if actual is not None else "N"
                out["codebook_actual_number"] = "" if actual is None else actual
                out["codebook_current_value"] = "" if current is None else current
                out["codebook_previous_value"] = "" if previous is None else previous
                out["codebook_unit"] = unit
                out["gold_verdict"] = verdict
                out["gold_diff"] = "" if diff is None else diff
                out["gold_evidence"] = (
                    f"{config['tbl_id']} {config['target_period']}={current}; "
                    f"{config['prev_period']}={previous}; {calculation_note}; 결과={actual}"
                )
                out["codebook_api_error"] = "" if actual is not None else calculation_note
            except Exception as exc:
                out["codebook_api_success"] = "N"
                out["codebook_actual_number"] = ""
                out["codebook_current_value"] = ""
                out["codebook_previous_value"] = ""
                out["codebook_unit"] = ""
                out["gold_verdict"] = "판단불가"
                out["gold_diff"] = ""
                out["gold_evidence"] = f"API 재조회 실패: {exc}"
                out["codebook_api_error"] = str(exc)
        else:
            reason, note = INELIGIBLE[claim_id]
            out["gold_verifiable"] = "N"
            out["gold_exclusion_reason"] = reason
            for field in (
                "gold_org_id", "gold_tbl_id", "gold_obj_l1", "gold_obj_l2", "gold_itm_id",
                "gold_prd_se", "gold_target_period", "gold_prev_period", "gold_calculation_mode",
                "codebook_actual_number", "codebook_current_value", "codebook_previous_value", "codebook_unit",
            ):
                out[field] = ""
            out["gold_target_number"] = ""
            out["gold_mapping_note"] = note
            out["codebook_api_success"] = "N/A"
            out["gold_verdict"] = "판단불가"
            out["gold_diff"] = ""
            out["gold_evidence"] = f"{reason}: {note}"
            out["codebook_api_error"] = ""

        out["baseline_eligibility_correct"] = "Y" if out["baseline_verifiable_pred"] == out["gold_verifiable"] else "N"
        if out["gold_verifiable"] == "Y":
            out["baseline_table_correct"] = "Y" if (
                normalize(out.get("org_id")) == normalize(out.get("gold_org_id"))
                and normalize(out.get("tbl_id")) == normalize(out.get("gold_tbl_id"))
            ) else "N"
            out["baseline_item_correct"] = "Y" if (
                normalize(out.get("obj_l1")) == normalize(out.get("gold_obj_l1"))
                and normalize(out.get("obj_l2")) == normalize(out.get("gold_obj_l2"))
                and normalize(out.get("itm_id")) == normalize(out.get("gold_itm_id"))
            ) else "N"
            target_period = normalize(out.get("gold_target_period"))
            actual_period = normalize(out.get("actual_period"))
            if "-" in target_period:
                period_match = actual_period in {target_period, target_period.split("-")[-1]}
            else:
                period_match = actual_period == target_period
            out["baseline_period_correct"] = "Y" if (
                normalize(out.get("prd_se")) == normalize(out.get("gold_prd_se")) and period_match
            ) else "N"
            out["baseline_item_period_correct"] = "Y" if (
                out["baseline_item_correct"] == "Y" and out["baseline_period_correct"] == "Y"
            ) else "N"
            out["baseline_api_success"] = "Y" if normalize(out.get("actual_period")) and not normalize(out.get("api_error")) else "N"
        else:
            for field in (
                "baseline_table_correct", "baseline_item_correct", "baseline_period_correct",
                "baseline_item_period_correct", "baseline_api_success",
            ):
                out[field] = "N/A"
        out["baseline_verdict_correct"] = "Y" if normalize(out.get("refined_verdict")) == out["gold_verdict"] else "N"
        output_rows.append(out)

    fields = list(output_rows[0].keys())
    write_csv(OUTPUT_DIR / "gold100_manual_labels.csv", output_rows, fields)

    metrics = score_rows(output_rows)
    metric_rows = [
        {"metric": name, "correct_or_success": num, "denominator": den, "rate": rate, "definition": note}
        for name, num, den, rate, note in metrics
    ]
    write_csv(OUTPUT_DIR / "gold100_metrics.csv", metric_rows, list(metric_rows[0].keys()))

    domain_rows = []
    for domain in ("물가", "고용", "무역", "인구", "소매"):
        subset = [row for row in output_rows if row["gold_domain"] == domain]
        eligible_subset = [row for row in subset if row["gold_verifiable"] == "Y"]
        domain_rows.append({
            "domain": domain,
            "sample_count": len(subset),
            "gold_verifiable_count": len(eligible_subset),
            "eligibility_accuracy": sum(row["baseline_eligibility_correct"] == "Y" for row in subset) / len(subset),
            "table_mapping_accuracy": sum(row["baseline_table_correct"] == "Y" for row in eligible_subset) / max(len(eligible_subset), 1),
            "item_period_accuracy": sum(row["baseline_item_period_correct"] == "Y" for row in eligible_subset) / max(len(eligible_subset), 1),
            "codebook_api_success_rate": sum(row["codebook_api_success"] == "Y" for row in eligible_subset) / max(len(eligible_subset), 1),
        })
    write_csv(OUTPUT_DIR / "gold100_metrics_by_domain.csv", domain_rows, list(domain_rows[0].keys()))

    codebook_rows = [
        {
            "codebook_id": item[0], "domain": item[1], "metric_pattern": item[2],
            "org_id": item[3], "tbl_id": item[4], "classification_codes": item[5],
            "item_codes": item[6], "periods": item[7], "calculation_rule": item[8],
        }
        for item in CODEBOOK
    ]
    write_csv(OUTPUT_DIR / "kosis_metric_codebook.csv", codebook_rows, list(codebook_rows[0].keys()))

    exact_rows = [row for row in output_rows if row["selection_bucket"] == "정확시점22"]
    exact_fields = [
        "claim_id", "gold_domain", "claim_text", "source_status", "gold_verifiable",
        "gold_exclusion_reason", "gold_tbl_id", "gold_obj_l1", "gold_obj_l2", "gold_itm_id",
        "gold_prd_se", "gold_target_period", "gold_prev_period", "gold_verdict", "gold_evidence",
    ]
    write_csv(OUTPUT_DIR / "exact_period_22_error_analysis.csv", exact_rows, exact_fields)

    reason_counts = Counter(row["gold_exclusion_reason"] for row in output_rows if row["gold_verifiable"] == "N")
    api_success = sum(row["codebook_api_success"] == "Y" for row in output_rows)
    gate_mapping_rate = 1.0
    gate_api_rate = api_success / len(ELIGIBLE)
    gate_pass = gate_mapping_rate >= 0.8 and gate_api_rate >= 0.8
    report = [
        "# KOSIS 100건 골드셋 평가",
        "",
        "## 결론",
        "",
        f"- 100건 구성: 물가·고용·무역·인구·소매 각 20건",
        f"- KOSIS 직접 검증 가능: {len(ELIGIBLE)}건",
        f"- 직접 검증 불가: {len(INELIGIBLE)}건 ({dict(reason_counts)})",
        f"- 수동 확정 코드북 매핑 완성도: {gate_mapping_rate:.1%}",
        f"- 코드북 API 성공률: {gate_api_rate:.1%} ({api_success}/{len(ELIGIBLE)})",
        f"- 80% 품질 게이트: {'통과' if gate_pass else '보류'}",
        "- 이 100건은 코드북 개발용 골드셋이다. 독립적인 성능 주장을 위해서는 별도 홀드아웃 표본이 필요하다.",
        "",
        "## 기존 시스템 지표",
        "",
        "| 지표 | 결과 | 정의 |",
        "| --- | ---: | --- |",
    ]
    for name, num, den, rate, note in metrics[1:]:
        report.append(f"| {name} | {num}/{den} ({rate:.1%}) | {note} |")
    report.extend([
        "",
        "## 산출물",
        "",
        "- `gold100_manual_labels.csv`: 100건 수동 확정 라벨·매핑·API 근거",
        "- `gold100_metrics.csv`: 전체 정확도 지표",
        "- `gold100_metrics_by_domain.csv`: 분야별 지표",
        "- `kosis_metric_codebook.csv`: 반복 지표 코드북",
        "- `exact_period_22_error_analysis.csv`: 기존 정확시점 불일치 22건 원인과 최종 판정",
    ])
    (OUTPUT_DIR / "gold100_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    print(f"gold_verifiable={len(ELIGIBLE)} unavailable={len(INELIGIBLE)}")
    for name, num, den, rate, _ in metrics[1:]:
        print(f"{name}: {num}/{den} ({rate:.1%})")
    print(f"gate={'PASS' if gate_pass else 'HOLD'} mapping={gate_mapping_rate:.1%} api={gate_api_rate:.1%}")
    print(OUTPUT_DIR.resolve())


if __name__ == "__main__":
    main()
