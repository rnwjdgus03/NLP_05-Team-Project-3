"""KOSIS 매핑·검증 (코드북 CSV 외부화 버전)

정현님 verify_claim_schema_v3_pilot.py의 로직을 계승하되, 매핑 규칙을 코드가 아닌
CSV(data/claims/kosis_mapping_codebook_v1.csv)에서 읽는다. 규칙 추가·수정은 CSV만
갱신하면 되므로 코드 버전 불일치로 매핑 결과가 달라지는 사고를 방지한다.

개선점 (기존 대비):
- 코드북 CSV 외부화 (규칙 = 데이터)
- value_min/max 범위 판정 ("1%대" -> 1.0~1.9 구간 포함 여부)
- measurement_role이 이전값/참고값/목표값이면 판정 제외
- 단위 배율(unit_multiplier)을 규칙별 컬럼으로 관리
- 현행 measurement 스키마는 국내공식통계 + KOSIS_VALUE만 매핑
- 구 스키마는 measurement_usage가 없으므로 기존 동작 유지

사용법:
  python map_verify_kosis.py --input hcx_extracted_isclaim51.csv --output outputs/bteam_review/mapped.csv

주의: KOSIS API 접속 가능한 로컬에서 실행 (.env의 KOSIS_API_KEY 사용).
"""
import argparse
import csv
import re
import sys
import time
from collections import Counter
from pathlib import Path

from kosis_api_test import get_stat_data

csv.field_size_limit(2 ** 31 - 1)

CODEBOOK = Path("data/claims/kosis_mapping_codebook_v1.csv")
SKIP_ROLES = {"이전값", "참고값", "목표값"}

MONTH_KO_RE = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월")
QUARTER_RE = re.compile(r"(\d{4})\s*Q\s*([1-4])", re.IGNORECASE)
YEAR_RE = re.compile(r"(\d{4})")
NUMBER_RE = re.compile(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?")


def nz(v):
    s = str(v or "").strip()
    return "" if s in ("", "nan", "None", "-") else s


def mapping_exclusion_reason(row):
    """Return why a measurement must not reach KOSIS mapping, or an empty string."""
    usage = nz(row.get("measurement_usage"))
    scope = nz(row.get("claim_domain_scope"))
    if usage and usage != "KOSIS_VALUE":
        return f"measurement_usage={usage} KOSIS 매핑 제외"
    if usage and scope and scope != "국내공식통계":
        return f"claim_domain_scope={scope} KOSIS 매핑 제외"
    if usage == "KOSIS_VALUE" and "measurement_indicator" in row:
        binding_source = nz(row.get("measurement_binding_source"))
        if binding_source and binding_source != "hcx":
            return f"measurement_binding_source={binding_source} 자동매핑 제외"
        for field in ("measurement_indicator", "measurement_period", "measurement_prd_se"):
            if not nz(row.get(field)):
                return f"{field} 누락으로 KOSIS 매핑 제외"
    if not nz(row.get("value")) or not nz(row.get("unit")):
        return "value/unit 누락으로 KOSIS 매핑 제외"
    if nz(row.get("value_type")) == "순위" or nz(row.get("unit")) == "위":
        return "순위값은 KOSIS 원자료와 직접 비교 불가"
    role = nz(row.get("measurement_role"))
    if role in SKIP_ROLES:
        return f"role={role} 판정 제외"
    return ""


def effective_indicator(row):
    return nz(row.get("measurement_indicator")) or nz(row.get("indicator"))


def effective_period(row):
    return nz(row.get("measurement_period")) or nz(row.get("period"))


def effective_prd_se(row):
    return nz(row.get("measurement_prd_se")) or nz(row.get("prd_se"))


def norm_ind(s):
    return re.sub(r"[\s·()]", "", str(s or ""))


def to_float(v):
    m = NUMBER_RE.search(str(v or "").replace(",", ""))
    try:
        return float(m.group()) if m else None
    except ValueError:
        return None


def load_codebook(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rules = [r for r in csv.DictReader(f)]
    return rules


def find_rule(rules, indicator, age_group, prd_se):
    """조건이 더 구체적으로 맞는 규칙 우선, 그다음 일반 규칙."""
    key = norm_ind(indicator)
    cands = [r for r in rules if r["indicator_key"] == key]
    if not cands:
        return None, "코드북에 지표 없음"

    def score(r):
        s = 0
        if nz(r["cond_age_group"]):
            if nz(r["cond_age_group"]) != nz(age_group):
                return -1
            s += 2
        if nz(r["cond_prd_se"]):
            if nz(r["cond_prd_se"]) != nz(prd_se):
                return -1
            s += 1
        if r["verify"] == "Y":
            s += 1
        return s

    scored = [(score(r), r) for r in cands]
    scored = [x for x in scored if x[0] >= 0]
    if not scored:
        return None, "지표는 있으나 조건(연령/주기) 불일치"
    return max(scored, key=lambda x: x[0])[1], ""


def normalize_period(period, prd_se):
    t = nz(period)
    if not t or "|" in t:
        return ""
    if "~" in t:
        t = t.split("~")[-1]
    m = MONTH_KO_RE.search(t)
    if m:
        return f"{int(m.group(1)):04d}{int(m.group(2)):02d}"
    m = QUARTER_RE.search(t)
    if m:
        return f"{int(m.group(1)):04d}0{m.group(2)}"
    if prd_se == "Y":
        m = YEAR_RE.search(t)
        return m.group(1) if m else ""
    if re.fullmatch(r"\d{6}", t) or re.fullmatch(r"\d{4}", t):
        return t
    return ""


def previous_period(norm, prd_se, base):
    if prd_se == "M" and len(norm) == 6:
        y, mo = int(norm[:4]), int(norm[4:6])
        if base in {"전년동월", "전년동기"}:
            return f"{y - 1}{mo:02d}"
        if base == "전월":
            y, mo = (y - 1, 12) if mo == 1 else (y, mo - 1)
            return f"{y}{mo:02d}"
    if prd_se == "Y" and len(norm) == 4:
        if base in {"전년", "전년동월", "전년동기"}:
            return str(int(norm) - 1)
    if prd_se == "Q" and len(norm) == 6:
        y, q = int(norm[:4]), int(norm[5])
        if base in {"전년동월", "전년동기"}:
            return f"{y - 1}0{q}"
        if base == "전분기":
            y, q = (y - 1, 4) if q == 1 else (y, q - 1)
            return f"{y}0{q}"
    return ""


def pick(rows, prd_de):
    for row in rows or []:
        if str(row.get("PRD_DE", "")) == prd_de:
            return row
    return None


def clamp_future(norm, article_date):
    """기사일보다 미래인 시점은 상대시점 역산 오류로 보고 1년 당긴다 (예: 기사 2025-01의 '12월' -> 202412)."""
    m = re.match(r"(\d{4})-(\d{2})", str(article_date or ""))
    if not m or not norm:
        return norm
    art = m.group(1) + m.group(2)
    if len(norm) == 6 and norm.isdigit() and norm > art:
        return f"{int(norm[:4]) - 1}{norm[4:6]}"
    if len(norm) == 4 and norm.isdigit() and norm > art[:4]:
        return str(int(norm) - 1)
    if len(norm) == 6 and norm[4] == "0" and not norm.isdigit() is False and norm[:4] > art[:4]:
        return f"{int(norm[:4]) - 1}{norm[4:]}"
    return norm


def actual_for(row, rule, data_rows):
    prd_se = nz(rule.get("cond_prd_se")) or effective_prd_se(row)
    norm = normalize_period(effective_period(row), prd_se) or normalize_period(row.get("period_end"), prd_se)
    norm = clamp_future(norm, row.get("date"))
    if not norm:
        return None, "", "", "시점 정규화 실패"
    cur = pick(data_rows, norm)
    if cur is None:
        return None, "", "", f"해당 시점({norm}) KOSIS 값 없음"
    val = to_float(cur.get("DT"))
    if val is None:
        return None, norm, "", "KOSIS DT 숫자 변환 실패"
    mult = float(rule.get("unit_multiplier") or 1)
    val *= mult

    value_type = nz(row.get("value_type"))
    unit = nz(row.get("unit"))
    if rule.get("rate_table") == "Y":
        return val, norm, "", "등락률 표 actual_value 사용"
    if value_type in {"증감률", "증감량"} or unit in {"%p", "%포인트"}:
        base = nz(row.get("change_base")) or "전년동월"
        prev_norm = previous_period(norm, prd_se, base)
        prev = pick(data_rows, prev_norm)
        if prev is None:
            return None, norm, prev_norm, "비교 기준 이전 시점 KOSIS 값 없음"
        pval = to_float(prev.get("DT"))
        if pval is None:
            return None, norm, prev_norm, "이전 시점 DT 숫자 변환 실패"
        pval *= mult
        if value_type == "증감률":
            if pval == 0:
                return None, norm, prev_norm, "이전값 0"
            return (val - pval) / pval * 100, norm, prev_norm, "원자료 증감률 계산"
        return val - pval, norm, prev_norm, "원자료 증감량 계산"
    return val, norm, "", "수준값 actual_value 사용"


def judge(row, actual):
    target = to_float(row.get("value"))
    if target is None:
        return "판단불가", "", "target 없음"
    if actual is None:
        return "판단불가", "", "actual 없음"
    if nz(row.get("value_type")) in {"증감률", "증감량"} and nz(row.get("direction")) in {"감소", "하락"}:
        target = -abs(target)
    # 범위 표현 (value_min/max) 판정
    vmin, vmax = to_float(row.get("value_min")), to_float(row.get("value_max"))
    if vmin is not None and vmax is not None:
        ok = vmin <= actual <= vmax
        return ("일치" if ok else "불일치"), abs(actual - target), f"범위판정 [{vmin},{vmax}] actual={actual:.3f}"
    unit = nz(row.get("unit"))
    if nz(row.get("value_type")) == "증감률" or unit in {"%", "%p", "%포인트"}:
        diff = abs(target - actual)
        return ("일치" if diff <= 0.3 else "불일치"), diff, f"절대오차={diff:.3f}, 허용=0.3"
    if actual == 0:
        return "판단불가", "", "actual=0"
    diff = abs(target - actual) / abs(actual)
    return ("일치" if diff <= 0.05 else "불일치"), diff, f"상대오차={diff:.3f}, 허용=0.05"


EXTRA = ["org_id", "tbl_id", "obj_l1", "obj_l2", "itm_id", "mapping_source",
         "actual_value", "actual_period", "actual_prev_period", "verdict", "diff", "judge_note"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", default="outputs/bteam_review/mapped_verified.csv")
    ap.add_argument("--codebook", default=str(CODEBOOK))
    a = ap.parse_args()

    rules = load_codebook(a.codebook)
    with open(a.input, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    fieldnames = list(rows[0].keys()) + [c for c in EXTRA if c not in rows[0]]

    cache = {}
    out_rows = []
    for row in rows:
        out = dict(row)
        out.update({c: "" for c in EXTRA})
        out["mapping_source"] = a.codebook

        def finish(verdict, note, rule=None, actual=None, ap_="", pp=""):
            if rule:
                out.update({"org_id": rule["org_id"], "tbl_id": rule["tbl_id"],
                            "obj_l1": rule["obj_l1"], "obj_l2": rule["obj_l2"],
                            "itm_id": rule["itm_id"]})
            out.update({"verdict": verdict, "judge_note": note,
                        "actual_value": "" if actual is None else actual,
                        "actual_period": ap_, "actual_prev_period": pp})
            out_rows.append(out)

        # 구 스키마는 기존 동작을 유지하고, measurement-first 스키마에서는
        # 실제 통계값만 KOSIS 매핑으로 전달한다.
        exclusion_reason = mapping_exclusion_reason(row)
        if exclusion_reason:
            finish("판단불가", exclusion_reason); continue

        rule, why = find_rule(rules, effective_indicator(row), row.get("age_group"), effective_prd_se(row))
        if rule is None:
            finish("판단불가", why); continue
        if rule["verify"] != "Y" or not nz(rule["itm_id"]):
            finish("판단불가", f"표 후보만 매핑: {rule['table_note']}", rule); continue

        rule_prd = nz(rule.get("cond_prd_se")) or effective_prd_se(row) or "M"
        key = (rule["org_id"], rule["tbl_id"], rule["obj_l1"], rule["obj_l2"], rule["itm_id"], rule_prd)
        try:
            if key not in cache:
                kw = {}
                if nz(rule["obj_l2"]):
                    kw["objL2"] = rule["obj_l2"]
                cache[key] = get_stat_data(org_id=rule["org_id"], tbl_id=rule["tbl_id"],
                                           obj_l1=rule["obj_l1"], itm_id=rule["itm_id"],
                                           prd_se=rule_prd, new_est_prd_cnt=180, **kw)
                time.sleep(0.1)
            actual, ap_, pp, note = actual_for(row, rule, cache[key])
            verdict, diff, jnote = judge(row, actual)
            out["diff"] = diff
            finish(verdict, f"{note}; {jnote}; {rule['table_note']}", rule, actual, ap_, pp)
        except Exception as exc:
            finish("판단불가", f"KOSIS 조회 실패: {exc}", rule)

    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    with open(a.output, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)
    print(f"완료 -> {a.output}")
    print(Counter(r["verdict"] for r in out_rows))


if __name__ == "__main__":
    sys.exit(main())
