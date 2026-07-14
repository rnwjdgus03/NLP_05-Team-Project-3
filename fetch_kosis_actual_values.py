"""
bteam_kosis_review_manual_todo.csv 에서 org_id/tbl_id(+가능하면 obj_l1/itm_id/prd_se)가
확정된 행들을 대상으로, KOSIS Open API에서 실제 통계 수치를 가져와
verify_claim.py가 바로 사용할 수 있는 table_claim_mapping.csv를 만드는 연결 스크립트.

*** 반드시 KOSIS API(kosis.kr)에 접속 가능한 로컬 환경(PowerShell)에서 실행할 것 ***

동작 방식:
  1) org_id/tbl_id가 채워진 행만 대상 (obj_l1/itm_id가 비어있으면 "ALL"로 조회)
  2) kosis_api_test.get_stat_data()로 최근 N개 시점 데이터를 가져옴
     (여러 시점을 가져온 뒤, claim의 'year' 컬럼과 매칭되는 시점을 우선 채택.
      year 정보가 없거나 매칭 실패 시 가장 최근 시점 값을 사용)
  3) 원본 컬럼 + actual_value / actual_period (해당 시점 원자료값)
     + actual_prev_value / actual_prev_period (직전 시점 원자료값)
     + actual_change_pct / actual_change_point (전기 대비 증감률(%) / 증감폭(포인트))
     + api_error 컬럼을 추가해서 table_claim_mapping.csv로 저장.
     증감률(%) claim은 actual_change_pct, 포인트 변화(CSI 등) claim은 actual_change_point,
     수준값(가격/금액 등) claim은 actual_value를 verify_claim.py가 자동으로 골라서 비교한다.

재실행해도 안전: 이미 actual_value가 채워진 행은 다시 API를 호출하지 않음
(캐시 파일이 있으면 이어서 진행 - 중간에 끊겨도 처음부터 다시 안 해도 됨).

사용법:
    python fetch_kosis_actual_values.py
    python fetch_kosis_actual_values.py --limit 50   # 테스트로 50건만
"""

import argparse
import ast
import csv
from datetime import datetime
from pathlib import Path
import re
import sys
import time

from kosis_api_test import get_stat_data

SRC_PATH = "outputs/bteam_review/bteam_kosis_review_manual_todo.csv"
OUT_PATH = "table_claim_mapping.csv"
SLEEP_SEC = 0.3  # API 과호출 방지용 딜레이

csv.field_size_limit(sys.maxsize)

# claim_text에 "전년동월/전년동기 대비"(YoY) 인지 "전월/전달/전분기 대비"(연속 시점,
# MoM/QoQ) 인지 표시가 있으면 그에 맞는 시차(lag)로 이전 시점을 골라야 증감률이
# 실제 claim과 같은 기준으로 계산된다. (이게 없으면 무조건 "바로 직전 시점"과 비교하게
# 되어, 전년동월대비 claim인데 전월비로 계산해버리는 오류가 생김)
YOY_RE = re.compile(r"전년\s*동월|전년\s*동기|전년\s*동분기|작년\s*같은|작년\s*동기|전년\s*대비|작년\s*대비")
SEQUENTIAL_RE = re.compile(
    r"전월\s*대비|전월\s*보다|전달\s*보다|전달\s*대비|전분기\s*대비|전분기\s*보다|"
    r"직전\s*달|직전\s*분기|직전\s*월|전달비"
)
QUARTER_RE = re.compile(r"([1-4])\s*분기")
EXPLICIT_YEAR_MONTH_RE = re.compile(r"(20\d{2})\s*년\s*(1[0-2]|[1-9])\s*월")
MONTH_RE = re.compile(r"(?<!\d)(1[0-2]|[1-9])\s*월")
HALF_RE = re.compile(r"(상|하)반기")


def detect_comparison_mode(claim_text):
    """claim_text에서 YOY(전년동월/동기대비) vs SEQUENTIAL(전월/전분기대비) 여부 추정."""
    if not claim_text:
        return None
    if YOY_RE.search(claim_text):
        return "YOY"
    if SEQUENTIAL_RE.search(claim_text):
        return "SEQUENTIAL"
    return None


def infer_year_from_context(row):
    """
    'year' 컬럼이 비어있는 경우가 많다 - "작년 4분기", "올해 성장률"처럼 명시적 연도
    숫자 없이 상대적 시간 표현만 쓰는 claim들. 이런 경우 기사 게재일(date 컬럼)을
    기준으로 "작년"=게재연도-1, "올해"=게재연도, "재작년"=게재연도-2 로 추정한다.
    """
    date_str = (row.get("date") or "").strip()
    m = re.match(r"(\d{4})", date_str)
    if not m:
        return []
    article_year = int(m.group(1))
    text = row.get("claim_text", "") or ""
    if "재작년" in text or "2년 전" in text or "2년전" in text:
        return [article_year - 2]
    if "작년" in text or "지난해" in text or "전년" in text:
        return [article_year - 1]
    if "올해" in text or "금년" in text:
        return [article_year]
    return []


def detect_target_quarter(claim_text):
    """claim_text에 "4분기"처럼 특정 분기가 명시돼 있으면 그 분기 번호(1~4) 반환."""
    if not claim_text:
        return None
    m = QUARTER_RE.search(claim_text)
    return int(m.group(1)) if m else None


def quarter_of(prd_de):
    """
    PRD_DE 문자열에서 분기(1~4)를 추출. KOSIS 응답에서 실제로 관찰된 형식은
    "202401"~"202404"(연도4자리 + 분기 2자리, 0패딩) 이지만, 혹시 모를 다른 형식
    ("2024Q4", "20241")도 대비해서 같이 처리한다.
    """
    s = str(prd_de)
    m = re.search(r"[Qq]([1-4])$", s)
    if m:
        return int(m.group(1))
    if len(s) == 6 and s[:4].isdigit() and s[4:6] in ("01", "02", "03", "04"):
        return int(s[4:6])
    if len(s) == 5 and s[:4].isdigit() and s[4] in "1234":
        return int(s[4])
    return None


def parse_years(year_str):
    """claim의 'year' 컬럼(문자열로 저장된 리스트, 예: "['2020']")을 정수 리스트로 변환."""
    if not year_str or not year_str.strip():
        return []
    try:
        val = ast.literal_eval(year_str)
        if isinstance(val, (list, tuple)):
            return [int(y) for y in val if str(y).strip().isdigit()]
        if str(val).strip().isdigit():
            return [int(val)]
    except Exception:
        pass
    return []


def shift_month(year, month, delta):
    month_index = year * 12 + (month - 1) + delta
    return month_index // 12, month_index % 12 + 1


def infer_target_period(row, prd_se):
    """기사 날짜와 상대·명시 시점 표현으로 KOSIS PRD_DE 목표값을 만든다."""
    text = row.get("claim_text", "") or ""
    article_date = None
    try:
        article_date = datetime.strptime((row.get("date") or "")[:10], "%Y-%m-%d")
    except ValueError:
        pass

    explicit_year_month = EXPLICIT_YEAR_MONTH_RE.search(text)
    years = parse_years(row.get("year", ""))
    contextual_years = years or infer_year_from_context(row)

    if prd_se == "M":
        if explicit_year_month:
            return f"{int(explicit_year_month.group(1)):04d}{int(explicit_year_month.group(2)):02d}"
        month_match = MONTH_RE.search(text)
        if month_match:
            month = int(month_match.group(1))
            if article_date:
                if re.search(r"지난해|작년|전년", text):
                    year = article_date.year - 1
                else:
                    year = article_date.year - 1 if month > article_date.month else article_date.year
            elif contextual_years:
                year = contextual_years[0]
            else:
                return None
            return f"{year:04d}{month:02d}"
        if article_date and re.search(r"지난달|전월|전달", text):
            year, month = shift_month(article_date.year, article_date.month, -1)
            return f"{year:04d}{month:02d}"
        if article_date and re.search(r"이달|이번\s*달|당월", text):
            return f"{article_date.year:04d}{article_date.month:02d}"
        return None

    target_year = contextual_years[0] if contextual_years else None
    if target_year is None and article_date:
        target_year = article_date.year

    if prd_se == "Q":
        quarter = detect_target_quarter(text)
        return f"{target_year:04d}Q{quarter}" if target_year and quarter else None

    if prd_se == "H":
        half_match = HALF_RE.search(text)
        if target_year and half_match:
            half = 1 if half_match.group(1) == "상" else 2
            return f"{target_year:04d}H{half}"
        return None

    if prd_se == "Y" and target_year:
        return f"{target_year:04d}"
    return None


def _to_float(value):
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def pick_best_match(
    data_rows,
    target_years,
    target_period=None,
    target_quarter=None,
    comparison_mode=None,
    prd_se="Y",
):
    """
    KOSIS API 응답(data_rows, 각 row에 PRD_DE=기간, DT=값)에서
    target_years(+가능하면 target_quarter)에 해당하는 시점을 우선 채택.
    없으면 가장 최근(마지막) 시점 사용.

    '이전 시점'은 comparison_mode에 따라 다르게 고른다:
      - YOY(전년동월/동기대비): 월별이면 12개 전, 분기별이면 4개 전 시점과 비교
      - SEQUENTIAL(전월/전분기대비) 또는 불명확: 바로 직전(1개 전) 시점과 비교
    (이걸 구분 안 하면 "전년동월대비 6.6%증가" 같은 claim을 전월비로 잘못 계산하게 됨)

    반환: (현재값, 현재시점, 이전값, 이전시점)
    """
    if not data_rows:
        return None, None, None, None

    def year_of(prd_de):
        # PRD_DE 예: "2024", "2024Q4", "202412" 등 -> 앞 4자리가 연도
        s = str(prd_de)
        return int(s[:4]) if s[:4].isdigit() else None

    def period_key(prd_de):
        value = str(prd_de)
        year = year_of(value)
        digits = re.sub(r"\D", "", value)
        if prd_se == "M" and len(digits) >= 6:
            return digits[:6]
        if prd_se == "Q" and year:
            quarter = quarter_of(value)
            return f"{year:04d}Q{quarter}" if quarter else None
        if prd_se == "H" and year:
            match = re.search(r"(?:H|0?)([12])$", value, re.IGNORECASE)
            return f"{year:04d}H{int(match.group(1))}" if match else None
        if prd_se == "Y" and year:
            return f"{year:04d}"
        return None

    sorted_rows = sorted(data_rows, key=lambda r: str(r.get("PRD_DE", "")))

    idx = None
    if target_period:
        exact_matches = [
            i for i, row in enumerate(sorted_rows)
            if period_key(row.get("PRD_DE", "")) == target_period
        ]
        if exact_matches:
            idx = exact_matches[-1]
        else:
            return None, target_period, None, None

    if target_years:
        year_matches = [i for i, row in enumerate(sorted_rows) if year_of(row.get("PRD_DE", "")) in target_years]
        if year_matches and target_quarter and prd_se == "Q":
            quarter_matches = [i for i in year_matches if quarter_of(sorted_rows[i].get("PRD_DE", "")) == target_quarter]
            if quarter_matches:
                idx = quarter_matches[0]
        if idx is None and year_matches:
            idx = year_matches[-1]

    if idx is None:
        idx = len(sorted_rows) - 1  # 매칭 실패 -> 가장 최근 시점

    current = sorted_rows[idx]

    if comparison_mode == "YOY":
        lag = 12 if prd_se == "M" else 4 if prd_se == "Q" else 1
    else:
        lag = 1  # SEQUENTIAL(전월/전분기비) 또는 불명확 -> 바로 직전 시점

    prev_idx = idx - lag
    prev = sorted_rows[prev_idx] if prev_idx >= 0 else None

    return (
        current.get("DT"), current.get("PRD_DE"),
        prev.get("DT") if prev else None, prev.get("PRD_DE") if prev else None,
    )


def load_cache(output_path):
    try:
        with open(output_path, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        return {r["claim_id"]: r for r in rows}
    except FileNotFoundError:
        return {}


def main(
    input_path=SRC_PATH,
    output_path=OUT_PATH,
    limit=None,
    sleep_sec=SLEEP_SEC,
    require_complete=False,
):
    with open(input_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        src_rows = list(reader)
        fieldnames = list(reader.fieldnames)

    print(f"전체 행: {len(src_rows)}")

    required_fields = ("org_id", "tbl_id", "obj_l1", "itm_id")
    if require_complete:
        targets = [
            row
            for row in src_rows
            if all((row.get(field) or "").strip() for field in required_fields)
        ]
        print(f"주요 ID 4종 확정된 행: {len(targets)}")
    else:
        targets = [
            row
            for row in src_rows
            if (row.get("org_id") or "").strip() and (row.get("tbl_id") or "").strip()
        ]
        print(f"org_id/tbl_id 확정된 행: {len(targets)}")

    cache = load_cache(output_path)
    print(f"기존 캐시({output_path})에 이미 처리된 행: {len(cache)}")

    added_fields = [
        "actual_value", "actual_period",
        "actual_prev_value", "actual_prev_period",
        "actual_change_pct", "actual_change_point",
        "api_error",
    ]
    out_fieldnames = fieldnames + [field for field in added_fields if field not in fieldnames]
    out_rows = []

    processed = 0
    fetched = 0
    errors = 0
    skipped_cached = 0

    for r in targets:
        cid = r["claim_id"]
        if limit and processed >= limit:
            break
        processed += 1

        # "actual_change_pct" 키 존재 여부로 새 버전(증감 계산 포함) 캐시인지 판단.
        # 예전 버전 캐시(그 컬럼 없음)는 재사용하지 않고 다시 조회한다.
        if (
            cid in cache
            and "actual_change_pct" in cache[cid]
            and cache[cid].get("actual_value", "").strip()
        ):
            out_rows.append(cache[cid])
            skipped_cached += 1
            continue

        org_id = r["org_id"].strip()
        tbl_id = r["tbl_id"].strip()
        obj_l1 = r.get("obj_l1", "").strip() or "ALL"
        itm_id = r.get("itm_id", "").strip() or "ALL"
        prd_se = r.get("prd_se", "").strip() or "Y"

        out_row = dict(r)
        try:
            data = get_stat_data(
                org_id=org_id, tbl_id=tbl_id, obj_l1=obj_l1, itm_id=itm_id,
                prd_se=prd_se, new_est_prd_cnt=30,
            )
            years = parse_years(r.get("year", "")) or infer_year_from_context(r)
            claim_text = r.get("claim_text", "")
            comparison_mode = detect_comparison_mode(claim_text)
            target_quarter = detect_target_quarter(claim_text)
            target_period = infer_target_period(r, prd_se)
            value, period, prev_value, prev_period = pick_best_match(
                data, years, target_period=target_period, target_quarter=target_quarter,
                comparison_mode=comparison_mode, prd_se=prd_se,
            )

            out_row["actual_value"] = value if value is not None else ""
            out_row["actual_period"] = period if period is not None else ""
            out_row["actual_prev_value"] = prev_value if prev_value is not None else ""
            out_row["actual_prev_period"] = prev_period if prev_period is not None else ""

            cur_f, prev_f = _to_float(value), _to_float(prev_value)
            if cur_f is not None and prev_f is not None:
                out_row["actual_change_point"] = cur_f - prev_f
                out_row["actual_change_pct"] = (
                    (cur_f - prev_f) / prev_f * 100 if prev_f != 0 else ""
                )
            else:
                out_row["actual_change_point"] = ""
                out_row["actual_change_pct"] = ""

            out_row["api_error"] = "" if value is not None else "데이터 없음(응답은 성공했으나 매칭 실패)"
            if value is not None:
                fetched += 1
            else:
                errors += 1
        except Exception as e:
            out_row["actual_value"] = ""
            out_row["actual_period"] = ""
            out_row["actual_prev_value"] = ""
            out_row["actual_prev_period"] = ""
            out_row["actual_change_point"] = ""
            out_row["actual_change_pct"] = ""
            out_row["api_error"] = str(e)
            errors += 1

        out_rows.append(out_row)
        time.sleep(sleep_sec)

        if processed % 20 == 0:
            print(f"  진행: {processed}/{len(targets)} (성공 {fetched}, 실패/미매칭 {errors}, 캐시재사용 {skipped_cached})")
            # 중간 저장 (끊겨도 이어서 할 수 있도록)
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=out_fieldnames, lineterminator="\n")
                w.writeheader()
                w.writerows(out_rows)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=out_fieldnames, lineterminator="\n")
        w.writeheader()
        w.writerows(out_rows)

    print(f"\n완료 -> {output_path}")
    print(f"처리: {processed}건 | 성공: {fetched}건 | 실패/미매칭: {errors}건 | 캐시재사용: {skipped_cached}건")
    print("이제 'python verify_claim.py --input table_claim_mapping.csv --output verified_claims.csv' 실행 가능")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=SRC_PATH, help="검토 완료 CSV 경로")
    ap.add_argument("--output", default=OUT_PATH, help="KOSIS 실제값을 추가할 CSV 경로")
    ap.add_argument("--limit", type=int, default=None, help="테스트용으로 앞에서 N건만 처리")
    ap.add_argument("--sleep", type=float, default=SLEEP_SEC, help="API 호출 사이 대기 초")
    ap.add_argument(
        "--require-complete",
        action="store_true",
        help="org_id/tbl_id/obj_l1/itm_id가 모두 채워진 행만 처리",
    )
    args = ap.parse_args()
    main(
        input_path=args.input,
        output_path=args.output,
        limit=args.limit,
        sleep_sec=args.sleep,
        require_complete=args.require_complete,
    )
