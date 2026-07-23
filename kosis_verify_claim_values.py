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


def period_range(period, prd_se, comparison_period=""):
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


def item_compatible(item_name, item_unit, row):
    """선택된 ITEM도 뉴스 단위와 지표 의미를 다시 확인한다."""
    claim_unit = row.get('unit', '')
    ck = row.get('unit_dimension') or unit_kind(claim_unit)
    ik = unit_kind(item_unit)
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
        if ik not in {'currency', 'person_count', 'count', 'quantity'}:
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


def aggregate_period(data_rows, prd_se, target_period, method):
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
    current, current_period = aggregate_period(data_rows, prd_se, target, method)
    mapping_type = row.get('mapping_type') or 'direct'
    if mapping_type == 'direct':
        return current, current_period, '', f'aggregation={method}'

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


DECREASE_WORDS = ('감소', '하락', '줄', '축소', '마이너스', '위축', '둔화', '뒷걸음', '하향')
INCREASE_WORDS = ('증가', '상승', '늘', '확대', '급증', '플러스', '오른', '올라', '상향')


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
    # direction 없음: 값 '바로 뒤'에 방향어가 붙을 때만 부호 적용 (예: '1.6% 감소').
    # '1.4%로 계속 감소 중'처럼 떨어져 있으면 추세 서술이므로 건드리지 않는다.
    text = str(row.get('claim_text') or '')
    key = str(row.get('measurement_text') or '').strip() or str(row.get('value') or '').strip()
    idx = text.find(key) if key and key != '-' else -1
    if idx < 0:
        return magnitude
    after = text[idx + len(key): idx + len(key) + 6]  # 값 바로 뒤 6자
    if any(w in after for w in DECREASE_WORDS):
        return -abs(magnitude)
    if any(w in after for w in INCREASE_WORDS):
        return abs(magnitude)
    return magnitude


def judge(claim_value, actual_value, tolerance_abs, tolerance_pct, review_pct=5.0,
          pending_abs=None, pending_pct=None):
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
    if ((pending_abs is not None and abs_diff <= pending_abs)
            or (pending_pct is not None and pct <= pending_pct)):
        return '판정보류', f'오차범위 검토 필요: 차이={abs_diff:.6g}, 차이율={pct:.3g}%'
    if pct <= review_pct:
        return '판정보류', f'차이={abs_diff:.6g}, 차이율={pct:.3g}% (오차밴드 {tolerance_pct}~{review_pct}%, 문맥 검토 필요)'
    return '불일치', f'차이={abs_diff:.6g}, 차이율={pct:.3g}%'


def annual_context_month_period_mismatch(row):
    period = parse_period(row.get('period'))
    if len(period) != 6:
        return False, ''
    text = str(row.get('claim_text') or '')
    year = period[:4]
    has_annual_context = year in text and any(token in text for token in ('연간', '한 해', '가운데', '동안', '전체'))
    explicit_month = bool(re.search(rf'{year}\s*년\s*(0?[1-9]|1[0-2])\s*월', text))
    if has_annual_context and not explicit_month:
        return True, f'연간 문맥인데 measurement_period={period}가 월 단위로 추출되어 수동 확인 필요'
    return False, ''


def verify_row(row, meta_cache, delay):
    out = dict(row)
    out['default_applied'] = 'N'
    out['default_reason'] = ''
    claim_value = parse_number(row.get('value'))
    compare_value = signed_claim_value(row, claim_value)
    out['claim_value_numeric'] = claim_value if claim_value is not None else ''

    if row.get('mapping_status'):
        if row.get('mapping_status') != 'READY':
            return mark_unverifiable(
                out,
                row.get('mapping_status') or 'MAPPING_NOT_READY',
                'mapping',
                row.get('mapping_reason') or '확정 매핑이 아님',
            )
    else:
        if str(row.get('candidate_rank', '')).strip() != '1':
            return mark_unverifiable(out, 'NOT_TOP_CANDIDATE', 'candidate', 'candidate_rank=1이 아님')
        if row.get('candidate_status') != 'READY':
            code = row.get('candidate_status_code') or 'CANDIDATE_NOT_READY'
            reason = row.get('candidate_status_reason') or '후보가 READY 상태가 아님'
            return mark_unverifiable(out, code, 'candidate', reason)
    if claim_value is None:
        return mark_unverifiable(out, 'VALUE_MISSING', 'input', 'claim value가 비어 있음')
    if not parse_period(row.get('period')):
        return mark_unverifiable(out, 'PERIOD_MISSING', 'input', 'measurement period가 없음')
    period_mismatch, period_mismatch_reason = annual_context_month_period_mismatch(row)
    if period_mismatch:
        return mark_unverifiable(out, 'PERIOD_GRANULARITY_REVIEW', 'input', period_mismatch_reason)
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
    extra_obj = {
        f'obj_l{level}': str(row.get(f'selected_obj_l{level}', '')).strip()
        for level in range(2, 9)
        if str(row.get(f'selected_obj_l{level}', '')).strip()
    }
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
    if mapping_type in {'rate_from_level', 'difference_from_level'} and not parse_period(comparison):
        return mark_unverifiable(out, 'COMPARISON_PERIOD_MISSING', 'input', '증감 계산 비교 시점 없음')
    prd_params, period_note = period_range(row.get('period'), prd_se, comparison)

    try:
        data = get_stat_data(
            org_id=org_id,
            tbl_id=tbl_id,
            obj_l1=obj_l1,
            itm_id=item.get('ITM_ID', ''),
            prd_se=prd_se,
            new_est_prd_cnt=60 if prd_se == 'M' and comparison else (12 if prd_se == 'M' else 8),
            **prd_params,
            **extra_obj,
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

    if not data:
        return mark_unverifiable(
            out,
            'EMPTY_RESPONSE',
            'api',
            'KOSIS 응답이 비어 있음',
            kosis_obj_l1=obj_l1,
            kosis_itm_id=item.get('ITM_ID', ''),
            kosis_itm_name=item.get('ITM_NM', ''),
            kosis_prd_se=prd_se,
        )

    expected_codes = {'ITM_ID': str(item.get('ITM_ID', '')), 'C1': obj_l1}
    expected_codes.update({
        f'C{level}': value
        for level in range(2, 9)
        if (value := extra_obj.get(f'obj_l{level}'))
    })
    exact_data = [
        record for record in data
        if all(str(record.get(key, '')) == str(value) for key, value in expected_codes.items())
    ]
    if data and not exact_data:
        return mark_unverifiable(
            out,
            'RESPONSE_CODE_MISMATCH',
            'api',
            'KOSIS 응답 ITM_ID/C1~C8이 확정 요청 코드와 일치하지 않음',
        )
    data = exact_data

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
        'kosis_previous_period_used': previous_period,
        'kosis_actual_raw': actual_raw if actual_raw is not None else '',
        'kosis_actual_value': actual_converted if actual_converted is not None else '',
        'kosis_rows_used': len(data_rows),
        'value_diff': (actual_converted - compare_value) if actual_converted is not None and compare_value is not None else '',
        'verdict': verdict,
        'verdict_code': verdict_code,
        'verdict_stage': verdict_stage,
        'verdict_reason': ' / '.join(p for p in reason_parts if p),
        'mapping_status': row.get('mapping_status', ''),
        'mapping_basis': row.get('mapping_basis') or 'upstream candidate validation',
    })
    for level in range(2, 9):
        out[f'kosis_obj_l{level}'] = row.get(f'selected_obj_l{level}', '')
        out[f'kosis_obj_l{level}_name'] = row.get(f'selected_obj_l{level}_name', '')
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
    if any(str(r.get('mapping_status', '')).strip() for r in rows):
        rows = [r for r in rows if r.get('mapping_status') == 'READY']
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
            verified = dict(row)
            verified.update({'verdict': '판단불가', 'verdict_reason': f'검증기 내부 오류: {exc}'})
        out_rows.append(verified)
        print(f"{i}/{len(rows)} {verified.get('claim_id','')} {verified.get('tbl_id','')} -> {verified.get('verdict','')}: {verified.get('verdict_reason','')[:120]}", flush=True)

    extra_fields = [
        'claim_value_numeric', 'kosis_obj_l1', 'kosis_obj_l1_name', 'kosis_itm_id', 'kosis_itm_name',
        'kosis_obj_l2', 'kosis_obj_l2_name', 'kosis_obj_l3', 'kosis_obj_l3_name',
        'kosis_obj_l4', 'kosis_obj_l4_name', 'kosis_obj_l5', 'kosis_obj_l5_name',
        'kosis_obj_l6', 'kosis_obj_l6_name', 'kosis_obj_l7', 'kosis_obj_l7_name',
        'kosis_obj_l8', 'kosis_obj_l8_name',
        'kosis_unit', 'kosis_prd_se', 'kosis_period_used', 'kosis_previous_period_used',
        'kosis_actual_raw', 'kosis_actual_value', 'kosis_rows_used', 'value_diff',
        'default_applied', 'default_reason', 'mapping_status', 'mapping_basis',
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
