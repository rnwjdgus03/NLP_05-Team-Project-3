"""
KOSIS Open API 호출 테스트 스크립트
- 1단계: 통계목록 API 로 카테고리를 타고 내려가면서 orgId / tblId 찾기
- 2단계: 통계자료(Param) API 로 실제 수치 데이터 조회

사용법:
1) KOSIS 마이페이지 > 이용현황 에서 발급받은 인증키를 아래 API_KEY 에 넣거나
   환경변수 KOSIS_API_KEY 로 설정
2) python kosis_api_test.py
"""

import os
import re
import json
import requests
from dotenv import load_dotenv

load_dotenv()  # 같은 폴더(또는 상위 폴더)의 .env 파일을 읽어서 환경변수로 등록

API_KEY = os.environ.get("KOSIS_API_KEY")
if not API_KEY:
    raise RuntimeError(
        "KOSIS_API_KEY가 없음. .env 파일에 KOSIS_API_KEY=발급받은키 형태로 추가하세요."
    )

LIST_URL = "https://kosis.kr/openapi/statisticsList.do"
DATA_URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"

# KOSIS가 "format=json"으로 줘도 실제로는 key에 따옴표가 없는 JS 객체 리터럴을
# 반환한다 (예: [{LIST_NM:"인구",LIST_ID:"A"}] <- LIST_NM, LIST_ID 에 따옴표 없음).
# 표준 json.loads()는 이걸 못 읽으므로, key를 따옴표로 감싸주는 전처리를 거친다.
_UNQUOTED_KEY = re.compile(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)')


def _parse_kosis_json(text):
    fixed = _UNQUOTED_KEY.sub(r'\1"\2"\3', text)
    parsed = json.loads(fixed)
    # 결과가 1건뿐이면 KOSIS가 리스트가 아니라 객체 하나만 돌려주는 경우가 있어서
    # 항상 리스트로 통일해준다 (안 그러면 for item in ... 할 때 dict의 key(문자열)를
    # 순회하게 돼서 'str' object has no attribute 'get' 에러가 남).
    if isinstance(parsed, dict):
        parsed = [parsed]
    return parsed


def get_list(vw_cd="MT_ZTITLE", parent_id=""):
    """
    통계목록 API - 카테고리를 순회하며 목록/통계표를 탐색.
    parent_id="" 로 호출하면 최상위 목록이 나옴.
    응답의 LIST_ID 를 다음 호출의 parent_id 로 넣으면 하위 목록으로 내려갈 수 있고,
    최종적으로 TBL_ID(통계표ID) + ORG_ID(기관ID) 가 있는 leaf 항목이 나오면
    그게 실제 통계표.
    """
    params = {
        "method": "getList",
        "apiKey": API_KEY,
        "vwCd": vw_cd,
        # 개발가이드 본문엔 parentId 라고 나오지만, 실제 서버가 받는 파라미터명은
        # parentListId 다. parentId로 보내면 무시되고 항상 최상위 목록만 돌아온다.
        "parentListId": parent_id,
        "format": "json",
    }
    res = requests.get(LIST_URL, params=params, timeout=10)
    res.raise_for_status()
    return _parse_kosis_json(res.text)


def get_stat_data(org_id, tbl_id, obj_l1, itm_id, prd_se="Y", new_est_prd_cnt=3, **extra):
    """
    통계자료(Param) API - 실제 통계 수치 조회.
    obj_l1: 분류1 코드 (필수, 통계표마다 다름 - 보통 '분류값 ID' 전체 조회 시 orgId+tblId만 넣고
            objL1 없이 한번 호출해보면 사용 가능한 분류코드가 에러/샘플로 힌트가 나오는 경우가 많음)
    itm_id: 항목 코드 (필수)
    prd_se: 수록주기 (연도 Y, 반기 H, 분기 Q, 월 M 등)
    new_est_prd_cnt: 최신 시점 몇 개를 가져올지 (startPrdDe/endPrdDe 대신 사용)
    """
    params = {
        "method": "getList",
        "apiKey": API_KEY,
        "orgId": org_id,
        "tblId": tbl_id,
        "objL1": obj_l1,
        "itmId": itm_id,
        "prdSe": prd_se,
        "newEstPrdCnt": new_est_prd_cnt,
        "format": "json",
    }
    params.update(extra)
    res = requests.get(DATA_URL, params=params, timeout=10)
    res.raise_for_status()
    return _parse_kosis_json(res.text)


if __name__ == "__main__":
    print("=== 1) 통계목록 최상위 카테고리 조회 (국내통계 주제별) ===")
    top = get_list(vw_cd="MT_ZTITLE", parent_id="")
    print(top[:5], "...")

    print("\n=== 1-1) '농림'(K1) -> '농림어업조사'(K1_9) -> '농업'(F_5_1) -> '2010년~'(F_5_1_1) 로 내려가기 ===")
    print("(parentListId 로 하위 목록의 LIST_ID를 계속 넘겨주면 됨)")
    leaf = get_list(vw_cd="MT_ZTITLE", parent_id="F_5_1_1")
    # leaf 단계에 오면 LIST_ID 대신 TBL_ID/ORG_ID 가 있는 실제 통계표 목록이 나온다
    sample_tables = [t for t in leaf if t.get("TBL_NM") == "경영주 연령별 농가"]
    print(sample_tables)

    print("\n=== 2) 통계자료 조회: 경영주 연령별 농가 (orgId=101, tblId=DT_1EA1019) ===")
    # 노션 프로젝트 소개에 나온 예시와 같은 통계표(농가 고령화 검증용)
    data = get_stat_data(
        org_id="101",
        tbl_id="DT_1EA1019",
        obj_l1="ALL",   # 분류1 = 시도(전국/서울/부산...). ALL이면 전체 지역
        itm_id="ALL",   # 항목 = 경영주 연령대(T00=계, T01=20세미만, T02=20~24세 ...)
        prd_se="Y",     # 연간 자료
        new_est_prd_cnt=1,  # 최신 1개 시점(2024년)만
    )
    # 전국(C1=='000') 데이터만 추려서 확인
    nationwide = [row for row in data if row.get("C1") == "000"]
    for row in nationwide:
        print(row["ITM_NM"], "|", row["DT"], row["UNIT_NM"])
