#!/usr/bin/env python3
"""기사가 KOSIS 로 확인 가능한 주장을 담고 있을 가능성을 점수화한다 (2026-08-04).

## 왜 필요한가

출처 가린 라벨링 12건에서 **8건이 KOSIS 에 아예 대응 통계가 없었다.**
검색을 아무리 고쳐도 이건 안 된다. **대상 기사 선정이 가장 큰 제약이다.**

지금 풀의 점수(`숫자단위_매칭수`·`통계출처_언급`·`변화표현_매칭수`)는
**KOSIS 수록 여부를 전혀 모른다.** 숫자가 많아도 KOSIS 에 없는 주제면 소용없다.

## 무엇으로 점수를 매기는가

첫 50건 실측에서 갈린 지점 둘이다.

**① 지표가 국가 총계 거시지표인가**

    확정 있음   수출액 · 수출증가율 · 산업생산지수 · 소매판매 · 환율 · 완성차 판매량
    확정 0      조선 인력 중 외국인 비율 · 전시 분야 비중 · 로봇화 기업 수 ·
                중소기업 도입률 · 코스피 변동률 · 상장기업 할인율

설문 기반 실태조사의 '비율·도입률'과 금융시장 지수는 KOSIS 좌표로 확인이 안 된다.

**② 제목에 구체적 수치가 있는가**

    '정부 올해 경제성장률 1.8%'      확정 1
    '추락하는 성장률, 내수 살려'      확정 0

같은 지표어인데 갈렸다. 숫자가 없으면 기사가 통계를 **인용**하는 게 아니라
**논평**하는 것이다.

## 한계

**표본이 13개 기사다.** 규칙이 이 13개에 과적합됐을 수 있다.
그래서 고른 50건을 실제로 돌려서 확정률이 오르는지 확인해야 한다.
안 오르면 이 점수는 틀린 것이고, 그때는 기사 선정이 병목이 아니라는 뜻이다.
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

# KOSIS 가 국가 총계로 제공하는 거시지표. 확정이 나온 기사들의 지표에서 뽑았다.
MACRO = (
    "수출", "수입", "무역", "관세",
    "물가", "소비자물가", "생산자물가", "환율",
    "산업생산", "소매판매", "생산지수", "가동률", "재고",
    "취업자", "실업", "고용", "일자리", "임금",
    "인구", "출생", "사망", "혼인", "이혼", "가구",
    "주택", "집값", "전세", "매매가격", "분양", "착공",
    "성장률", "국내총생산", "GDP", "소비", "투자",
    "판매량", "등록대수", "여객", "화물",
)

# 확정이 하나도 안 나온 기사들의 지표 계열.
# 설문 실태조사의 비율·도입률과 금융시장 지수는 KOSIS 좌표로 표현이 안 된다.
WEAK = (
    "도입률", "도입 여부", "인식", "만족도", "애로사항", "실태조사",
    "코스피", "코스닥", "증시", "주가", "지수 변동", "시가총액",
    "공모주", "상장", "할인율", "밸류업",
    "전시", "박람회", "행사", "수상", "선정",
    "간담회", "협약", "출시", "인사", "취임",
)

# 기업 개별 소식. KOSIS 는 개별 기업 실적을 수록하지 않는다.
FIRM = ("은행", "증권", "보험", "카드", "그룹", "회장", "사장", "대표이사",
        "재단", "장학", "노조", "파업", "소송", "인수", "합병")

# **해외 통계는 KOSIS 에 없다.** 1차 점수화에서 상위권이 '미국 1월 소비자물가',
# '中 4월 소비자물가', 'IMF 성장률 전망' 으로 가득 찼다.
# 거시지표어와 수치를 다 갖췄지만 한국 통계가 아니다.
# 돌려보기 전에 잡았다 — 안 잡았으면 한 시간을 날렸다.
FOREIGN = ("미국", "美", "중국", "中", "일본", "日", "유럽", "EU", "독일", "英", "영국",
           "IMF", "OECD", "WTO", "연준", "Fed", "트럼프", "바이든", "시진핑",
           "뉴욕", "월가", "나스닥", "다우", "글로벌", "세계")
# 다만 '대미 수출', '중국 수출' 처럼 **한국 통계의 상대국**은 KOSIS 에 있다.
FOREIGN_OK = ("수출", "수입", "무역", "관세", "교역")

# 제목이 수치를 인용하는가. 논평 기사와 통계 인용 기사를 가르는 신호다.
NUMBER = re.compile(r"\d[\d,.]*\s*(%|％|억|조|만|천|명|개|대|건|달러|원|포인트|배|위)")

# 정부 부처·기관 발표는 KOSIS 수록 통계일 확률이 높다.
OFFICIAL = ("통계청", "한국은행", "기재부", "기획재정부", "산업부", "산업통상자원부",
            "국토부", "국토교통부", "고용노동부", "관세청", "농식품부", "정부")


# 아카이브 원본(`검증대상_기사드랍후.csv`)은 작성일이 **엑셀 일련번호**다(45749.0).
# 그대로 두면 '작년' 이 언제인지 못 풀어 기간 추출이 통째로 깨진다.
# 2026-08-04 홀드아웃 준비에서 한 번 밟았던 함정이라 여기서 자동으로 고친다.
_EXCEL_EPOCH = "1899-12-30"


def normalize_date(value: str) -> str:
    raw = str(value or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    try:
        serial = float(raw)
    except ValueError:
        return raw
    import datetime
    base = datetime.date.fromisoformat(_EXCEL_EPOCH)
    return (base + datetime.timedelta(days=int(serial))).isoformat()


def normalize_label(value: str) -> str:
    """레이블 표기를 앞 묶음들과 맞춘다(1/0 -> TRUE/FALSE)."""
    raw = str(value or "").strip()
    return {"1": "TRUE", "0": "FALSE"}.get(raw, raw)


def score_title(title: str) -> tuple[int, list[str]]:
    text = str(title or "")
    score, why = 0, []
    macro = [word for word in MACRO if word in text]
    if macro:
        score += 40 + 10 * min(len(macro), 3)
        why.append(f"거시지표({'/'.join(macro[:3])})")
    weak = [word for word in WEAK if word in text]
    if weak:
        score -= 50
        why.append(f"약한계열({'/'.join(weak[:2])})")
    firm = [word for word in FIRM if word in text]
    if firm:
        score -= 40
        why.append(f"기업소식({'/'.join(firm[:2])})")
    if NUMBER.search(text):
        score += 35
        why.append("제목에 수치")
    else:
        score -= 15
        why.append("수치 없음")
    if any(word in text for word in OFFICIAL):
        score += 20
        why.append("공식기관")
    foreign = [word for word in FOREIGN if word in text]
    if foreign and not any(word in text for word in FOREIGN_OK):
        score -= 70
        why.append(f"해외통계({'/'.join(foreign[:2])})")
    return score, why


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--articles", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--exclude", type=Path, action="append", default=[],
                        help="이미 쓴 기사 CSV. URL 로 제외한다")
    parser.add_argument("--top", type=int, default=50)
    parser.add_argument("--title-col", default="기사제목")
    parser.add_argument("--url-col", default="URL")
    parser.add_argument("--date-col", default="작성일")
    parser.add_argument("--label-col", default="검색 구분 레이블")
    args = parser.parse_args()

    with args.articles.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    used: set[str] = set()
    for path in args.exclude:
        if path.exists():
            with path.open(encoding="utf-8-sig", newline="") as handle:
                used |= {str(r.get(args.url_col, "")).strip()
                         for r in csv.DictReader(handle)}

    scored = []
    seen_title: set[str] = set()
    for row in rows:
        if str(row.get(args.url_col, "")).strip() in used:
            continue
        # 같은 기사가 제목만 같고 URL 이 다른 경우가 있다(재송고).
        # 1차 점수화에서 상위 15개 중 3쌍이 중복이었다.
        title_key = "".join(str(row.get(args.title_col, "")).split())
        if title_key in seen_title:
            continue
        seen_title.add(title_key)
        value, why = score_title(row.get(args.title_col))
        fixed = dict(row)
        fixed[args.date_col] = normalize_date(row.get(args.date_col))
        if args.label_col in fixed:
            fixed[args.label_col] = normalize_label(fixed[args.label_col])
        scored.append({**fixed, "affinity_score": value, "affinity_why": " · ".join(why)})
    scored.sort(key=lambda r: -r["affinity_score"])
    picked = scored[:args.top]

    fields = list(rows[0].keys()) + ["affinity_score", "affinity_why"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(picked)

    print(f"후보 {len(scored)} (제외 {len(used)}) → 상위 {len(picked)} 저장: {args.output}")
    dates = sorted(r[args.date_col] for r in picked if r[args.date_col])
    print(f"점수 범위 {picked[-1]['affinity_score']} ~ {picked[0]['affinity_score']}"
          f" | 기간 {dates[0]} ~ {dates[-1]}\n")
    for row in picked[:15]:
        print(f"  {row['affinity_score']:>4}  {str(row[args.title_col])[:52]:54s} {row['affinity_why'][:40]}")
    print("\n**이 점수는 기사 13개에서 뽑은 규칙이다.** 실제로 돌려서 확정률이 오르는지 확인할 것.")


if __name__ == "__main__":
    main()
