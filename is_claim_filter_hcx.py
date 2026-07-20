"""정제 문장 → is_claim 판별 (HCX-007 + Structured Outputs)

기존 Claude 대화 기반 is_claim 필터를 재현 가능한 코드로 대체하는 스크립트.
주의: v1.2부터 KOSIS 검증 가능성 판단을 포함하는 결합형 기준 (해외/기업/여론조사/전망 = False).

사용법:
  python is_claim_filter_hcx.py --input 뉴스_데이터_정제문장.csv --output is_claim_200.csv --limit 200

- 입력 컬럼 자동 인식: 은결님 형식(문장/전_문장/다음_문장/작성일) 또는 표준 형식(claim_text/prev_sentence/...)
- 모든 비어있지 않은 문장을 LLM이 판정 (무숫자 추세 주장도 포함: "작년에 비해 상승했다")
- 이어받기: 중단 후 재실행하면 완료된 claim_id 는 건너뜀
- .env 에 CLOVA_API_KEY 필요
"""
import argparse
import csv
import json
import os
import re
import sys
import time
import uuid

import requests
from dotenv import load_dotenv

csv.field_size_limit(2 ** 31 - 1)

URL = "https://clovastudio.stream.ntruss.com/v3/chat-completions/{model}"
PROMPT_VERSION = "isclaim-v1.2-kosis-combined"

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_claim": {"type": "string", "enum": ["True", "False"]},
        "reason": {"type": "string", "description": "판단 근거 한 문장"},
        "confidence": {"type": "string", "enum": ["high", "mid", "low"]},
    },
    "required": ["is_claim", "reason", "confidence"],
}

SYSTEM_PROMPT = """당신은 한국 뉴스의 수치 주장을 KOSIS(국가통계포털) 통계표로 검증할 수 있는지 분류하는 데이터 라벨러다.
[True 조건]
- '현재 문장'이 수치, 비율, 규모, 평균, 증감률, 순위 또는 통계 지표의 변화 방향을 주장한다.
- 인구·가구·고용·물가·소득·산업·무역·교육·보건·복지·지역 등 국내 집계 통계이며, KOSIS에서 지표/시점/지역/대상을 맞춰 대조할 가능성이 높다.
- 숫자가 없어도 '출산율이 증가했다', '실업률이 전년보다 낮아졌다', '인구가 감소세로 돌아섰다'처럼 KOSIS 시계열 값으로 증가·감소·상승·하락·최고·최저 여부를 확인할 수 있으면 True다.
- 앞뒤 문장과 기사 작성일은 현재 문장의 생략된 지표명·시점·대상·비교 기준을 해석하는 데 사용한다.
[False 조건]
- 개인의 나이, 주소, 날짜/시각, 경기 점수, 제품 가격 하나처럼 집계 통계가 아니다.
- 특정 사건의 사망·부상·탑승 인원, 현장 상황, 단순 횟수이다.
- 특정 기업 한 곳의 매출·주가·실적, 해외 통계, 여론조사, 전망·목표·추정이다.
- 숫자가 기사 작성일, 법 조항, 모델명, 순번의 의미일 뿐이다.
- 단순 의견·평가·원인 설명일 뿐, 통계값이나 통계적 변화 방향에 관한 사실 주장이 아니다.
- 앞/뒤 문장만 검증 가능하고 현재 문장은 그렇지 않다.
- KOSIS에 있을지 불확실하면 False로 보수적으로 판정한다."""

USER_TMPL = """기사 작성일: {date}
이전 문장: {prev}
[현재 문장] {text}
다음 문장: {next}

위 [현재 문장]을 판별해 JSON으로 답하라."""

# 입력 컬럼 자동 매핑 (은결님 형식 ↔ 표준 형식)
COL_ALIASES = {
    "claim_text": ["claim_text", "문장"],
    "prev_sentence": ["prev_sentence", "전_문장"],
    "next_sentence": ["next_sentence", "다음_문장"],
    "date": ["date", "작성일"],
    "claim_id": ["claim_id"],
    "article_id": ["article_id"],
    "title": ["title", "기사제목"],
    "url": ["url", "URL"],
}

HAS_NUMBER_RE = re.compile(r"\d")


def resolve_cols(fieldnames):
    m = {}
    for std, cands in COL_ALIASES.items():
        for c in cands:
            if c in fieldnames:
                m[std] = c
                break
    for required in ("claim_id", "claim_text"):
        if required not in m:
            raise SystemExit(f"입력 CSV에서 {required} 컬럼을 찾을 수 없습니다. 컬럼: {fieldnames}")
    return m


def call_hcx(api_key, model, text, prev, nxt, date="-", retries=4):
    body = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_TMPL.format(date=date or "-", prev=prev or "-", text=text, next=nxt or "-")},
        ],
        "temperature": 0.0, "topP": 0.8, "seed": 42,
    }
    if model.startswith("HCX-007"):
        body["thinking"] = {"effort": "none"}
        body["maxCompletionTokens"] = 300
        body["responseFormat"] = {"type": "json", "schema": RESPONSE_SCHEMA}
    else:
        body["maxTokens"] = 300
    headers = {"Authorization": f"Bearer {api_key}",
               "X-NCP-CLOVASTUDIO-REQUEST-ID": str(uuid.uuid4()),
               "Content-Type": "application/json"}
    for i in range(retries):
        r = requests.post(URL.format(model=model), headers=headers, json=body, timeout=60)
        if r.status_code == 429:
            time.sleep(5 * (i + 1)); continue
        r.raise_for_status()
        content = r.json()["result"]["message"]["content"]
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            raise ValueError("JSON 없음")
        return json.loads(m.group(0))
    raise RuntimeError("rate limit 재시도 초과")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", default="is_claim_filtered.csv")
    ap.add_argument("--model", default="HCX-007")
    ap.add_argument("--limit", type=int, default=0, help="앞에서부터 N건만 판정 (0=전체)")
    ap.add_argument("--sleep", type=float, default=0.5)
    a = ap.parse_args()

    load_dotenv()
    key = os.getenv("CLOVA_API_KEY")
    if not key:
        raise SystemExit(".env 에 CLOVA_API_KEY 를 설정하세요")

    with open(a.input, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        cols = resolve_cols(reader.fieldnames)

    out_cols = list(rows[0].keys()) + ["is_claim", "is_claim_reason", "is_claim_confidence",
                                       "is_claim_method", "extraction_model", "prompt_version", "extracted_at"]
    done = set()
    if os.path.exists(a.output):
        with open(a.output, encoding="utf-8-sig") as f:
            done = {r[cols["claim_id"]] for r in csv.DictReader(f)}
        print(f"이어받기: {len(done)}건 완료됨")

    today = time.strftime("%Y-%m-%d")
    n = n_api = n_rule = n_y = 0
    mode = "a" if done else "w"
    with open(a.output, mode, newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=out_cols)
        if mode == "w":
            w.writeheader()
        for r in rows:
            cid = r[cols["claim_id"]]
            if cid in done:
                continue
            if a.limit and n >= a.limit:
                break
            text = str(r.get(cols["claim_text"], "") or "").strip()
            out = dict(r)
            out.update({"extraction_model": a.model, "prompt_version": PROMPT_VERSION, "extracted_at": today})
            try:
                if not text:
                    out.update({"is_claim": "False", "is_claim_reason": "빈 문장", "is_claim_confidence": "high",
                                "is_claim_method": "rule"})
                    n_rule += 1
                else:
                    j = call_hcx(key, a.model, text,
                                 r.get(cols.get("prev_sentence", ""), "-"), r.get(cols.get("next_sentence", ""), "-"),
                                 date=r.get(cols.get("date", ""), "-"))
                    out.update({"is_claim": j.get("is_claim", "False"), "is_claim_reason": j.get("reason", "-"),
                                "is_claim_confidence": j.get("confidence", "-"), "is_claim_method": "hcx"})
                    n_api += 1
                    time.sleep(a.sleep)
                n_y += out["is_claim"] == "True"
                w.writerow(out); f.flush()
                print(f"[{cid}] {out['is_claim']} ({out['is_claim_method']}) {out['is_claim_reason'][:40]}")
            except Exception as e:
                print(f"[{cid}] 실패: {type(e).__name__}: {e}")
            n += 1
    print(f"\n완료 → {a.output}")
    print(f"판정 {n}건 = API {n_api} + 규칙 {n_rule} | is_claim=True: {n_y}건 ({n_y / max(n, 1):.0%})")


if __name__ == "__main__":
    main()
