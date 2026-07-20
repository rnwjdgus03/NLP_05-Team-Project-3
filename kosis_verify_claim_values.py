#!/usr/bin/env python3
"""
KOSIS API 기반 claim 값 검증기.

입력
- run_kosis_index_pipeline.py가 만든 *_kosis_index_candidates_with_meta.csv

출력
- candidate_rank=1 기준으로 KOSIS 실제 데이터 API를 호출해
  claim_value / kosis_actual_value / verdict(일치/불일치/판단불가)를 붙인 CSV

주의
- 이 파일은 예전 하드코딩 verifier를 대체하기 위한 새 검증 단계다.
- tbl_id 후보는 입력 파일의 candidate_rank=1을 사용한다.
- obj/item 코드는 KOSIS meta API와 claim 텍스트/indicator 힌트로 고른다.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

PROJECT_DIR = Path('/Users/gu/myproject/NLP_05-Team-Project-3')
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from kosis_api_test import get_meta, get_stat_data  # noqa: E402

csv.field_size_limit(sys.maxsize)

TRUTHY = {'true', '1', 'y', 'yes', 't'}

BROAD_OBJ_HINTS = {
    '반도체': {
        'prefer': ['전자집적회로', '초소형', '메모리', '반도체'],
        'strong_code_prefix': ['13102112831A.7764'],
        'avoid': ['감광성', '다이오드', '트랜지스터', '부분품', '액정', '웨이퍼', '장비', '기계', '기구'],
    },
    '자동차': {
        'prefer': ['승용자동차', '자동차', '차량'],
        'strong_code_prefix': ['13102112831A.781'],
        'avoid': ['타이어', '부분품', '부품'],
    },
    '화장품': {
        'prefer': ['화장품', '화장용품'],
        'strong_code_prefix': [],
        'avoid': ['탈모제', '향수'],
    },
}


def read_csv(path: Path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
        return rows, list(rows[0].keys()) if rows else []


def write_csv(path: Path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def compact(text):
    return re.sub(r'\s+', '', str(text or '').strip())


def tokens(text):
    return [t for t in re.findall(r'[가-힣A-Za-z0-9]+', str(text or '')) if len(t) >= 2]


def parse_number(value):
    s = str(value or '').strip()
    if not s or s in {'-', '—', 'nan', 'None'}:
        return None
    s = s.replace(',', '')
    m = re.search(r'-?\d+(?:\.\d+)?', s)
    return float(m.group()) if m else None


def parse_period(period):
    s = str(period or '').strip()
    if not s or s == '-':
        return ''
    # 2025-03, 2025.03, 202503 모두 월로 인정
    m = re.search(r'(20\d{2})\D?(0[1-9]|1[0-2])', s)
    if m:
        return m.group(1) + m.group(2)
    m = re.search(r'(19\d{2}|20\d{2})', s)
    if m:
        return m.group(1)
    return s


def normalize_prd_se(prd_se, period):
    s = str(prd_se or '').strip().upper()
    if s in {'Y', 'M', 'Q', 'H'}:
        return s
    p = parse_period(period)
    if len(p) == 6:
        return 'M'
    return 'Y'


def period_range(period, prd_se):
    p = parse_period(period)
    if not p:
        return {}, '기간 없음'
    if prd_se == 'M':
        if len(p) == 6:
            return {'startPrdDe': p, 'endPrdDe': p}, ''
        if len(p) == 4:
            return {'startPrdDe': p + '01', 'endPrdDe': p + '12'}, '연도만 있어 월자료 1~12월 합산 시도'
    if prd_se == 'Q':
        if len(p) == 4:
            return {'startPrdDe': p + '01', 'endPrdDe': p + '04'}, '연도만 있어 분기자료 1~4분기 합산 시도'
    return {'startPrdDe': p[:4], 'endPrdDe': p[:4]}, ''


def score_name(name, hint_text):
    c_name = compact(name)
    score = 0
    for t in tokens(hint_text):
        ct = compact(t)
        if ct and ct in c_name:
            score += min(len(ct), 8)
    return score


def unit_kind(unit):
    u = compact(unit)
    if not u or u == '-':
        return 'unknown'
    if '%' in u or '퍼센트' in u or '비율' in u:
        return 'rate'
    if any(x in u for x in ('원', '달러', '엔', '유로')):
        return 'money'
    if any(x in u for x in ('명', '인', '가구', '세대', '사람')):
        return 'people'
    if any(x in u for x in ('시간', '일', '개월', '년', '세')):
        return 'time'
    if any(x in u for x in ('개', '대', '건', '톤')):
        return 'count'
    return 'other'


def item_compatible(item_name, item_unit, row):
    """선택된 ITEM도 뉴스 단위와 지표 의미를 다시 확인한다."""
    claim_unit = row.get('unit', '')
    ck, ik = unit_kind(claim_unit), unit_kind(item_unit)
    if ck != 'unknown' and ik != 'unknown' and ck != ik:
        return False, f'뉴스 단위({claim_unit})와 KOSIS 항목 단위({item_unit})가 다름'
    text = compact(' '.join(str(row.get(k, '')) for k in ('indicator', 'metric_domain', 'claim_text')))
    name = compact(item_name)
    rate_claim = '%' in compact(claim_unit) or any(k in text for k in ('증감률', '증가율', '비율', '퍼센트'))
    rate_item = any(k in name for k in ('비율', '증감률', '증가율', '등락률', '구성비')) or '%' in compact(item_unit)
    if rate_claim and not rate_item:
        return False, f'비율 claim에 비율이 아닌 KOSIS 항목({item_name})이 선택됨'
    if '수출' in text and '수출' not in name and '무역' not in name:
        return False, f'수출 claim에 다른 KOSIS 항목({item_name})이 선택됨'
    if '수입' in text and '수입' not in name and '무역' not in name:
        return False, f'수입 claim에 다른 KOSIS 항목({item_name})이 선택됨'
    return True, ''


def choose_item(meta_rows, row):
    selected_itm_id = str(row.get('selected_itm_id', '')).strip()
    if selected_itm_id:
        for m in meta_rows:
            if m.get('OBJ_ID') == 'ITEM' and m.get('ITM_ID') == selected_itm_id:
                ok, _ = item_compatible(m.get('ITM_NM', ''), m.get('UNIT_NM', ''), row)
                if not ok:
                    break
                return m, f"item={m.get('ITM_NM','')}[{m.get('ITM_ID','')}] from selected_itm_id"
        # 기존 선택 코드가 단위/의미 검사를 통과하지 못하면 폐기한다.
        selected_name = row.get('selected_itm_name', '')
        selected_unit = row.get('selected_itm_unit', '')
        ok, reason = item_compatible(selected_name, selected_unit, row)
        if ok:
            return {'ITM_ID': selected_itm_id, 'ITM_NM': selected_name, 'UNIT_NM': selected_unit}, 'item from selected_itm_id column'

    items = [m for m in meta_rows if m.get('OBJ_ID') == 'ITEM']
    if not items:
        return None, 'ITEM 메타 없음'
    text = ' '.join(str(row.get(k, '')) for k in ['indicator', 'metric_domain', 'industry_or_item', 'claim_text'])
    preferred = []
    if any(k in text for k in ['수출', 'export', 'Export']):
        preferred += ['수출액', '수출']
    if any(k in text for k in ['수입', 'import', 'Import']):
        preferred += ['수입액', '수입']
    if any(k in text for k in ['증가율', '상승률', '비율', '%', '퍼센트']):
        preferred += ['증감률', '증가율', '등락률', '비율']
    if any(k in text for k in ['취업자', '인원', '명']):
        preferred += ['계', '전체']

    scored = []
    for m in items:
        nm = m.get('ITM_NM', '')
        if not item_compatible(nm, m.get('UNIT_NM', ''), row)[0]:
            continue
        score = score_name(nm, text)
        for p in preferred:
            if compact(p) in compact(nm):
                score += 30
        # 특별 힌트가 없으면 첫 항목을 기본 후보로 둘 수 있게 낮은 점수 부여
        scored.append((score, m))
    if not scored:
        return None, '단위/지표 의미가 맞는 ITEM 후보 없음'
    scored.sort(key=lambda x: (-x[0], x[1].get('ITM_NM', '')))
    best = scored[0][1]
    return best, f"item={best.get('ITM_NM','')}[{best.get('ITM_ID','')}]"


def obj_candidates(meta_rows, row, first_obj):
    """첫 obj 조회가 비어 있을 때 재시도할 분류축 후보를 만든다."""
    seen = {first_obj}
    out = [first_obj]
    text = ' '.join(str(row.get(k, '')) for k in ('indicator', 'metric_domain', 'industry_or_item', 'claim_text'))
    scored = []
    for m in meta_rows:
        if m.get('OBJ_ID') == 'ITEM':
            continue
        code = m.get('ITM_ID', '')
        if not code or code in seen:
            continue
        score = score_name(m.get('ITM_NM', ''), text)
        if compact(m.get('ITM_NM', '')) in {'계', '전체', '총액', '전국'}:
            score += 5
        scored.append((score, code))
    for _, code in sorted(scored, reverse=True)[:10]:
        if code not in seen:
            seen.add(code); out.append(code)
    return out


def parse_meta_candidate_codes(summary):
    # 예: 품목별:반도체[13102112831A.77637]/item=N/score=60
    out = []
    for part in str(summary or '').split('|'):
        m = re.search(r'([^:|]+):([^\[]+)\[([^\]]+)\]/item=([YN])', part)
        if not m:
            continue
        out.append({
            'axis_name': m.group(1).strip(),
            'code_name': m.group(2).strip(),
            'code_id': m.group(3).strip(),
            'is_item': m.group(4).strip(),
        })
    return out


def choose_obj_l1(meta_rows, row):
    selected_obj = str(row.get('selected_obj_l1', '')).strip()
    selected_name = str(row.get('selected_obj_l1_name', '')).strip()
    selected_axis = str(row.get('selected_obj_l1_axis_id', '')).strip()
    if selected_obj:
        return selected_obj, f"objL1={selected_name}[{selected_obj}] axis={selected_axis} from selected_obj_l1"

    text = ' '.join(str(row.get(k, '')) for k in ['indicator', 'metric_domain', 'industry_or_item', 'claim_text'])
    indicator_text = compact(row.get('indicator', ''))
    focused_text = indicator_text or compact(row.get('industry_or_item', '')) or compact(text)
    ctext = compact(text)

    # 구버전 결과 파일 호환: meta_candidates가 있으면 쓰되, broad claim에서 너무 좁은 코드는 피한다.
    for c in parse_meta_candidate_codes(row.get('meta_candidates', '')):
        if c['is_item'] != 'N' or not c['code_id']:
            continue
        cname = compact(c['code_name'])
        too_narrow = False
        for broad, cfg in BROAD_OBJ_HINTS.items():
            if broad in focused_text and any(compact(a) in cname for a in cfg['avoid']):
                too_narrow = True
                break
        if not too_narrow:
            return c['code_id'], f"objL1={c['code_name']}[{c['code_id']}] from meta_candidates"

    classes = [m for m in meta_rows if m.get('OBJ_ID') != 'ITEM']
    if not classes:
        return 'ALL', '분류축 없음: ALL 시도'

    scored = []
    for m in classes:
        nm = m.get('ITM_NM', '')
        code = m.get('ITM_ID', '')
        cnm = compact(nm)
        score = score_name(nm, text)
        if compact(nm) in {'계', '전체', '총액', '전국'}:
            score += 5
        for broad, cfg in BROAD_OBJ_HINTS.items():
            if broad in focused_text:
                if any(code.startswith(prefix) for prefix in cfg.get('strong_code_prefix', [])):
                    score += 120
                if any(compact(p) in cnm for p in cfg['prefer']):
                    score += 60
                if any(compact(a) in cnm for a in cfg['avoid']):
                    score -= 100
        scored.append((score, m))
    scored.sort(key=lambda x: (-x[0], x[1].get('ITM_NM', '')))
    best = scored[0][1]
    return best.get('ITM_ID') or 'ALL', f"objL1={best.get('ITM_NM','')}[{best.get('ITM_ID','')}]"


def unit_factor(kosis_unit, claim_unit):
    ku = compact(kosis_unit)
    cu = compact(claim_unit)
    if not cu or cu == '-':
        return 1.0, 'claim 단위 없음: KOSIS 단위 그대로 비교'
    if ku == cu:
        return 1.0, '단위 동일'
    # KOSIS 천달러 -> claim 억달러: 1억달러 = 100,000천달러
    if '천달러' in ku and '억달러' in cu:
        return 1 / 100000, '천달러→억달러 환산'
    if '달러' in ku and '억달러' in cu and '천' not in ku:
        return 1 / 100000000, '달러→억달러 환산'
    if ('명' in ku or '사람' in ku) and '만명' in cu:
        return 1 / 10000, '명→만명 환산'
    if '천명' in ku and '만명' in cu:
        return 0.1, '천명→만명 환산'
    if '백만원' in ku and '억원' in cu:
        return 1 / 100, '백만원→억원 환산'
    if '억원' in ku and '조원' in cu:
        return 1 / 10000, '억원→조원 환산'
    if '%' in ku and ('%' in cu or '퍼센트' in cu):
        return 1.0, '퍼센트 단위 동일 취급'
    return 1.0, f'단위 환산 미정: KOSIS={kosis_unit}, claim={claim_unit}'




def is_unit_compatible(kosis_unit, claim_unit, item_name=''):
    """서로 다른 성격의 값을 비교하지 않도록 방어한다."""
    ku = compact(kosis_unit)
    cu = compact(claim_unit)
    item = compact(item_name)
    if not cu or cu == '-':
        return False, 'claim 단위 없음'
    if '%' in cu or '퍼센트' in cu:
        if '%' in ku or '비율' in item or '증감률' in item or '증가율' in item or '등락률' in item:
            return True, ''
        return False, f'claim은 비율인데 KOSIS 항목은 금액/수량 계열: KOSIS단위={kosis_unit}, 항목={item_name}'
    money_claim = any(x in cu for x in ['원', '달러'])
    money_kosis = any(x in ku for x in ['원', '달러'])
    people_claim = any(x in cu for x in ['명', '사람'])
    people_kosis = any(x in ku for x in ['명', '사람'])
    if money_claim and not money_kosis:
        return False, f'claim은 금액인데 KOSIS 단위가 금액이 아님: {kosis_unit}'
    if people_claim and not people_kosis:
        return False, f'claim은 인원인데 KOSIS 단위가 인원이 아님: {kosis_unit}'
    return True, ''


def needs_manual_code_review(row, obj_reason):
    """표는 맞아도 세부 품목/산업 코드가 좁게 잡히면 불일치 확정 대신 보류한다."""
    text = compact(' '.join(str(row.get(k, '')) for k in ['indicator', 'industry_or_item', 'claim_text']))
    reason = compact(obj_reason)
    broad_to_narrow = {
        '반도체': ['감광성', '다이오드', '트랜지스터', '부분품', '액정', '웨이퍼', '장비', '기계', '기구'],
        '자동차': ['승용자동차및기타의차량', '타이어', '부분품', '부품'],
        '화장품': ['탈모제', '향수'],
    }
    for broad, narrow_terms in broad_to_narrow.items():
        if broad in text and any(n in reason for n in narrow_terms):
            return True, f'{broad} claim인데 세부 품목 코드({obj_reason})가 좁게 잡혀 수동 확인 필요'
    return False, ''

def clean_data_rows(data):
    rows = []
    for r in data:
        if r.get('err'):
            continue
        val = parse_number(r.get('DT'))
        if val is None:
            continue
        rows.append(r)
    return rows


def aggregate_actual(data_rows, prd_se, period):
    if not data_rows:
        return None, '', ''
    p = parse_period(period)
    # 연도 claim인데 월/분기 자료면 합산한다. 수출액 같은 flow 통계 대응.
    if len(p) == 4 and prd_se in {'M', 'Q'}:
        vals = [parse_number(r.get('DT')) for r in data_rows if str(r.get('PRD_DE', '')).startswith(p)]
        vals = [v for v in vals if v is not None]
        if vals:
            return sum(vals), '+'.join(r.get('PRD_DE', '') for r in data_rows if str(r.get('PRD_DE', '')).startswith(p)), '월/분기 자료 합산'
    # 그 외에는 요청 기간과 가장 가까운/마지막 값을 쓴다.
    sorted_rows = sorted(data_rows, key=lambda r: str(r.get('PRD_DE', '')))
    r = sorted_rows[-1]
    return parse_number(r.get('DT')), r.get('PRD_DE', ''), '단일/최신 값 사용'


def judge(claim_value, actual_value, tolerance_abs, tolerance_pct):
    if claim_value is None:
        return '판단불가', 'claim value 없음'
    if actual_value is None:
        return '판단불가', 'KOSIS actual value 없음'
    diff = actual_value - claim_value
    abs_diff = abs(diff)
    pct = abs_diff / max(abs(claim_value), 1e-9) * 100
    if abs_diff <= tolerance_abs or pct <= tolerance_pct:
        return '일치', f'차이={abs_diff:.6g}, 차이율={pct:.3g}%'
    return '불일치', f'차이={abs_diff:.6g}, 차이율={pct:.3g}%'


def verify_row(row, meta_cache, delay):
    out = dict(row)
    claim_value = parse_number(row.get('value'))
    out['claim_value_numeric'] = claim_value if claim_value is not None else ''

    if str(row.get('candidate_rank', '')).strip() != '1':
        out.update({'verdict': '판단불가', 'verdict_reason': 'candidate_rank=1이 아님'})
        return out
    if claim_value is None:
        out.update({'verdict': '판단불가', 'verdict_reason': 'claim value가 비어 있음'})
        return out
    org_id = row.get('org_id', '')
    tbl_id = row.get('tbl_id', '')
    if not org_id or not tbl_id:
        out.update({'verdict': '판단불가', 'verdict_reason': 'org_id/tbl_id 없음'})
        return out

    key = (org_id, tbl_id)
    if key not in meta_cache:
        meta_cache[key] = get_meta(org_id, tbl_id, 'ITM')
        time.sleep(delay)
    meta_rows = meta_cache[key]

    item, item_reason = choose_item(meta_rows, row)
    if not item:
        out.update({'verdict': '판단불가', 'verdict_reason': item_reason})
        return out
    obj_l1, obj_reason = choose_obj_l1(meta_rows, row)
    prd_se = normalize_prd_se(row.get('prd_se'), row.get('period'))
    prd_params, period_note = period_range(row.get('period'), prd_se)

    try:
        data = []
        used_obj = obj_l1
        # 첫 obj_l1에 값이 없으면 같은 ITEM으로 다른 분류 코드를 재시도한다.
        for try_obj in obj_candidates(meta_rows, row, obj_l1):
            data = get_stat_data(
                org_id=org_id,
                tbl_id=tbl_id,
                obj_l1=try_obj,
                itm_id=item.get('ITM_ID', ''),
                prd_se=prd_se,
                new_est_prd_cnt=12 if prd_se == 'M' else 4,
                **prd_params,
            )
            time.sleep(delay)
            if clean_data_rows(data):
                used_obj = try_obj
                if try_obj != obj_l1:
                    obj_reason += f' / 첫 obj 데이터 없음, 대체 obj={try_obj} 재시도'
                break
            used_obj = try_obj
        obj_l1 = used_obj
    except Exception as exc:
        out.update({
            'kosis_obj_l1': obj_l1,
            'kosis_itm_id': item.get('ITM_ID', ''),
            'kosis_itm_name': item.get('ITM_NM', ''),
            'kosis_prd_se': prd_se,
            'verdict': '판단불가',
            'verdict_reason': f'KOSIS data API 오류: {exc}',
        })
        return out

    data_rows = clean_data_rows(data)
    actual_raw, actual_period, agg_reason = aggregate_actual(data_rows, prd_se, row.get('period'))
    kosis_unit_value = (item.get('UNIT_NM') or (data_rows[0].get('UNIT_NM') if data_rows else ''))
    factor, unit_reason = unit_factor(kosis_unit_value, row.get('unit'))
    compatible, compatible_reason = is_unit_compatible(kosis_unit_value, row.get('unit'), item.get('ITM_NM', ''))
    manual_review, manual_review_reason = needs_manual_code_review(row, obj_reason)
    actual_converted = actual_raw * factor if actual_raw is not None else None

    if not compatible:
        verdict, reason = '판단불가', compatible_reason
    elif manual_review:
        verdict, reason = '판단불가', manual_review_reason
    else:
        verdict, reason = judge(claim_value, actual_converted, tolerance_abs=0.5, tolerance_pct=1.0)

    reason_parts = [reason, item_reason, obj_reason, agg_reason, unit_reason]
    if period_note:
        reason_parts.append(period_note)
    if not data_rows:
        reason_parts.append('조회 데이터 없음')

    out.update({
        'kosis_obj_l1': obj_l1,
        'kosis_obj_l1_name': row.get('selected_obj_l1_name', ''),
        'kosis_itm_id': item.get('ITM_ID', ''),
        'kosis_itm_name': item.get('ITM_NM', ''),
        'kosis_unit': kosis_unit_value,
        'kosis_prd_se': prd_se,
        'kosis_period_used': actual_period,
        'kosis_actual_raw': actual_raw if actual_raw is not None else '',
        'kosis_actual_value': actual_converted if actual_converted is not None else '',
        'kosis_rows_used': len(data_rows),
        'value_diff': (actual_converted - claim_value) if actual_converted is not None and claim_value is not None else '',
        'verdict': verdict,
        'verdict_reason': ' / '.join(p for p in reason_parts if p),
    })
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True, help='*_kosis_index_candidates_with_meta.csv')
    parser.add_argument('--output', default='')
    parser.add_argument('--limit', type=int, default=0, help='테스트용 처리 행 수. 0이면 전체')
    parser.add_argument('--skip-empty-value', action='store_true', help='value가 비어 있는 행은 테스트/검증에서 제외')
    parser.add_argument('--rank', default='1', help='검증할 candidate_rank. 기본 1')
    parser.add_argument('--delay', type=float, default=0.12)
    args = parser.parse_args()

    inp = Path(args.input).expanduser()
    outp = Path(args.output).expanduser() if args.output else inp.with_name(inp.stem.replace('_kosis_index_candidates_with_meta', '') + '_kosis_verified.csv')
    rows, fields = read_csv(inp)
    rows = [r for r in rows if str(r.get('candidate_rank', '')).strip() == str(args.rank)]
    if args.skip_empty_value:
        rows = [r for r in rows if parse_number(r.get('value')) is not None]
    if args.limit:
        rows = rows[:args.limit]

    # 입력 후보 파일에 동일 measurement가 반복될 수 있다.
    # 검증 결과는 measurement당 1행만 남겨 중복 카운트를 막는다.
    deduped = []
    seen = set()
    for r in rows:
        measurement_id = str(r.get('claim_measurement_id', '')).strip()
        key = measurement_id if measurement_id and measurement_id != '-' else (r.get('claim_id'), r.get('value'), r.get('unit'))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    rows = deduped

    meta_cache = {}
    out_rows = []
    for i, row in enumerate(rows, 1):
        try:
            verified = verify_row(row, meta_cache, args.delay)
        except Exception as exc:
            verified = dict(row)
            verified.update({'verdict': '판단불가', 'verdict_reason': f'검증기 내부 오류: {exc}'})
        out_rows.append(verified)
        print(f"{i}/{len(rows)} {verified.get('claim_id','')} {verified.get('tbl_id','')} -> {verified.get('verdict','')}: {verified.get('verdict_reason','')[:120]}", flush=True)

    extra_fields = [
        'claim_value_numeric', 'kosis_obj_l1', 'kosis_obj_l1_name', 'kosis_itm_id', 'kosis_itm_name',
        'kosis_unit', 'kosis_prd_se', 'kosis_period_used', 'kosis_actual_raw',
        'kosis_actual_value', 'kosis_rows_used', 'value_diff', 'verdict', 'verdict_reason',
    ]
    final_fields = list(dict.fromkeys(fields + extra_fields))
    write_csv(outp, out_rows, final_fields)

    counts = defaultdict(int)
    for r in out_rows:
        counts[r.get('verdict', '')] += 1
    print(f'saved={outp}')
    print('verdict_counts=' + ', '.join(f'{k}:{v}' for k, v in sorted(counts.items())))


if __name__ == '__main__':
    main()
