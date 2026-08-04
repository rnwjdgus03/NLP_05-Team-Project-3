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

from prepare_kosis_mapping_input import canonicalize_unit, unit_dimension as infer_unit_dimension

PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from kosis_api_test import get_meta, get_stat_data  # noqa: E402

csv.field_size_limit(2 ** 31 - 1)

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


def mark_unverifiable(out, code, stage, reason, **extra):
    out.update(
        {
            'verdict': '판단불가',
            'verdict_code': code,
            'verdict_stage': stage,
            'verdict_reason': reason,
            **extra,
        }
    )
    return out


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
    m = re.search(r'[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?', s)
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


def infer_comparison_period(row):
    """Infer only explicit year-over-year comparisons from the claim text."""
    explicit = parse_period(row.get('comparison_period'))
    if explicit:
        return explicit, ''
    current = parse_period(row.get('period') or row.get('measurement_period'))
    if not current:
        return '', ''
    text = compact(row.get('claim_text'))
    year_over_year = any(token in text for token in (
        '전년동월대비', '전년동월보다', '전년대비', '전년보다',
        '지난해같은달대비', '지난해같은기간대비',
    ))
    if not year_over_year:
        return '', ''
    if len(current) == 6:
        return f'{int(current[:4]) - 1}{current[4:]}', '원문의 전년 비교 표현에서 비교 월 추론'
    if len(current) == 4:
        return str(int(current) - 1), '원문의 전년 비교 표현에서 비교 연도 추론'
    return '', ''


def claim_period_span(row):
    """'1~11월' 같은 누적 구간. prepare 가 넣어준다. 없으면 None.

    2026-08-04: 반도체 수출 1~11월 1274억달러를 2024년 **12개월** 1420억과 대조해
    '불일치' 가 났다. 차이 11.5% 가 정확히 12월 한 달이었다.
    월 자료를 그 구간만 합산하면 답할 수 있다.
    """
    start = str(row.get('period_span_start') or '').strip()
    end = str(row.get('period_span_end') or '').strip()
    if len(start) == 6 and len(end) == 6 and start <= end:
        return start, end
    return None


def period_range(period, prd_se, comparison_period="", span=None):
    if span:
        return {'startPrdDe': span[0], 'endPrdDe': span[1]}, (
            f'누적 구간 {span[0]}~{span[1]} 월 자료 조회')
    p = parse_period(period)
    if not p:
        return {}, '기간 없음'
    comparison = parse_period(comparison_period)
    if prd_se == 'M':
        if len(p) == 6:
            start = comparison or p
            return {'startPrdDe': start, 'endPrdDe': p}, ''
        if len(p) == 4:
            start_year = comparison[:4] if comparison else p
            return {'startPrdDe': start_year + '01', 'endPrdDe': p + '12'}, '연도 기준 월자료 조회'
    if prd_se == 'Q':
        if len(p) == 4:
            start_year = comparison[:4] if comparison else p
            return {'startPrdDe': start_year + '01', 'endPrdDe': p + '04'}, '연도 기준 분기자료 조회'
    year = p[:4]
    start_year = comparison[:4] if comparison else year
    return {'startPrdDe': start_year, 'endPrdDe': year}, ''


def score_name(name, hint_text):
    c_name = compact(name)
    score = 0
    for t in tokens(hint_text):
        ct = compact(t)
        if ct and ct in c_name:
            score += min(len(ct), 8)
    return score


def unit_kind(unit):
    return infer_unit_dimension(canonicalize_unit(unit))


def is_index_level_item(item_name, item_unit):
    raw_unit = str(item_unit or "").strip().lower()
    name = compact(item_name)
    return (
        bool(re.search(r"\d{4}\s*[=＝]\s*100(?:\.0+)?", raw_unit))
        or "지수" in name
        or "index" in str(item_name or "").lower()
    )


def item_compatible(item_name, item_unit, row):
    """선택된 ITEM도 뉴스 단위와 지표 의미를 다시 확인한다."""
    claim_unit = row.get('unit', '')
    ck = row.get('unit_dimension') or unit_kind(claim_unit)
    ik = unit_kind(item_unit)
    if is_index_level_item(item_name, item_unit):
        ik = 'index'
    text = compact(' '.join(str(row.get(k, '')) for k in ('indicator', 'metric_domain', 'claim_text')))
    name = compact(item_name)
    semantic = row.get('semantic_type', '')
    rate_claim = semantic in {'rate_change', 'rate_level'} or '%' in compact(claim_unit)
    rate_item = any(k in name for k in ('비율', '증감률', '증가율', '등락률', '구성비')) or '%' in compact(item_unit)
    if semantic == 'rate_change' and rate_item and not any(
        token in name for token in ('증감률', '증가율', '감소율', '등락률')
    ):
        return False, f'증감률 claim에 일반 비율 ITEM({item_name})이 선택됨'
    if semantic == 'rate_change' and not rate_item:
        if ik not in {'currency', 'person_count', 'count', 'quantity', 'index'}:
            return False, f'증감률을 계산할 수 없는 KOSIS ITEM({item_name}, {item_unit})'
    elif rate_claim and not rate_item:
        return False, f'비율 claim에 비율이 아닌 KOSIS 항목({item_name})이 선택됨'
    elif ck == 'unknown' or ik == 'unknown':
        return False, f'단위 차원을 확정할 수 없음: claim={claim_unit}, KOSIS={item_unit}'
    elif ck != ik:
        return False, f'뉴스 단위({claim_unit})와 KOSIS 항목 단위({item_unit})가 다름'
    if '수출' in text and '수출' not in name and '무역' not in name:
        return False, f'수출 claim에 다른 KOSIS 항목({item_name})이 선택됨'
    if '수입' in text and '수입' not in name and '무역' not in name:
        return False, f'수입 claim에 다른 KOSIS 항목({item_name})이 선택됨'
    indicator = compact(row.get('indicator', ''))
    if '정비사' in indicator and not any(token in name for token in ('정비사', '정비인력', '종사자', '인력')):
        return False, f'정비사 claim에 다른 KOSIS ITEM({item_name})이 선택됨'
    if any(token in indicator for token in ('여객', '이용객')) and not any(
        token in name for token in ('여객', '이용객', '승객')
    ):
        return False, f'여객 claim에 다른 KOSIS ITEM({item_name})이 선택됨'
    entity = row.get('entity_type', '')
    if entity == 'organization' and any(token in name for token in ('인력', '종사자', '근로자', '인원')):
        return False, f'기업 수 claim에 사람 수 ITEM({item_name})이 선택됨'
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


def unit_spec(unit):
    value = compact(canonicalize_unit(unit))
    dimension = infer_unit_dimension(value)
    if dimension == 'currency':
        if '달러' in value:
            family = 'USD'
        elif '엔' in value:
            family = 'JPY'
        elif '유로' in value:
            family = 'EUR'
        else:
            family = 'KRW'
        scales = [('조', 1e12), ('억', 1e8), ('백만', 1e6), ('천', 1e3)]
        scale = next((factor for token, factor in scales if token in value), 1.0)
        return dimension, family, scale
    if dimension == 'person_count':
        scales = [('백만', 1e6), ('만', 1e4), ('천', 1e3)]
        scale = next((factor for token, factor in scales if token in value), 1.0)
        return dimension, 'PERSON', scale
    if dimension == 'rate':
        return dimension, 'RATE', 1.0
    if dimension == 'count':
        return dimension, value or 'COUNT', 1.0
    if dimension == 'quantity':
        return dimension, value, 1.0
    return dimension, value, 1.0


def unit_factor(kosis_unit, claim_unit):
    kd, kf, ks = unit_spec(kosis_unit)
    cd, cf, cs = unit_spec(claim_unit)
    if kd == 'unknown' or cd == 'unknown':
        return None, f'단위 차원 미확정: KOSIS={kosis_unit}, claim={claim_unit}'
    if kd != cd or kf != cf:
        return None, f'단위 불일치: KOSIS={kosis_unit}({kd}/{kf}), claim={claim_unit}({cd}/{cf})'
    factor = ks / cs
    return factor, f'단위 환산계수={factor:g}: KOSIS={kosis_unit} → claim={claim_unit}'


def is_unit_compatible(kosis_unit, claim_unit, item_name=''):
    factor, reason = unit_factor(kosis_unit, claim_unit)
    if factor is not None:
        return True, ''
    # A rate-change claim may legitimately use a level ITEM and derive YoY.
    item = compact(item_name)
    if any(token in item for token in ('증감률', '증가율', '감소율', '등락률')):
        if unit_kind(claim_unit) == 'rate':
            return True, ''
    return False, reason


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


def aggregation_method(row):
    indicator = compact(row.get('indicator', ''))
    if any(token in indicator for token in ('수출액', '수입액', '교역액', '매출액', '생산액', '출하액')):
        return 'sum'
    return 'latest'


def aggregate_period(data_rows, prd_se, target_period, method, span=None):
    if span:
        # 구간 합산은 **반드시 sum** 이다. latest 를 쓰면 마지막 달 값만 나온다.
        matching = [r for r in data_rows
                    if span[0] <= str(r.get('PRD_DE', '')) <= span[1]]
        values = [parse_number(r.get('DT')) for r in matching]
        values = [v for v in values if v is not None]
        if not values:
            return None, ''
        return sum(values), f"{span[0]}~{span[1]}({len(values)}개월)"
    matching = [r for r in data_rows if str(r.get('PRD_DE', '')).startswith(target_period)]
    if not matching:
        return None, ''
    matching.sort(key=lambda row: str(row.get('PRD_DE', '')))
    if len(target_period) == 4 and prd_se in {'M', 'Q'} and method == 'sum':
        values = [parse_number(row.get('DT')) for row in matching]
        values = [value for value in values if value is not None]
        if not values:
            return None, ''
        return sum(values), '+'.join(str(row.get('PRD_DE', '')) for row in matching)
    row = matching[-1]
    return parse_number(row.get('DT')), str(row.get('PRD_DE', ''))


def derive_actual(data_rows, prd_se, period, row):
    if not data_rows:
        return None, '', '', '조회 데이터 없음'
    target = parse_period(period)
    if not target:
        return None, '', '', '기간 없음'
    method = aggregation_method(row)
    span = claim_period_span(row)
    current, current_period = aggregate_period(data_rows, prd_se, target, method, span)
    mapping_type = row.get('mapping_type') or 'direct'
    if span and mapping_type != 'direct':
        # 누적 증감률은 비교 기간도 같은 폭으로 잡아야 한다. 아직 안 연다.
        return None, current_period, '', '누적 구간의 증감률은 지원하지 않는다'
    if mapping_type == 'direct':
        return current, current_period, '', f'aggregation=sum; 누적 {current_period}' if span else f'aggregation={method}'

    previous_target = parse_period(row.get('comparison_period'))
    if not previous_target:
        return None, current_period, '', 'comparison_period 없음'
    previous, previous_period = aggregate_period(data_rows, prd_se, previous_target, method)
    if current is None or previous is None:
        return None, current_period, previous_period, '현재/이전 기간 값 부족'
    if mapping_type == 'rate_from_level':
        if previous == 0:
            return None, current_period, previous_period, '이전 기간 값이 0'
        return (current - previous) / abs(previous) * 100, current_period, previous_period, f'수준값에서 증감률 계산; aggregation={method}'
    if mapping_type == 'difference_from_level':
        return current - previous, current_period, previous_period, f'수준값에서 증감량 계산; aggregation={method}'
    return None, current_period, previous_period, f'지원하지 않는 mapping_type={mapping_type}'


# 값 뒤에 붙어 '그 값 자체'가 아니라 '그 값을 기준으로 한 비교'임을 뜻하는 표현.
#
# 2026-08-02 실측: "성장률과 물가 상승률이 모두 2%를 밑돈 경우는 2020년이 마지막이었다"에서
# 2% 는 측정값이 아니라 한계값이다. 2020년 실제 물가상승률 0.54% 는 2% 미만이므로
# **주장은 참**인데, 검증기가 '주장 2 vs 실제 0.54 → 불일치'로 단언했다.
# 참인 기사에 거짓 딱지를 붙인 것이다.
#
# 한계값 비교를 제대로 구현하려면 방향(미만/초과)을 정확히 읽어야 하고,
# 틀리면 새로운 거짓 판정이 생긴다. 그래서 지금은 **판정하지 않는다** —
# 틀린 답을 내는 것보다 못 한다고 말하는 편이 낫다.
# 활용형에 주의한다. '밑돌다'는 '밑돈'으로 줄어 '밑돌'을 포함하지 않고,
# '넘어서다'는 '넘어섰다'가 되어 '넘어서'를 포함하지 않는다.
# 그래서 어간을 짧게 잡는다 — 테스트가 이 실수를 잡아줬다.
THRESHOLD_MARKERS = ('밑돌', '밑돈', '밑도', '웃돌', '웃돈', '웃도',
                     '미만', '이하', '이상', '초과', '넘어', '넘은', '넘는', '넘었',
                     '아래로', '위로', '선을 넘', '선을 웃')
_THRESHOLD_TAIL = 14

# 비교 기준 충돌. 문장은 전년 기준을 말하는데 change_base 가 전월로 잡힌 경우.
#
# 2026-08-02 실측 거짓 불일치:
#   "작년 12월 수출은 613억8000만달러로 1년 전 대비 6.6% 늘어 한 달 전(1.4%)에 비해
#    오름폭을 키웠다" — '한 달 전(1.4%)'은 11월의 **전년동월비**다.
#   추출이 '한 달 전'을 비교 기준으로 읽어 change_base=전월 로 넣었고,
#   검증기가 11월 vs 10월(-2.1%)을 계산해 '불일치'라고 단언했다.
#   실제 11월 전년동월비는 +1.4% 로 주장이 참이다.
#
# '한 달 전'은 시점 지시어이지 비교 기준이 아니다. 문장에 전년 기준이 명시돼 있고
# 전월 기준 표현이 없으면 어느 쪽인지 확정할 수 없다 → 판정하지 않는다.
YEAR_BASIS_PHRASES = ('1년 전', '일년 전', '전년 대비', '전년대비', '전년 동월', '전년동월',
                      '작년 같은', '전년 같은')
MONTH_BASIS_PHRASES = ('전월 대비', '전월대비', '전달 대비', '전달보다', '한 달 새',
                       '한달 새', '지난달 대비', '전월비')

DECREASE_WORDS = ('감소', '하락', '줄', '축소', '마이너스', '위축', '둔화', '뒷걸음', '하향')
INCREASE_WORDS = ('증가', '상승', '늘', '확대', '급증', '플러스', '오른', '올라', '상향')


def change_base_conflicts(row):
    """비교 기준이 문장과 어긋나는가. 어긋나면 그 근거를 돌려준다.

    '한 달 전'처럼 시점을 가리키는 말이 비교 기준으로 잘못 읽히면
    전월비를 계산하게 되고, 전년동월비 주장과 비교해 거짓 불일치가 난다.
    """
    base = str(row.get('change_base') or '').strip()
    if base not in {'전월', '전달'}:
        return ''
    text = str(row.get('claim_text') or '')
    if not text:
        return ''
    if any(phrase in text for phrase in MONTH_BASIS_PHRASES):
        return ''   # 전월 기준이 문장에 명시돼 있다
    hit = next((phrase for phrase in YEAR_BASIS_PHRASES if phrase in text), '')
    if hit:
        return f"문장은 '{hit}' 기준인데 change_base={base}"
    return ''


def threshold_expression(claim_text, claim_value):
    """주장 값이 '한계값'으로 쓰였으면 그 표현을 돌려준다. 아니면 빈 문자열.

    값 바로 뒤(약 14자)에 비교 표현이 붙는 경우만 본다.
    문장 어딘가에 '이상'이 있다는 이유로 막으면 정상 주장까지 잃는다.
    """
    text = str(claim_text or '')
    if not text or claim_value is None:
        return ''
    digits = f'{claim_value:g}'
    for match in re.finditer(re.escape(digits), text):
        tail = text[match.end():match.end() + _THRESHOLD_TAIL]
        for marker in THRESHOLD_MARKERS:
            if marker in tail:
                return text[match.start():match.end() + _THRESHOLD_TAIL].strip()
    return ''


def signed_claim_value(row, magnitude):
    """증감률·증감량 주장에 방향 부호를 붙인다. KOSIS actual은 부호가 있는데(감소=음수)
    추출된 value는 크기만 저장되는 경우가 많아, direction 또는 원문에서 감소/증가를 읽어 부호를 맞춘다.
    수준값(억달러·명 등)에는 적용하지 않는다."""
    if magnitude is None:
        return magnitude
    vt = str(row.get('value_type') or '').strip()
    role = str(row.get('measurement_role') or '').strip()
    if vt not in {'증감률', '증감량'} and role not in {'증감률', '증감값'}:
        return magnitude
    direction = str(row.get('direction') or '').strip()
    if any(w in direction for w in INCREASE_WORDS):
        return abs(magnitude)
    if any(w in direction for w in DECREASE_WORDS):
        return -abs(magnitude)
    text = str(row.get('claim_text') or '')
    key = str(row.get('measurement_text') or '').strip() or str(row.get('value') or '').strip()
    idx = text.find(key) if key and key != '-' else -1
    if idx < 0:
        return magnitude

    # 원문에 마이너스가 명시된 경우 (예: '9월(-0.4%)·10월(-0.2%)').
    # 추출은 크기만 저장해서 부호가 사라진다. 방향어보다 이 신호가 더 확실하므로 먼저 본다.
    # 실측: '작년 9월(-0.4%)…3개월 연속 전월 대비 감소' 에서 '감소'는 값에서 20자 넘게
    # 떨어져 있어 방향어 규칙이 닿지 않았고, 부호가 없는 +0.4 로 비교돼 차이가 부풀었다.
    if _explicit_minus_before(text, idx):
        return -abs(magnitude)

    # 값 '바로 뒤'에 방향어가 붙을 때만 부호 적용 (예: '1.6% 감소').
    # '1.4%로 계속 감소 중'처럼 떨어져 있으면 추세 서술이므로 건드리지 않는다.
    after = text[idx + len(key): idx + len(key) + 6]  # 값 바로 뒤 6자
    if any(w in after for w in DECREASE_WORDS):
        return -abs(magnitude)
    if any(w in after for w in INCREASE_WORDS):
        return abs(magnitude)
    return magnitude


# 값 바로 앞의 마이너스: '-0.4' / '△0.4' / '▲0.4'(하락 표기) 를 허용한다.
# 여는 괄호·공백은 건너뛰되, 다른 문자가 끼면 이 값의 부호가 아니라고 본다.
_MINUS_MARKS = ('-', '−', '－', '▲', '△', '↓')


def _explicit_minus_before(text: str, idx: int) -> bool:
    cursor = idx - 1
    while cursor >= 0 and text[cursor] in ' (（[':
        cursor -= 1
    return cursor >= 0 and text[cursor] in _MINUS_MARKS


def _compact_date(value):
    """'2026-02-25' / '20260225' → 'YYYYMMDD'. 8자리 미만이면 빈 문자열."""
    digits = re.sub(r'[^0-9]', '', str(value or ''))
    return digits[:8] if len(digits) >= 8 else ''


def latest_revision_date(data_rows, periods):
    """판정에 실제 사용된 시점(periods)의 KOSIS 행에서 가장 늦은 LST_CHN_DE(개정일)."""
    wanted = {str(p) for p in periods if p}
    dates = []
    for r in data_rows or []:
        if wanted and str(r.get('PRD_DE', '')) not in wanted:
            continue
        d = _compact_date(r.get('LST_CHN_DE'))
        if d:
            dates.append(d)
    return max(dates) if dates else ''


# 잠정치가 확정치로 바뀔 수 있는 기간. 이보다 오래된 관측은 이미 확정으로 보고
# 개정을 핑계로 쓰지 않는다. (무역통계 2~3개월, 산업활동동향 1~2개월, 국민계정 1~2년)
REVISION_WINDOW_MONTHS = 24
# 잠정→확정 개정은 통상 소폭이다. 이보다 큰 차이를 '개정 때문'이라 하면 판정 회피가 된다.
REVISION_MAX_RATE_POINT = 3.0     # 증감률: 절대 %p
REVISION_MAX_LEVEL_PCT = 10.0     # 수준값: 상대 %


def _period_end_month(period) -> str:
    """관측 시점의 마지막 달을 YYYYMM 으로. 연간이면 12월로 본다."""
    digits = re.sub(r'[^0-9]', '', str(period or ''))
    if len(digits) >= 6:
        return digits[:6]
    if len(digits) == 4:
        return digits + '12'
    return ''


def months_between(article_date: str, period) -> int | None:
    """관측 시점 종료 → 기사일까지 몇 개월인가. 판단 불가면 None."""
    end = _period_end_month(period)
    article = _compact_date(article_date)
    if not end or len(article) < 6:
        return None
    ay, am = int(article[:4]), int(article[4:6])
    py, pm = int(end[:4]), int(end[4:6])
    return (ay - py) * 12 + (am - pm)


def within_revision_window(article_date: str, actual_period,
                           months: int = REVISION_WINDOW_MONTHS) -> bool:
    """기사가 '아직 개정될 수 있는 시점'의 값을 다뤘는가.

    LST_CHN_DE 는 표 전체의 최종 수정일이라 월간 표는 갱신될 때마다 바뀐다.
    그래서 '개정일 > 기사일'만 보면 최근 기사는 거의 전부 보류가 된다.
    실제 개정 위험은 **관측 시점이 아직 잠정치 구간에 있을 때** 생긴다.
    """
    gap = months_between(article_date, actual_period)
    if gap is None:
        return True          # 판단 불가하면 기존처럼 보수적으로 통과시킨다
    return 0 <= gap <= months


def revision_explains_gap(claim_value, actual_value, rate_like: bool) -> bool:
    """차이 크기가 잠정→확정 개정으로 설명될 만한가.

    설명 못 할 크기까지 개정 탓으로 돌리면 보류가 판정 회피 수단이 된다.
    """
    if claim_value is None or actual_value is None:
        return True          # 크기를 모르면 기존 동작 유지
    gap = abs(actual_value - claim_value)
    if rate_like:
        return gap <= REVISION_MAX_RATE_POINT
    denominator = max(abs(claim_value), 1e-9)
    return gap / denominator * 100 <= REVISION_MAX_LEVEL_PCT


def revision_vintage_risk(row, data_rows, mapping_type, actual_period, previous_period,
                          *, claim_value=None, actual_value=None, rate_like=None):
    """불일치를 통계 개정(빈티지) 위험으로 보류할지. 전 조건 충족 시 (개정일, 기사일) 반환.

    조건(전부 필요 — 모든 불일치를 보류하지 않기 위한 명시 조건):
      1) 파생 증감률 판정 (rate_from_level 또는 value_type=증감률)
      2) 기사 작성일 파싱 가능
      3) 사용된 KOSIS 행의 LST_CHN_DE(개정일)가 기사일보다 '이후'
      4) 관측 시점이 기사 시점보다 과거 또는 동월
      5) [2026-07-31 추가] 관측 시점이 아직 **잠정치 구간**에 있다
         — 3)만으로는 최근 기사가 거의 전부 보류된다(실측 9건 중 5건).
      6) [2026-07-31 추가] 차이 크기가 **개정으로 설명될 만한 범위**다
         — 설명 못 할 차이까지 보류하면 판정 회피가 된다.
    """
    if mapping_type != 'rate_from_level' and str(row.get('value_type') or '').strip() != '증감률':
        return '', ''
    article = _compact_date(row.get('date'))
    if not article:
        return '', ''
    revised = latest_revision_date(data_rows, [actual_period, previous_period])
    if not revised or revised <= article:
        return '', ''
    target = str(actual_period or '')
    if len(target) >= 6 and target[:6] > article[:6]:
        return '', ''
    if not within_revision_window(article, actual_period):
        return '', ''
    if rate_like is None:
        rate_like = (mapping_type == 'rate_from_level'
                     or str(row.get('value_type') or '').strip() == '증감률')
    if not revision_explains_gap(claim_value, actual_value, rate_like):
        return '', ''
    return revised, article


# 수준값: 이 비율을 넘는 차이는 '기사가 틀렸다'보다 '좌표를 잘못 잡았다'로 보는 것이 타당하다.
# (무역흑자 518억달러를 수입액 6320억달러에 대면 1,120% 가 나온다)
MISMAPPING_PCT = 300.0
# 증감률: 분모가 작아 상대오차가 쉽게 폭발한다(8.2% vs 42.5% = 418%).
# 둘 다 있을 수 있는 증감률이므로 상대오차 대신 **절대 %p 차이**로 본다.
MISMAPPING_RATE_POINT = 100.0


def extreme_error(claim_value, actual_value, threshold=MISMAPPING_PCT, *,
                  rate_like: bool = False,
                  rate_threshold: float = MISMAPPING_RATE_POINT) -> bool:
    """차이가 '기사 오류'로 보기엔 비상식적인가. 그렇다면 매핑 오류를 먼저 의심한다.

    증감률과 수준값은 기준이 달라야 한다. 증감률 8.2% 와 42.5% 는 상대오차 418% 지만
    둘 다 실재할 수 있는 값이라 매핑 오류로 단정하면 안 된다.
    """
    if claim_value is None or actual_value is None:
        return False
    if rate_like:
        return abs(actual_value - claim_value) >= rate_threshold
    denominator = max(abs(claim_value), 1e-9)
    return abs(actual_value - claim_value) / denominator * 100 >= threshold


def judge(claim_value, actual_value, tolerance_abs, tolerance_pct, review_pct=5.0):
    """3구간 판정: 일치 / 판정보류(오차밴드) / 불일치.

    - 일치: 절대오차 tolerance_abs 이내 또는 상대오차 tolerance_pct% 이내
    - 판정보류: tolerance_pct% 초과 ~ review_pct% 이내 (근사·관점·세부항목 차이 가능 → 문맥 검토)
    - 불일치: review_pct% 초과 (명백히 벗어남)
    멘토 조언(오차밴드): 수치가 다르다고 바로 '틀림'이 아니라, 애매한 구간은 보류한다.
    """
    if claim_value is None:
        return '판단불가', 'claim value 없음'
    if actual_value is None:
        return '판단불가', 'KOSIS actual value 없음'
    diff = actual_value - claim_value
    abs_diff = abs(diff)
    pct = abs_diff / max(abs(claim_value), 1e-9) * 100
    # 팀 공식 기준(거의 정확일치, 엄격)에 맞춰 상대오차로 판정한다.
    # 절대오차 지름길(0.5%p)은 1.4% vs 1.31% 같은 큰 상대오차를 일치로 오판해 제거했다.
    # (골드 역산: 일치 <=1.23%, 불일치 >=5%. tolerance_pct/review_pct로 조정 가능.)
    if pct <= tolerance_pct:
        return '일치', f'차이={abs_diff:.6g}, 차이율={pct:.3g}%'
    if pct <= review_pct:
        return '판정보류', f'차이={abs_diff:.6g}, 차이율={pct:.3g}% (오차밴드 {tolerance_pct}~{review_pct}%, 문맥 검토 필요)'
    return '불일치', f'차이={abs_diff:.6g}, 차이율={pct:.3g}%'


def pin_item(meta_rows, row):
    """`selected_itm_id` 를 그대로 쓴다(후보 좌표를 있는 그대로 검증할 때).

    기본 경로인 `choose_item` 은 메타에서 ITEM 을 다시 고르기 때문에,
    'A 후보 좌표 vs C 후보 좌표' 처럼 **좌표를 고정해 비교**할 때는 쓸 수 없다.
    """
    wanted = str(row.get('selected_itm_id', '')).strip()
    if not wanted:
        return None, 'selected_itm_id 없음(고정 검증 불가)'
    for meta in meta_rows:
        if str(meta.get('ITM_ID', '')).strip() == wanted:
            return meta, f"ITEM 고정={meta.get('ITM_NM', '')}[{wanted}]"
    return None, f'selected_itm_id={wanted} 가 메타에 없음'


def verify_row(row, meta_cache, delay, use_pinned_item=False):
    """use_pinned_item=True 면 ITEM 을 다시 고르지 않고 selected_itm_id 를 그대로 쓴다."""
    out = dict(row)
    out['default_applied'] = 'N'
    out['default_reason'] = ''
    claim_value = parse_number(row.get('value'))
    compare_value = signed_claim_value(row, claim_value)
    out['claim_value_numeric'] = claim_value if claim_value is not None else ''

    # 확정 매핑이 아니면 판정하지 않는다. 단, --allow-unconfirmed 로 표시된 진단 행은
    # 조회까지 진행한다(결과는 판정이 아니라 진단이며 출력에 표시가 남는다).
    #
    # 2026-08-02: 게이트가 두 겹이었다. CLI 의 행 필터만 열었더니 여기서 다시 막혀
    # 24건이 전부 '판단불가'로 나왔다. validate 에서 고쳤던 이중 게이트와 같은 모양이다.
    diagnostic = str(row.get('verified_without_confirmation', '')).strip().upper() == 'Y'
    if row.get('mapping_status') and row.get('mapping_status') != 'READY' and not diagnostic:
        return mark_unverifiable(
            out,
            row.get('mapping_status'),
            'mapping',
            row.get('mapping_reason', '확정 매핑이 아님'),
        )
    if not row.get('mapping_status') and str(row.get('candidate_rank', '')).strip() != '1':
        return mark_unverifiable(out, 'NOT_TOP_CANDIDATE', 'candidate', 'candidate_rank=1이 아님')
    if not row.get('mapping_status') and row.get('candidate_status') != 'READY':
        code = row.get('candidate_status_code') or 'CANDIDATE_NOT_READY'
        reason = row.get('candidate_status_reason') or '후보가 READY 상태가 아님'
        return mark_unverifiable(out, code, 'candidate', reason)
    if claim_value is None:
        return mark_unverifiable(out, 'VALUE_MISSING', 'input', 'claim value가 비어 있음')
    threshold = threshold_expression(row.get('claim_text'), claim_value)
    if threshold:
        return mark_unverifiable(
            out, 'THRESHOLD_CLAIM_UNSUPPORTED', 'input',
            f"'{threshold}' — 한계값 서술이라 값 일치로 판정할 수 없음")
    conflict = change_base_conflicts(row)
    if conflict:
        return mark_unverifiable(
            out, 'CHANGE_BASE_AMBIGUOUS', 'input',
            f"{conflict} — 비교 기준을 확정할 수 없음")
    if not parse_period(row.get('period')):
        return mark_unverifiable(out, 'PERIOD_MISSING', 'input', 'measurement period가 없음')
    mapping_type = str(row.get('mapping_type', '')).strip()
    if mapping_type not in {'direct', 'rate_from_level', 'difference_from_level'}:
        return mark_unverifiable(
            out,
            'MAPPING_TYPE_UNSUPPORTED',
            'candidate',
            f'지원하지 않는 mapping_type={mapping_type or "-"}',
        )
    org_id = row.get('org_id', '')
    tbl_id = row.get('tbl_id', '')
    if not org_id or not tbl_id:
        return mark_unverifiable(out, 'TABLE_ID_MISSING', 'candidate', 'org_id/tbl_id 없음')

    key = (org_id, tbl_id)
    if key not in meta_cache:
        meta_cache[key] = get_meta(org_id, tbl_id, 'ITM')
        time.sleep(delay)
    meta_rows = meta_cache[key]

    if use_pinned_item:
        item, item_reason = pin_item(meta_rows, row)
        if not item:
            return mark_unverifiable(out, 'ITEM_NOT_IN_META', 'metadata', item_reason)
    else:
        item, item_reason = choose_item(meta_rows, row)
        if not item:
            return mark_unverifiable(out, 'NO_COMPATIBLE_ITEM', 'metadata', item_reason)
    has_obj_axis = any(meta.get('OBJ_ID') != 'ITEM' for meta in meta_rows)
    if has_obj_axis and not str(row.get('selected_obj_l1', '')).strip():
        return mark_unverifiable(out, 'OBJ_UNRESOLVED', 'metadata', 'selected_obj_l1이 확정되지 않음')
    obj_l1 = str(row.get('selected_obj_l1', '')).strip() or 'ALL'
    if obj_l1 == 'ALL' and not has_obj_axis:
        out['default_applied'] = 'Y'
        out['default_reason'] = '분류축 없음 → 전체(ALL) 조회 [위험도 낮음]'
    obj_reason = (
        f"objL1={row.get('selected_obj_l1_name','')}[{obj_l1}] "
        f"axis={row.get('selected_obj_l1_axis_id','')}"
    )
    prd_se = normalize_prd_se(row.get('prd_se'), row.get('period'))
    if not str(row.get('prd_se', '')).strip() and prd_se:
        note = f"prd_se 미지정 → period 형식에서 '{prd_se}' 추론 [위험도 중간]"
        out['default_applied'] = 'Y'
        out['default_reason'] = (out['default_reason'] + '; ' + note).strip('; ')
    comparison = row.get('comparison_period') if mapping_type in {'rate_from_level', 'difference_from_level'} else ''
    comparison_note = ''
    if mapping_type in {'rate_from_level', 'difference_from_level'} and not parse_period(comparison):
        comparison, comparison_note = infer_comparison_period(row)
        if comparison:
            row = {**row, 'comparison_period': comparison}
            out['comparison_period'] = comparison
            out['default_applied'] = 'Y'
            out['default_reason'] = (
                out['default_reason'] + '; ' + comparison_note + ' [위험도 낮음]'
            ).strip('; ')
    if mapping_type in {'rate_from_level', 'difference_from_level'} and not parse_period(comparison):
        return mark_unverifiable(out, 'COMPARISON_PERIOD_MISSING', 'input', '증감 계산 비교 시점 없음')
    prd_params, period_note = period_range(row.get('period'), prd_se, comparison,
                                          claim_period_span(row))

    try:
        data = get_stat_data(
            org_id=org_id,
            tbl_id=tbl_id,
            obj_l1=obj_l1,
            itm_id=item.get('ITM_ID', ''),
            prd_se=prd_se,
            new_est_prd_cnt=60 if prd_se == 'M' and comparison else (12 if prd_se == 'M' else 8),
            **prd_params,
        )
        time.sleep(delay)
    except Exception as exc:
        return mark_unverifiable(
            out,
            'KOSIS_API_ERROR',
            'api',
            f'KOSIS data API 오류: {exc}',
            kosis_obj_l1=obj_l1,
            kosis_itm_id=item.get('ITM_ID', ''),
            kosis_itm_name=item.get('ITM_NM', ''),
            kosis_prd_se=prd_se,
        )

    data_rows = clean_data_rows(data)
    actual_raw, actual_period, previous_period, agg_reason = derive_actual(
        data_rows, prd_se, row.get('period'), row
    )
    kosis_unit_value = (item.get('UNIT_NM') or (data_rows[0].get('UNIT_NM') if data_rows else ''))
    if mapping_type == 'rate_from_level':
        factor, unit_reason = 1.0, '수준값 증감률 계산에서는 단위 배율 상쇄'
        compatible, compatible_reason = actual_raw is not None, ''
    else:
        factor, unit_reason = unit_factor(kosis_unit_value, row.get('unit'))
        compatible = factor is not None
        compatible_reason = '' if compatible else unit_reason
    manual_review, manual_review_reason = needs_manual_code_review(row, obj_reason)
    actual_converted = actual_raw * factor if actual_raw is not None and factor is not None else None

    if actual_raw is None:
        verdict, reason = '판단불가', agg_reason
        verdict_code, verdict_stage = 'ACTUAL_DERIVATION_FAILED', 'data'
    elif not compatible:
        # 멘토 조언(단위→랭킹): 단위 불일치를 하드 리젝트하지 않고 후보로 남긴다.
        # 다만 단위 변환이 안 되면 값 비교가 불가하므로 거짓 일치/불일치는 내지 않고 '판정보류'로 남겨 검토받는다.
        verdict = '판정보류'
        reason = compatible_reason + ' (단위 비호환 → 후보 유지·확신 판정 보류, 사람 검토)'
        verdict_code, verdict_stage = 'UNIT_UNCERTAIN', 'unit'
    elif manual_review:
        verdict, reason = '판단불가', manual_review_reason
        verdict_code, verdict_stage = 'OBJ_CODE_REVIEW_REQUIRED', 'metadata'
    else:
        verdict, reason = judge(compare_value, actual_converted, tolerance_abs=0.5, tolerance_pct=1.5, review_pct=4.0)
        if compare_value != claim_value:
            reason += f' (방향부호 적용: claim={compare_value})'
        verdict_code = {'일치': 'MATCH', '불일치': 'VALUE_MISMATCH',
                        '판정보류': 'WITHIN_UNCERTAINTY_BAND'}.get(verdict, 'COMPARISON_FAILED')
        verdict_stage = 'comparison'
        # 오차가 지나치게 크면 기사 오류보다 우리 좌표 매핑 오류일 가능성이 높다.
        # 실측: '518억달러 무역흑자'가 수입액 총액에 매핑돼 차이율 1,120%로 '불일치'가 났다.
        # 팩트체크에서 맞는 기사를 틀렸다고 하는 것이 최악이므로 단정하지 않는다.
        rate_like = (unit_kind(row.get('unit')) == 'rate'
                     or mapping_type == 'rate_from_level')
        if verdict == '불일치' and extreme_error(
                compare_value, actual_converted, rate_like=rate_like):
            verdict = '판단불가'
            verdict_code = 'LIKELY_MISMAPPING'
            verdict_stage = 'mapping'
            reason += (f' (차이율이 {MISMAPPING_PCT:.0f}% 를 넘어 좌표 매핑 오류로 의심'
                       ' — 기사 오류로 단정하지 않고 사람 검토로 보낸다)')
        elif verdict == '불일치':
            revised, article_date = revision_vintage_risk(
                row, data_rows, mapping_type, actual_period, previous_period,
                claim_value=compare_value, actual_value=actual_converted,
                rate_like=rate_like)
            if revised:
                verdict = '판정보류'
                verdict_code = 'REVISION_VINTAGE_RISK'
                reason += (f' (KOSIS 개정일 {revised} > 기사일 {article_date}:'
                           f' 기사 당시 공표치가 이후 개정되었을 수 있어 보류)')
                out['kosis_lst_chn_de'] = revised

    reason_parts = [reason, item_reason, obj_reason, agg_reason, unit_reason]
    if period_note:
        reason_parts.append(period_note)
    if comparison_note:
        reason_parts.append(comparison_note)
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
        'kosis_previous_period_used': previous_period,
        'kosis_actual_raw': actual_raw if actual_raw is not None else '',
        'kosis_actual_value': actual_converted if actual_converted is not None else '',
        'kosis_rows_used': len(data_rows),
        'value_diff': (actual_converted - compare_value) if actual_converted is not None and compare_value is not None else '',
        'verdict': verdict,
        'verdict_code': verdict_code,
        'verdict_stage': verdict_stage,
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
    parser.add_argument(
        '--allow-unconfirmed', action='store_true',
        help='확정되지 않은 매핑(NEEDS_CONFIRMATION 등)도 조회한다. **진단 전용**이다. '
             '출력의 verified_without_confirmation=Y 로 표시되며, 이 결과를 '
             '판정으로 쓰면 안 된다 — 좌표가 확정되지 않았으므로 값이 맞아도 '
             '우연일 수 있고 틀려도 주장이 거짓이라는 뜻이 아니다.')
    args = parser.parse_args()

    inp = Path(args.input).expanduser()
    outp = Path(args.output).expanduser() if args.output else inp.with_name(inp.stem.replace('_kosis_index_candidates_with_meta', '') + '_kosis_verified.csv')
    rows, fields = read_csv(inp)
    if any(str(r.get('mapping_status', '')).strip() for r in rows):
        # 기본은 READY 만. 확정 안 된 매핑에 판정을 내면 파이프라인의 원칙이 깨진다.
        # 2026-08-02: '후보가 결정적이지 않음' 24건이 정말 틀린 좌표인지 재려면
        # 조회는 해봐야 해서 진단용 통로를 열되, 출력에 표시를 남긴다.
        if not args.allow_unconfirmed:
            rows = [r for r in rows if r.get('mapping_status') == 'READY']
        else:
            for row in rows:
                row['verified_without_confirmation'] = 'Y'
            if 'verified_without_confirmation' not in fields:
                fields.append('verified_without_confirmation')
            print('[진단 모드] 확정되지 않은 매핑을 조회한다. 결과를 판정으로 쓰지 말 것.')
    else:
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
            # verdict_code 를 비워두면 집계에서 빈 문자열 버킷이 생겨 원인 추적이 끊긴다.
            # 네트워크 계열은 재시도 후에도 실패한 것이므로 별도 코드로 구분한다.
            network = isinstance(exc, (ConnectionError, TimeoutError)) or any(
                token in type(exc).__name__ for token in ('Connection', 'Timeout', 'HTTP'))
            verified = dict(row)
            verified.update({
                'verdict': '판단불가',
                'verdict_code': 'KOSIS_API_ERROR' if network else 'VERIFIER_INTERNAL_ERROR',
                'verdict_stage': 'api' if network else 'verifier',
                'verdict_reason': f'검증기 내부 오류: {exc}',
            })
        out_rows.append(verified)
        print(f"{i}/{len(rows)} {verified.get('claim_id','')} {verified.get('tbl_id','')} -> {verified.get('verdict','')}: {verified.get('verdict_reason','')[:120]}", flush=True)

    extra_fields = [
        'claim_value_numeric', 'kosis_obj_l1', 'kosis_obj_l1_name', 'kosis_itm_id', 'kosis_itm_name',
        'kosis_unit', 'kosis_prd_se', 'kosis_period_used', 'kosis_previous_period_used',
        'kosis_actual_raw', 'kosis_actual_value', 'kosis_rows_used', 'value_diff',
        'default_applied', 'default_reason', 'kosis_lst_chn_de',
        'verdict', 'verdict_code', 'verdict_stage', 'verdict_reason',
    ]
    final_fields = list(dict.fromkeys(fields + extra_fields))
    write_csv(outp, out_rows, final_fields)

    counts = defaultdict(int)
    for r in out_rows:
        counts[r.get('verdict', '')] += 1
    reason_counts = defaultdict(int)
    for r in out_rows:
        reason_counts[r.get('verdict_code', '')] += 1
    print(f'saved={outp}')
    print('verdict_counts=' + ', '.join(f'{k}:{v}' for k, v in sorted(counts.items())))
    print('verdict_code_counts=' + ', '.join(f'{k}:{v}' for k, v in sorted(reason_counts.items())))


if __name__ == '__main__':
    main()
