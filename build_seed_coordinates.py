#!/usr/bin/env python3
"""사람이 손으로 맞춘 지표→좌표 매핑을 씨앗 사전으로 가져온다 (2026-08-05).

## 왜 필요한가

**우리 병목은 좌표 선택이다.** 네 번 독립으로 쟀고 매번 같은 답이 나왔다.

    홀드아웃3   좌표 문제 38 / 시스템 한계 46 = 83%
    홀드아웃4   좌표 문제 95 / 시스템 한계 119 = 80%   (평가집합 162, 표본 3배)

그리고 **지금 골드로는 이걸 고쳤는지 잴 수가 없다.** `gold_confirmed_v3` 는
`build_gold_from_evidence` 가 우리 후보 중 값이 재현되는 좌표를 골드로 삼은 것이라
"골드 표가 후보 안에 있는가"가 동어반복이다(실측 Recall@3 = 100%).

어제 KOSIS 공식 통합검색으로 독립 골드를 만들려다 실패했다 —
782개를 새로 가져왔는데 **정답은 0개**였다. 키워드 검색이라 노이즈만 늘었다.

## 무엇을 가져오는가

`Dayoooun/korea-stats-mcp` (MIT) 의 `src/data/quickStatsParams.ts` 다.
83개 키워드가 **완성된 좌표**로 하드코딩돼 있다:

    orgId · tableId · itemId · objL1 · objL2 · unit · supportedPeriods

사람이 KOSIS 메타데이터를 보고 손으로 맞춘 것이고, **우리 임베딩과 무관하다.**
그게 독립 골드의 자격 조건이다.

**시도 지역 코드 5종**이 특히 값지다. 같은 '서울' 이 표마다 다르다:

    인구동향  서울 11 · 부산 21        주민등록  서울 11 · 부산 26
    물가      서울 T11 · 부산 T12      주택      서울 a7 · 부산 b1
    미세먼지  13102128219A.4200003

홀드아웃3 의 거짓 불일치 둘이 `국가별 수출액` 에서 **분류1을 '계'로 고른** 것이었다.
축 값을 못 고르는 같은 계열의 문제고, 우리 OBJ 선택에는 지역 어휘가 아예 없다.

## 그대로 믿지 않는다

별 8개 개인 프로젝트고 주석은 "2024년 기준" 이다. 좌표가 낡았거나 틀릴 수 있다.
**`verify_seed_coordinates.py` 로 KOSIS 에 직접 조회해 통과한 것만 쓴다.**
검증 안 한 좌표를 골드로 삼으면 순환 골드보다 더 나쁘다 — 틀린 답을 정답이라 믿게 된다.

## 한계

- **83개 키워드는 KOSIS 90만 표에 비하면 아무것도 아니다.** 우리 표 인덱스는 107,138개다.
- **전부 국가/시도 총계다.** 품목축·상대국축이 없다.
  홀드아웃4 상위 지표 중 `대미 수출액`·`달걀 물가`·`설비투자`·`원·달러 환율` 은 못 덮는다.
  **홀드아웃3에서 우리가 틀린 바로 그 유형(중국 수출·미국 수출)이 안 덮인다.**
- 그러므로 이건 해법이 아니라 **정답지**다. 좌표 선택을 고칠 때 채점에 쓴다.

## 쓰는 법

    curl -sL https://raw.githubusercontent.com/Dayoooun/korea-stats-mcp/main/\\
src/data/quickStatsParams.ts -o data/vendor/quickStatsParams.ts

    python build_seed_coordinates.py \\
      --source data/vendor/quickStatsParams.ts \\
      --output data/seed_coordinates.csv \\
      --region-output data/seed_region_codes.csv
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

FIELDS = ["keyword", "org_id", "tbl_id", "tbl_name", "description",
          "itm_id", "obj_l1", "obj_l2", "unit", "prd_se_list",
          "region_scheme", "source"]

REGION_FIELDS = ["scheme", "region", "code"]

SOURCE = "korea-stats-mcp"

# TS 객체 리터럴을 파싱한다. 완전한 파서는 필요 없다 —
# 이 파일은 기계 생성에 가까운 일정한 모양이고, 어긋나면 개수로 잡힌다.
_ENTRY = re.compile(r"^\s*'([^']+)':\s*\{(.*?)^\s*\},", re.S | re.M)
_FIELD = re.compile(r"(\w+):\s*'([^']*)'")
_REGION_REF = re.compile(r"regionCodes:\s*(REGION_CODES_\w+)")
_PERIODS = re.compile(r"supportedPeriods:\s*\[([^\]]*)\]")

_REGION_BLOCK = re.compile(
    r"export const (REGION_CODES_\w+)[^=]*=\s*\{(.*?)^\};", re.S | re.M)
_REGION_PAIR = re.compile(r"'([^']+)':\s*'([^']*)'")


def strip_comments(text: str) -> str:
    """주석 안의 문자열이 필드로 잡히지 않게 지운다.

    `objL1: '00',          // 전국 (C1: "00")` 같은 줄이 많다.
    작은따옴표가 주석에 들어 있으면 필드 파싱이 어긋난다.
    """
    return re.sub(r"//[^\n]*", "", text)


def parse_regions(text: str) -> list[dict]:
    out = []
    for match in _REGION_BLOCK.finditer(text):
        scheme = match.group(1)
        for region, code in _REGION_PAIR.findall(strip_comments(match.group(2))):
            out.append({"scheme": scheme, "region": region, "code": code})
    return out


def parse_entries(text: str) -> list[dict]:
    """QUICK_STATS_PARAMS 블록만 읽는다. 지역 코드 상수는 위에서 따로 처리한다."""
    start = text.find("QUICK_STATS_PARAMS")
    if start < 0:
        raise SystemExit("QUICK_STATS_PARAMS 를 못 찾았다. 원본 구조가 바뀌었다")
    body = text[start:]

    out = []
    for match in _ENTRY.finditer(body):
        keyword, block = match.group(1), match.group(2)
        clean = strip_comments(block)
        fields = dict(_FIELD.findall(clean))
        if not fields.get("tableId"):
            continue
        periods = _PERIODS.search(clean)
        prd = ("|".join(p.strip().strip("'\"") for p in periods.group(1).split(",")
                        if p.strip()) if periods else "Y")
        region = _REGION_REF.search(clean)
        out.append({
            "keyword": keyword,
            "org_id": fields.get("orgId", ""),
            "tbl_id": fields.get("tableId", ""),
            "tbl_name": fields.get("tableName", ""),
            "description": fields.get("description", ""),
            "itm_id": fields.get("itemId", ""),
            "obj_l1": fields.get("objL1", ""),
            "obj_l2": fields.get("objL2", ""),
            "unit": fields.get("unit", ""),
            "prd_se_list": prd,
            "region_scheme": region.group(1) if region else "",
            "source": SOURCE,
        })
    return out


def write(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--region-output", type=Path)
    args = parser.parse_args()

    text = args.source.read_text(encoding="utf-8")
    rows = parse_entries(text)
    regions = parse_regions(text)

    write(args.output, rows, FIELDS)
    if args.region_output:
        write(args.region_output, regions, REGION_FIELDS)

    tables = {row["tbl_id"] for row in rows}
    schemes = {row["scheme"] for row in regions}
    print(f"키워드 {len(rows)} · 고유 표 {len(tables)} → {args.output}")
    if args.region_output:
        print(f"지역코드 {len(regions)} · 체계 {len(schemes)} → {args.region_output}")
    print("\n주기별:", end=" ")
    from collections import Counter
    print(dict(Counter(row["prd_se_list"] for row in rows)))
    print("\n**검증 안 된 좌표다.** verify_seed_coordinates.py 를 반드시 돌릴 것 —")
    print("틀린 좌표를 골드로 삼으면 순환 골드보다 나쁘다.")


if __name__ == "__main__":
    main()
