"""LLM 기반 자동매핑 프로토타입 (HCX-007, structured output).

목적: 정규식 규칙(kosis_codebook_v2/v3)이 놓치는 claim을, 후보 KOSIS 표를 미리
좁혀준 상태에서 HCX-007이 JSON schema로 강제된 구조화 출력으로 선택하게 만들고,
그 출력이 실제로 후보 목록 안에 있는 코드인지(hallucination guard) 검증하는
전체 흐름을 작은 규모(claim 5~10건)로 시연한다.

설계 원칙 (오늘 멘토 미팅 피드백 반영):
1. LLM에게 "알아서 매핑해봐"라고 통째로 맡기지 않는다. 후보 표 몇 개를 미리
   좁혀서 그 안에서만 고르게 한다 (canонical candidate pool).
2. LLM 출력은 반드시 JSON schema(Structured Outputs)로 강제한다.
3. LLM이 뱉은 org_id/tbl_id/obj_l1/itm_id가 후보 목록에 실제로 있는 값인지
   코드로 재검증한다. 없는 값을 만들어냈으면(hallucination) 그 결과는 버리고
   "매핑실패"로 처리한다 -- 이게 없으면 "일치한다는데 사실 안 맞는" 최악의
   상황(멘토 피드백)이 재발한다.
4. 이 스크립트는 최종 값 비교(verify())까지는 하지 않는다. LLM이 올바른
   표/분류/항목/시점을 고르는지까지만 확인하는 1단계 프로토타입이다.
   실제 KOSIS 수치 대조는 기존 kosis_codebook_v2.verify()를 그대로 재사용하면
   된다 (이 스크립트가 만든 결과를 config dict로 변환해서 넘기면 됨).

실행 전 준비:
- pip install langchain-naver pydantic python-dotenv
- .env에 CLOVASTUDIO_API_KEY=발급받은_키 추가
- 네이버클라우드플랫폼 콘솔에서 CLOVA Studio 앱(Test App)을 만들고 API 키 발급

실행:
    python llm_auto_mapping_prototype.py
"""

from __future__ import annotations

import csv
import os
import sys
from typing import Literal, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

csv.field_size_limit(sys.maxsize)

# ---------------------------------------------------------------------------
# 1. 후보 KOSIS 표 풀 (canonical candidate pool)
#
# 실제 파이프라인에서는 match_claims_to_tables.py + kosis_metadata_summary.py로
# claim마다 동적으로 후보를 좁혀야 하지만, 이 프로토타입은 "LLM + structured
# output + hallucination guard" 메커니즘 자체를 검증하는 게 목적이라 물가
# 도메인에서 이미 확인된 표 5개만 고정 후보로 둔다.
# ---------------------------------------------------------------------------
CANDIDATE_TABLES = [
    {
        "org_id": "101",
        "tbl_id": "DT_1J22042",
        "name": "월별 소비자물가 등락률",
        "obj_l1_options": {
            "0": "총지수",
            "1": "생활물가지수",
            "2": "신선식품지수",
            "4": "식료품 및 에너지제외지수(근원물가)",
        },
        "itm_id_options": {"T03": "전년동월비(%)"},
        "prd_se_options": ["M"],
        "note": "이미 전년동월비가 계산되어 있는 표. mode=LEVEL로 그 값을 그대로 target과 비교.",
    },
    {
        "org_id": "101",
        "tbl_id": "DT_1J22112",
        "name": "품목성질별 소비자물가지수(월)",
        "obj_l1_options": {"T10": "총지수"},
        "obj_l2_options": {
            "B05": "석유류",
            "B01": "가공식품",
            "F01K01126": "라면(외식)",
            "E01H03102": "휴대전화료",
        },
        "itm_id_options": {"T": "지수"},
        "prd_se_options": ["M"],
        "note": "지수 원값. mode=CHANGE_RATE로 두 시점 지수를 직접 비교해야 함.",
    },
    {
        "org_id": "101",
        "tbl_id": "DT_1DA7010S",
        "name": "종사상지위별 취업자(연간)",
        "obj_l1_options": {"06": "자영업자", "21": "고용원 없는 자영업자"},
        "itm_id_options": {"T30": "취업자수(천명)"},
        "prd_se_options": ["Y"],
        "note": "연간 수준값(LEVEL). 사람 수 단위는 천명.",
    },
    {
        "org_id": "360",
        "tbl_id": "DT_1R11001_FRM101",
        "name": "품목별 수출입(통관 기준, 월)",
        "obj_l1_options": {"13102112831A.A": "총수출"},
        "itm_id_options": {"13103112831T1": "수출금액(천달러)"},
        "prd_se_options": ["M"],
        "note": "mode=CHANGE_RATE, 전년동월비 직접 계산 필요.",
    },
    {
        "org_id": "101",
        "tbl_id": "DT_1K41012",
        "name": "소매판매액지수(월/분기)",
        "obj_l1_options": {"G0": "소매판매업 전체", "G31": "음식료품"},
        "itm_id_options": {"T2": "전년동기비", "T3": "전월(전분기)비"},
        "prd_se_options": ["M", "Q"],
        "note": "mode=CHANGE_RATE.",
    },
]


# ---------------------------------------------------------------------------
# 2. Structured output 스키마
# ---------------------------------------------------------------------------
class ClaimMapping(BaseModel):
    """claim_text를 후보 KOSIS 표 중 하나에 매핑한 결과."""

    verifiable: bool = Field(description="후보 표 중 하나로 KOSIS 검증이 가능한 주장인가")
    org_id: Optional[str] = Field(default=None, description="후보 목록에 있는 org_id 그대로. 모르면 null")
    tbl_id: Optional[str] = Field(default=None, description="후보 목록에 있는 tbl_id 그대로. 모르면 null")
    obj_l1: Optional[str] = Field(default=None, description="후보 표의 obj_l1_options 키 중 하나. 모르면 null")
    obj_l2: Optional[str] = Field(default=None, description="후보 표의 obj_l2_options 키 중 하나. 없으면 null")
    itm_id: Optional[str] = Field(default=None, description="후보 표의 itm_id_options 키 중 하나. 모르면 null")
    prd_se: Optional[str] = Field(default=None, description="후보 표의 prd_se_options 중 하나. 모르면 null")
    target_number: Optional[float] = Field(default=None, description="claim이 말하는 실제 목표 수치")
    target_period: Optional[str] = Field(default=None, description="목표 시점, 월=YYYYMM, 연=YYYY, 분기=YYYYQQ")
    prev_period: Optional[str] = Field(default=None, description="비교 기준 시점(있는 경우)")
    mode: Optional[Literal["LEVEL", "CHANGE_RATE", "POINT_CHANGE", "ABS_TO_ABS"]] = Field(
        default=None, description="판정 방식"
    )
    confidence: Literal["high", "medium", "low"] = Field(description="이 매핑 결과에 대한 스스로의 확신도")
    reason: str = Field(description="왜 이 표/분류/항목을 골랐는지, 혹은 왜 검증 불가라고 판단했는지 한국어로 간단히")


def build_prompt(claim: dict) -> str:
    candidate_lines = []
    for table in CANDIDATE_TABLES:
        candidate_lines.append(
            f"- org_id={table['org_id']}, tbl_id={table['tbl_id']} ({table['name']})\n"
            f"    obj_l1 선택지: {table.get('obj_l1_options', {})}\n"
            f"    obj_l2 선택지: {table.get('obj_l2_options', {})}\n"
            f"    itm_id 선택지: {table.get('itm_id_options', {})}\n"
            f"    prd_se 선택지: {table.get('prd_se_options', [])}\n"
            f"    비고: {table.get('note', '')}"
        )
    candidates_text = "\n".join(candidate_lines)

    return f"""아래는 뉴스 기사에서 뽑은 수치 주장(claim)과, 이 주장을 검증할 수 있는
KOSIS 국가통계 후보 표 목록입니다.

[기사 정보]
날짜: {claim.get('date', '')}
제목: {claim.get('title', '')}
앞 문장: {claim.get('prev_sentence', '')}
주장 문장: {claim.get('claim_text', '')}
뒤 문장: {claim.get('next_sentence', '')}

[검증 가능한 후보 KOSIS 표 목록 -- 이 목록에 있는 코드만 사용할 것]
{candidates_text}

[지시사항]
1. 이 주장이 위 후보 표 중 하나로 검증 가능한지 판단하세요.
2. 검증 가능하면 org_id/tbl_id/obj_l1/obj_l2/itm_id/prd_se를 반드시 위 후보
   목록에 있는 값 그대로 채우세요. 목록에 없는 코드를 새로 만들어내지 마세요.
3. 문장에 여러 시점의 숫자가 섞여 있을 때, 진짜 목표 시점과 단순 비교용으로
   언급된 과거 시점(예: "작년 8월(2%) 이후")을 혼동하지 마세요. 이 기사들은
   보통 "지난달"= 기사 날짜 기준 전월 수치를 다룹니다.
4. 전망치/예상치("~할 것으로 전망", "~로 예상")는 검증 가능한 관측 수치가
   아니므로 verifiable=false로 처리하세요.
5. 후보 표 중 어느 것도 맞지 않거나, 확신이 없으면 verifiable=false로 하고
   이유를 reason에 적으세요. 억지로 끼워맞추지 마세요.
"""


def hallucination_guard(mapping: ClaimMapping) -> Optional[str]:
    """LLM 출력이 후보 목록에 실제로 존재하는 코드인지 검증한다.
    문제가 있으면 문제를 설명하는 문자열을, 없으면 None을 반환한다."""
    if not mapping.verifiable:
        return None

    table = next(
        (t for t in CANDIDATE_TABLES if t["org_id"] == mapping.org_id and t["tbl_id"] == mapping.tbl_id),
        None,
    )
    if table is None:
        return f"존재하지 않는 org_id/tbl_id 조합을 생성함: {mapping.org_id}/{mapping.tbl_id}"

    if mapping.obj_l1 and mapping.obj_l1 not in table.get("obj_l1_options", {}):
        return f"후보에 없는 obj_l1 생성함: {mapping.obj_l1}"
    if mapping.obj_l2 and mapping.obj_l2 not in table.get("obj_l2_options", {}):
        return f"후보에 없는 obj_l2 생성함: {mapping.obj_l2}"
    if mapping.itm_id and mapping.itm_id not in table.get("itm_id_options", {}):
        return f"후보에 없는 itm_id 생성함: {mapping.itm_id}"
    if mapping.prd_se and mapping.prd_se not in table.get("prd_se_options", []):
        return f"후보에 없는 prd_se 생성함: {mapping.prd_se}"
    return None


# ---------------------------------------------------------------------------
# 3. 테스트용 claim 5~10건 (holdout3의 물가 도메인에서, 이미 사람이 수동으로
#    분석해둔 것과 같은 claim들 -- LLM 결과와 직접 비교할 수 있도록)
# ---------------------------------------------------------------------------
SAMPLE_CLAIM_IDS = [
    "C03159",  # 정답: 검증불가 (해외 통계, 미국 물가)
    "C03743",  # 정답: 검증가능, DT_1J22042/0/T03/M, target=2.0, period=202501
    "C03745",  # 정답: 애매함 (문장 자체엔 실제 수치 없음)
    "C03749",  # 정답: 검증가능, DT_1J22112/T10/B01/T/M, target=2.7, period=202501
    "C03751",  # 정답: 검증가능, DT_1J22042/1/T03/M, target=2.5, period=202501
    "C18677",  # 정답: 검증가능이지만 "외식 소주" 세부품목 -- 지금 후보 풀엔 코드가 없어서 실패해야 정상
    "C20305",  # 정답: 검증불가 (전망치 문장이 섞여 있음)
]


def load_sample_claims(path: str) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    by_id = {row["claim_id"]: row for row in rows}
    return [by_id[cid] for cid in SAMPLE_CLAIM_IDS if cid in by_id]


def main():
    api_key = os.environ.get("CLOVASTUDIO_API_KEY")
    if not api_key:
        print("CLOVASTUDIO_API_KEY가 .env에 없습니다. 발급받은 키를 .env에 추가하세요.")
        return

    try:
        from langchain_naver import ChatClovaX
    except ImportError:
        print("langchain-naver가 설치되어 있지 않습니다. `pip install langchain-naver`를 먼저 실행하세요.")
        return

    chat = ChatClovaX(
        model="HCX-007",
        thinking={"effort": "none"},  # structured output은 thinking과 함께 못 씀
        temperature=0.1,
    )
    structured_chat = chat.with_structured_output(ClaimMapping, method="json_schema")

    review_path = "outputs/bteam_holdout3/holdout3_100_review.csv"
    claims = load_sample_claims(review_path)
    if not claims:
        print(f"{review_path}에서 샘플 claim을 찾지 못했습니다.")
        return

    print(f"{len(claims)}건 테스트 시작 (모델: HCX-007)\n")
    for claim in claims:
        prompt = build_prompt(claim)
        result: ClaimMapping = structured_chat.invoke(prompt)
        guard_issue = hallucination_guard(result)

        print("=" * 60)
        print(f"claim_id: {claim['claim_id']}")
        print(f"claim_text: {claim['claim_text']}")
        print(f"LLM 판단: verifiable={result.verifiable}, confidence={result.confidence}")
        if result.verifiable:
            print(
                f"  -> org_id={result.org_id}, tbl_id={result.tbl_id}, "
                f"obj_l1={result.obj_l1}, obj_l2={result.obj_l2}, itm_id={result.itm_id}, "
                f"prd_se={result.prd_se}"
            )
            print(
                f"  -> target_number={result.target_number}, target_period={result.target_period}, "
                f"prev_period={result.prev_period}, mode={result.mode}"
            )
        print(f"  reason: {result.reason}")
        if guard_issue:
            print(f"  [경고] hallucination guard 발동: {guard_issue}")
            print("  -> 이 결과는 폐기하고 '매핑실패'로 처리해야 함")
        print()


if __name__ == "__main__":
    main()
