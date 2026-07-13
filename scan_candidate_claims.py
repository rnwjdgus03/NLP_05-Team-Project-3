# -*- coding: utf-8 -*-
"""
A팀의 claim_candidates.csv가 오기 전, 원본 기사 코퍼스(chosun_full.csv)에서
'수치 기반 주장'일 가능성이 높은 기사를 미리 스캔해 후보를 뽑아두는 스크립트.

방식: 기사 본문에서
  1) 숫자+단위 패턴 (%, 퍼센트, 명, 가구, 원, 억원, 조원, 배, 위, 세, 년, kg, km 등)
  2) 통계 출처 키워드 (통계청, 국가데이터처, KOSIS, 통계에 따르면 등)
  3) 변화/비교 표현 (증가, 감소, 줄었다, 늘었다, 최고, 최저, 역대, 배 늘어 등)
가 함께 등장하는 정도로 점수를 매겨 상위 후보를 추린다.
완전한 claim 추출은 아니고, A팀 작업 전 매칭 파이프라인 예비 테스트/우선순위 참고용.
"""
import re
import pandas as pd

df = pd.read_csv('chosun_full.csv', encoding='utf-8-sig')
df = df[df['검색 구분 레이블'].astype(str).str.upper() == 'TRUE'].copy()
df['기사 본문 전체'] = df['기사 본문 전체'].fillna('')

NUM_UNIT = re.compile(r'\d[\d,\.]*\s*(%|퍼센트|명|가구|원|억원|조원|배|위|세|건|개|만|만명|만가구|kg|km|톤)')
SOURCE_KW = re.compile(r'(통계청|국가데이터처|KOSIS|코시스|통계에?\s?따르면|조사에?\s?따르면)')
TREND_KW = re.compile(r'(증가|감소|줄었|늘었|최고치|최저치|역대|급증|급감|하락|상승|줄어|늘어)')

def score_row(text):
    n_num = len(NUM_UNIT.findall(text))
    has_source = bool(SOURCE_KW.search(text))
    n_trend = len(TREND_KW.findall(text))
    score = n_num + (3 if has_source else 0) + n_trend
    return score, n_num, has_source, n_trend

scores = df['기사 본문 전체'].apply(score_row)
df['score'] = [s[0] for s in scores]
df['숫자단위_매칭수'] = [s[1] for s in scores]
df['통계출처_언급'] = [s[2] for s in scores]
df['변화표현_매칭수'] = [s[3] for s in scores]

result = df.sort_values('score', ascending=False)[
    ['기사제목', '작성일', 'URL', 'score', '숫자단위_매칭수', '통계출처_언급', '변화표현_매칭수']
]

result.to_csv('candidate_claim_articles.csv', index=False, encoding='utf-8-sig')

print(f"True 라벨 기사 {len(df)}건 중 스캔 완료")
print(f"score > 0 (숫자/단위 표현 최소 1개 이상): {(result['score']>0).sum()}건")
print(f"통계출처 명시 언급 기사: {result['통계출처_언급'].sum()}건")
print()
print("=== 상위 15건 ===")
print(result.head(15).to_string(index=False))
