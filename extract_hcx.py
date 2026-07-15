"""HCX 기반 claim 구조화 추출 (v3 스키마)

사용법:
  1) .env 에 CLOVA_API_KEY=... 저장 (커밋 금지)
  2) pip install requests python-dotenv
  3) python extract_hcx.py --input hcx_input_100.csv --output hcx_extracted.csv
     [--model HCX-007] [--limit 5]  # --limit 로 소량 먼저 확인 권장

- 중단돼도 재실행하면 이미 처리한 claim_id 는 건너뛴다 (이어받기).
- 출력은 v3 스키마 43컬럼, measurement 행 분리 형식 → score_pilot.py 로 바로 채점 가능.
"""
import argparse
import csv
import json
import os
import re
import time
import uuid

import requests
from dotenv import load_dotenv

URL = "https://clovastudio.stream.ntruss.com/v3/chat-completions/{model}"

RESPONSE_SCHEMA = {
  "type": "object",
  "properties": {
    "claim_domain_scope": {"type": "string", "enum": ["국내공식통계","해외통계·정책","개별기업","여론조사·설문","전망·목표","기타"]},
    "is_recurring_series": {"type": "string", "enum": ["Y","N"]},
    "metric_domain": {"type": "string", "enum": ["물가","고용","무역","인구","소득·임금","소매·소비","생산·산업","부동산","금융·금리","재정·조세","보건·복지","에너지·환경","기타"]},
    "indicator": {"type": "string"},
    "keywords": {"type": "string", "description": "통계표명에 나올 법한 단어 2~5개, ; 구분"},
    "region": {"type": "string"}, "age_group": {"type": "string"},
    "gender": {"type": "string", "enum": ["남","여","전체","-"]},
    "industry_or_item": {"type": "string"}, "population_etc": {"type": "string"},
    "origin_country": {"type": "string"}, "destination_country": {"type": "string"},
    "period": {"type": "string", "description": "YYYY, YYYYMM, YYYYQn, YYYYHn, - 중 하나. 예: 202508, 2025Q1, 2024H2"},
    "period_end": {"type": "string"},
    "prd_se": {"type": "string", "enum": ["Y","M","Q","H","-"]},
    "time_resolution_status": {"type": "string", "enum": ["확정","모호","결측","충돌"]},
    "measurements": {"type": "array", "items": {"type": "object", "properties": {
      "measurement_role": {"type": "string", "enum": ["현재값","이전값","증감값","증감률","목표값","참고값"]},
      "value": {"type": "number"},
      "value_min": {"type": "string"}, "value_max": {"type": "string"},
      "value_approximate": {"type": "string", "enum": ["Y","N"]},
      "unit": {"type": "string"},
      "value_type": {"type": "string", "enum": ["수준값","증감률","증감량","비중","순위"]},
      "direction": {"type": "string", "enum": ["증가","감소","유지","-"]},
      "change_base": {"type": "string", "enum": ["전년동월","전월","전분기","전년동기","전년","특정시점","-"]}},
      "required": ["measurement_role","value","unit","value_type","direction","change_base"]}},
    "evidence_text": {"type": "string", "description": "원문 구절 그대로 발췌, 따옴표 포함 변형 금지"},
    "extraction_confidence": {"type": "string", "enum": ["high","mid","low"]},
    "needs_review": {"type": "string", "enum": ["Y","N"]},
    "review_reason": {"type": "string"}
  },
  "required": ["claim_domain_scope","is_recurring_series","metric_domain","indicator","keywords",
               "region","age_group","gender","period","prd_se","time_resolution_status",
               "measurements","evidence_text","extraction_confidence","needs_review"]
}



SYSTEM_PROMPT = """너는 한국 뉴스 문장에서 통계 주장을 구조화 추출하는 시스템이다. 반드시 JSON만 출력한다.

## 출력 JSON 스키마
{
 "claim_domain_scope": "국내공식통계|해외통계·정책|개별기업|여론조사·설문|전망·목표|기타",
 "is_recurring_series": "Y|N",  // 반복 집계되는 통계 시리즈인가. 일회성 사건·발표는 N
 "metric_domain": "물가|고용|무역|인구|소득·임금|소매·소비|생산·산업|부동산|금융·금리|재정·조세|보건·복지|에너지·환경|기타",
 "indicator": "수식어 포함 지표명 (예: 청년실업률, 근원물가상승률)",
 "keywords": "통계표명에 나올 법한 단어 2~5개, ; 구분",
 "region": "행정구역 정식명. 국내 통계인데 지역 언급 없으면 전국. 해외 국가명 금지. 없으면 -",
 "age_group": "표준 구간 (청년→15~29세, 20대→20~29세, 고령층→65세 이상). 없으면 -",
 "gender": "남|여|전체|-",
 "industry_or_item": "산업/품목명. 없으면 -",
 "population_etc": "기타 대상 집단. 없으면 -",
 "origin_country": "-", "destination_country": "-",  // 무역 claim 한정 수입선/수출선
 "period": "YYYY|YYYYMM|YYYYQn|YYYYHn|-",  // 기사 날짜 기준 상대시점 역산 필수
 "period_end": "구간 주장의 끝. 단일 시점이면 -",
 "prd_se": "Y|M|Q|H|-",  // period 형식과 일관되게
 "time_resolution_status": "확정|모호|결측|충돌",
 "measurements": [  // 수치마다 하나. 날짜·서수(29일 발표, 3위 등 시점·순번)는 넣지 않는다
   {"measurement_role": "현재값|이전값|증감값|증감률|목표값|참고값",
    "value": 숫자,  // 한국어 수사 환산: 2만867→20867, 31.2만→312000
    "value_min": "범위 표현의 하한 (3%대→3). 아니면 -",
    "value_max": "범위 표현의 상한 (3%대→3.9). 아니면 -",
    "value_approximate": "Y|N",  // 약/가량/수준
    "unit": "%|%p|명|원|건|대(수량) 등. %와 %p 반드시 구분. 만명→명으로 환산",
    "value_type": "수준값|증감률|증감량|비중|순위",
    "direction": "증가|감소|유지|-",
    "change_base": "전년동월|전월|전분기|전년동기|전년|특정시점|-"}],
 "evidence_text": "판단 근거 원문 구절 그대로 (요약·변형 금지)",
 "extraction_confidence": "high|mid|low",
 "needs_review": "Y|N", "review_reason": "-"
}

## 판정 규칙
- verifiable(검증가능)은 시스템이 계산하므로 출력하지 않는다. scope와 recurring만 정확히.
- 중의성 주의: '청년'은 연령(년도 아님), 'N대 기업'은 순위(연령 아님), '6만3849대'는 수량, '1분기'는 Q1.
- 검증가능해도 수치가 기록·연속형('27개월째 마이너스')이면 measurements는 빈 배열 + needs_review=Y.
- claim_domain_scope가 국내공식통계가 아니면 measurements는 빈 배열로 둔다."""

USER_TMPL = """기사 날짜: {date}
이전 문장: {prev}
[검증 대상 문장] {text}
다음 문장: {next}

위 [검증 대상 문장]의 통계 주장을 JSON으로 추출하라."""

OUT_COLS = ["claim_id", "claim_measurement_id", "article_id", "title", "date", "url",
            "claim_text", "prev_sentence", "next_sentence",
            "claim_domain_scope", "is_recurring_series", "verifiable_kosis", "unverifiable_reason",
            "metric_domain", "indicator", "keywords", "region", "age_group", "gender",
            "industry_or_item", "population_etc", "origin_country", "destination_country",
            "period", "period_end", "prd_se", "time_resolution_status",
            "measurement_role", "value", "value_min", "value_max", "value_approximate",
            "unit", "value_type", "direction", "change_base",
            "evidence_text", "extraction_confidence", "needs_review", "review_reason",
            "extraction_model", "prompt_version", "extracted_at"]
PROMPT_VERSION = "v1.1-hcx-so"
REASON_MAP = {"해외통계·정책": "해외통계", "개별기업": "개별기업", "여론조사·설문": "여론조사·설문",
              "전망·목표": "전망·예측", "기타": "정보부족"}


def call_hcx(api_key, model, date, text, prev, nxt, retries=4, effort="none"):
    body = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_TMPL.format(date=date, prev=prev, text=text, next=nxt)},
        ],
        "temperature": 0.0, "topP": 0.8, "seed": 42,
    }
    if model.startswith("HCX-007"):  # 추론 모델: maxTokens 불가, thinking 설정 필요
        body["thinking"] = {"effort": "none"}  # Structured Outputs는 추론과 동시 사용 불가
        body["maxCompletionTokens"] = 2000
        body["responseFormat"] = {"type": "json", "schema": RESPONSE_SCHEMA}
    else:
        body["maxTokens"] = 2000
    headers = {"Authorization": f"Bearer {api_key}",
               "X-NCP-CLOVASTUDIO-REQUEST-ID": str(uuid.uuid4()),
               "Content-Type": "application/json"}
    for i in range(retries):
        r = requests.post(URL.format(model=model), headers=headers, json=body, timeout=90)
        if r.status_code == 429:
            time.sleep(5 * (i + 1)); continue
        r.raise_for_status()
        return r.json()["result"]["message"]["content"]
    raise RuntimeError("rate limit 재시도 초과")


def parse_json(s):
    m = re.search(r"\{.*\}", s, re.S)
    if not m:
        raise ValueError("JSON 없음")
    return json.loads(m.group(0))


def norm(x):
    s = str(x).strip() if x is not None else "-"
    return s if s else "-"


def to_rows(claim, j, model):
    scope, rec = norm(j.get("claim_domain_scope")), norm(j.get("is_recurring_series"))
    verifiable = "Y" if (scope == "국내공식통계" and rec == "Y") else "N"
    reason = "-" if verifiable == "Y" else REASON_MAP.get(scope, "정보부족")
    base = {c: norm(claim.get(c)) for c in ["claim_id", "article_id", "title", "date", "url",
                                            "claim_text", "prev_sentence", "next_sentence"]}
    base.update({
        "claim_domain_scope": scope, "is_recurring_series": rec,
        "verifiable_kosis": verifiable, "unverifiable_reason": reason,
        **{k: norm(j.get(k)) for k in ["metric_domain", "indicator", "keywords", "region",
                                       "age_group", "gender", "industry_or_item", "population_etc",
                                       "origin_country", "destination_country", "period", "period_end",
                                       "prd_se", "time_resolution_status", "evidence_text",
                                       "extraction_confidence", "needs_review", "review_reason"]},
        "extraction_model": model, "prompt_version": PROMPT_VERSION,
        "extracted_at": time.strftime("%Y-%m-%d"),
    })
    meas = j.get("measurements") or []
    if verifiable == "N" or not meas:
        row = dict(base)
        row.update({c: "-" for c in ["claim_measurement_id", "measurement_role", "value", "value_min",
                                     "value_max", "value_approximate", "unit", "value_type",
                                     "direction", "change_base"]})
        return [row]
    rows = []
    for k, m in enumerate(meas, 1):
        row = dict(base)
        row.update({"claim_measurement_id": f"{base['claim_id']}-m{k}",
                    **{f: norm(m.get(f)) for f in ["measurement_role", "value", "value_min", "value_max",
                                                   "value_approximate", "unit", "value_type",
                                                   "direction", "change_base"]}})
        rows.append(row)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="hcx_input_100.csv")
    ap.add_argument("--output", default="hcx_extracted.csv")
    ap.add_argument("--model", default="HCX-007")
    ap.add_argument("--effort", default="none", choices=["none", "low", "medium"],
                    help="HCX-007 추론 깊이 (구조화 추출은 none 권장)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=1.0)
    a = ap.parse_args()

    load_dotenv()
    key = os.getenv("CLOVA_API_KEY")
    if not key:
        raise SystemExit(".env 에 CLOVA_API_KEY 를 설정하세요")

    with open(a.input, encoding="utf-8-sig") as f:
        claims = list(csv.DictReader(f))
    done = set()
    if os.path.exists(a.output):
        with open(a.output, encoding="utf-8-sig") as f:
            done = {r["claim_id"] for r in csv.DictReader(f)}
        print(f"이어받기: {len(done)}건 완료됨")

    mode = "a" if done else "w"
    with open(a.output, mode, newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLS)
        if mode == "w":
            w.writeheader()
        n = 0
        for c in claims:
            if c["claim_id"] in done:
                continue
            if a.limit and n >= a.limit:
                break
            try:
                raw = call_hcx(key, a.model, c.get("date", "-"), c["claim_text"],
                               c.get("prev_sentence", "-"), c.get("next_sentence", "-"),
                               effort=a.effort)
                rows = to_rows(c, parse_json(raw), a.model)
                w.writerows(rows); f.flush()
                print(f"[{c['claim_id']}] ok ({len(rows)} 행)")
            except Exception as e:
                print(f"[{c['claim_id']}] 실패: {type(e).__name__}: {e}")
            n += 1
            time.sleep(a.sleep)
    print("완료 →", a.output)


if __name__ == "__main__":
    main()
