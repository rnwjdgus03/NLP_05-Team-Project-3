"""
KOSIS Open API 호출 테스트 스크립트
- 1단계: 통계목록 API 로 카테고리를 타고 내려가면서 orgId / tblId 찾기
- 2단계: 통계자료(Param) API 로 실제 수치 데이터 조회

사용법:
1) KOSIS 마이페이지 > 이용현황 에서 발급받은 인증키를 아래 API_KEY 에 넣거나
   환경변수 KOSIS_API_KEY 로 설정
2) python kosis_api_test.py
"""

import copy
import hashlib
import logging
import os
import re
import json
import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

load_dotenv()  # 같은 폴더(또는 상위 폴더)의 .env 파일을 읽어서 환경변수로 등록

API_KEY = os.environ.get("KOSIS_API_KEY")

# KOSIS 서버는 간헐적으로 연결을 끊는다(RemoteDisconnected / Read timed out).
# 재시도가 없으면 같은 입력으로 돌려도 결과가 실행마다 달라져 재현성이 깨진다.
# 실측: 검증 9건 중 3건이 네트워크 오류로 실패해 verdict 분포가 바뀌었다.
RETRY_TOTAL = 4
RETRY_BACKOFF = 1.0        # 1s → 2s → 4s → 8s (지수 백오프)
REQUEST_TIMEOUT = 20
RATE_LIMIT_COOLDOWN = 65.0
AXISLESS_OBJ_L1 = "__KOSIS_AXISLESS_TABLE__"


class KosisCoordinateError(ValueError):
    """The proposed ITEM/OBJ coordinate cannot satisfy the KOSIS API contract."""

_SENSITIVE_QUERY = re.compile(
    r"(?i)(api(?:_|-)?key|access(?:_|-)?token|token)(\s*[:=]\s*)([^&,;\s]+)"
)
_BEARER_TOKEN = re.compile(r"(?i)(authorization\s*:\s*bearer\s+)([^,;\s]+)")


def redact_credentials(value) -> str:
    """Return text safe for logs, CSVs and verdict reasons."""
    text = str(value or "")
    text = _SENSITIVE_QUERY.sub(
        lambda match: f"{match.group(1)}{match.group(2)}<redacted>", text,
    )
    text = _BEARER_TOKEN.sub(lambda match: f"{match.group(1)}<redacted>", text)
    for secret in (os.environ.get("KOSIS_API_KEY"), API_KEY):
        if secret:
            text = text.replace(str(secret), "<redacted>")
    return text


def safe_exception_message(exc: BaseException) -> str:
    """Format an exception without leaking request credentials."""
    return redact_credentials(str(exc))


class _CredentialRedactionFilter(logging.Filter):
    """Redact query credentials before urllib3 emits retry diagnostics."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:
            rendered = str(record.msg)
        record.msg = redact_credentials(rendered)
        record.args = ()
        return True


def _install_http_log_redaction() -> None:
    for logger_name in ("urllib3", "urllib3.connectionpool", "urllib3.util.retry"):
        logger = logging.getLogger(logger_name)
        if not any(isinstance(item, _CredentialRedactionFilter) for item in logger.filters):
            logger.addFilter(_CredentialRedactionFilter())


_install_http_log_redaction()


class KosisAPIError(RuntimeError):
    """KOSIS application error returned inside an HTTP-200 JSON response."""

    def __init__(self, code, message=""):
        self.code = str(code).strip()
        self.message = redact_credentials(message).strip()
        super().__init__(f"KOSIS API error {self.code}: {self.message}".rstrip())


class KosisTransportError(RuntimeError):
    """Credential-safe HTTP/network failure."""


class KosisInvalidKeyError(KosisAPIError):
    pass


class KosisExpiredKeyError(KosisAPIError):
    pass


class KosisRateLimitError(KosisAPIError):
    pass


class KosisServerError(KosisAPIError):
    pass


_ERROR_TYPES = {
    "11": KosisInvalidKeyError,
    "12": KosisExpiredKeyError,
    "40": KosisRateLimitError,
    "50": KosisServerError,
}

# KOSIS returns err=30 in the same envelope as application errors, but it
# means that the requested coordinate has no rows.  Callers need this marker
# to distinguish an empty coordinate from transport/authentication failures.
EMPTY_RESULT_ERROR_CODE = "30"


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=RETRY_TOTAL,
        connect=RETRY_TOTAL,
        read=RETRY_TOTAL,
        backoff_factor=RETRY_BACKOFF,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


SESSION = _build_session()


def _require_api_key():
    api_key = os.environ.get("KOSIS_API_KEY") or API_KEY
    if not api_key:
        raise RuntimeError(
            "KOSIS_API_KEY가 없음. .env 파일에 KOSIS_API_KEY=발급받은키 형태로 추가하세요."
        )
    return api_key

LIST_URL = "https://kosis.kr/openapi/statisticsList.do"
DATA_URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"
META_URL = "https://kosis.kr/openapi/statisticsData.do"  # method=getMeta
SEARCH_URL = "https://kosis.kr/openapi/statisticsSearch.do"

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
    _raise_for_kosis_error(parsed)
    return parsed


def _raise_for_kosis_error(rows):
    """Raise a typed exception for KOSIS' HTTP-200 error payloads."""
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        folded = {str(key).casefold(): value for key, value in row.items()}
        code = str(folded.get("err") or "").strip()
        if not code or code == EMPTY_RESULT_ERROR_CODE:
            continue
        message = folded.get("errmsg") or folded.get("err_msg") or ""
        error_type = _ERROR_TYPES.get(code, KosisAPIError)
        raise error_type(code, message)


def _has_kosis_error_marker(rows):
    return any(
        isinstance(row, dict)
        and str(
            next(
                (value for key, value in row.items() if str(key).casefold() == "err"),
                "",
            )
        ).strip()
        for row in rows or []
    )


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
        "apiKey": _require_api_key(),
        "vwCd": vw_cd,
        # 개발가이드 본문엔 parentId 라고 나오지만, 실제 서버가 받는 파라미터명은
        # parentListId 다. parentId로 보내면 무시되고 항상 최상위 목록만 돌아온다.
        "parentListId": parent_id,
        "format": "json",
    }
    return _request_json(LIST_URL, params)


def search_tables(keyword, page=1, per_page=50):
    """KOSIS 통합검색 — 키워드로 통계표를 찾는다.

    2026-08-02: 골드를 만들려는데 정답 좌표가 후보에도 메타 인덱스에도 없는 건이 나왔다.
    예) '석유화학 수출액' — 메타에서 '석유화학' 코드가 0개.
        KOSIS 품목별 무역통계는 SITC 기준이라 분류가 '선박용증기 터어빈의것' 수준으로
        잘게 쪼개져 있고, 기사가 쓰는 산업부 MTI 13대 품목 구분이 없다.

    그래서 갈라야 한다 — **KOSIS 에 표가 아예 없는가**, 아니면
    **있는데 우리 상류 표 검색이 못 찾았는가**. 전자면 커버리지 한계이고
    후자면 고칠 버그다. 이 함수는 그 판별에 쓴다.
    """
    params = {
        "method": "getList",
        "apiKey": _require_api_key(),
        "searchNm": keyword,
        # KOSIS documents startCount as a one-based page number, not a row offset.
        "startCount": max(1, int(page)),
        "resultCount": per_page,
        "sort": "RANK",
        "format": "json",
    }
    rows = _request_json(SEARCH_URL, params)
    return [row for row in rows if isinstance(row, dict)]


STAT_REQUEST_KEYS = (
    "orgId", "tblId", "itmId",
    "objL1", "objL2", "objL3", "objL4", "objL5", "objL6", "objL7", "objL8",
    "prdSe", "startPrdDe", "endPrdDe", "newEstPrdCnt",
)


def canonical_stat_request(params):
    """Return the auditable, credential-free KOSIS coordinate request."""
    return {
        key: str(params[key])
        for key in STAT_REQUEST_KEYS
        if params.get(key) not in (None, "")
    }


def stat_request_fingerprint(params):
    payload = json.dumps(
        canonical_stat_request(params), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _request_json(url, params, request_limiter=None):
    max_attempts = 2 if request_limiter is not None else 1
    for attempt in range(max_attempts):
        if request_limiter is not None:
            request_limiter.acquire()
        try:
            res = SESSION.get(url, params=params, timeout=REQUEST_TIMEOUT)
            res.raise_for_status()
        except requests.RequestException as exc:
            raise KosisTransportError(safe_exception_message(exc)) from None
        try:
            return _parse_kosis_json(res.text)
        except KosisRateLimitError:
            if request_limiter is None:
                raise
            request_limiter.cooldown(RATE_LIMIT_COOLDOWN)
            if attempt + 1 >= max_attempts:
                raise

    raise AssertionError("unreachable")


def get_stat_data(
    org_id, tbl_id, obj_l1, itm_id, prd_se="Y", new_est_prd_cnt=3,
    request_cache=None, request_limiter=None, *, axisless_table=False, **extra,
):
    """
    통계자료(Param) API - 실제 통계 수치 조회.
    obj_l1: 분류1 코드. 축 없는 표는 ``axisless_table=True``를 명시해야 한다.
    itm_id: 항목 코드 (필수)
    prd_se: 수록주기. legacy H/Y2 입력도 API에는 공식 S/F로 전송한다.
    new_est_prd_cnt: 최신 시점 몇 개를 가져올지 (startPrdDe/endPrdDe 대신 사용)
    """
    params = {
        "method": "getList",
        "apiKey": _require_api_key(),
        "orgId": org_id,
        "tblId": tbl_id,
        "itmId": itm_id,
        "prdSe": api_periodicity_code(prd_se),
        "format": "json",
    }
    # KOSIS documents newEstPrdCnt as an alternative to an explicit period
    # range. Sending both can make the API ignore the requested range or
    # return an empty response, so use exactly one mode per request.
    has_explicit_range = bool(extra.get("startPrdDe") or extra.get("endPrdDe"))
    if not has_explicit_range:
        params["newEstPrdCnt"] = new_est_prd_cnt
    if obj_l1 == AXISLESS_OBJ_L1:
        obj_l1 = None
    if obj_l1 not in (None, ""):
        params["objL1"] = obj_l1
    else:
        raise KosisCoordinateError(
            "objL1 is required by the KOSIS parameter API; "
            "axis-less tables must be resolved to an official total code before querying"
        )
    for level in range(2, 9):
        py_key = f"obj_l{level}"
        api_key = f"objL{level}"
        if py_key in extra and api_key not in extra:
            extra[api_key] = extra.pop(py_key)
    params.update(extra)
    cache_key = stat_request_fingerprint(params)
    if request_cache is not None and cache_key in request_cache:
        return copy.deepcopy(request_cache[cache_key])
    parsed = _request_json(DATA_URL, params, request_limiter=request_limiter)
    if request_cache is not None and not _has_kosis_error_marker(parsed):
        request_cache[cache_key] = copy.deepcopy(parsed)
    return parsed


def api_periodicity_code(value) -> str:
    """Map accepted legacy labels to official KOSIS request codes."""
    raw = str(value or "").strip().upper()
    aliases = {
        "H": "S", "S": "S",
        "Y2": "F", "Y3": "F", "Y4": "F", "Y5": "F", "Y10": "F",
        "F": "F",
    }
    return aliases.get(raw, raw)


def get_meta(org_id, tbl_id, meta_type="ITM", request_limiter=None):
    """
    통계표설명(메타정보) API - 실제 데이터를 안 당겨도 분류/항목 코드 전체를 알 수 있음.
    meta_type="TBL" -> 표 이름만 (기본정보)
    meta_type="ITM" -> 분류(objL1 등) 코드 전체 + 항목(itmId) 코드 전체를 한번에 줌
                       응답 안에서 OBJ_ID=="ITEM" 인 행이 "항목"(itmId 후보),
                       그 외 OBJ_ID(A, B ...) 인 행이 "분류"(objL1, objL2 ... 후보) 코드임
    """
    params = {
        "method": "getMeta",
        "type": meta_type,
        "apiKey": _require_api_key(),
        "orgId": org_id,
        "tblId": tbl_id,
        "format": "json",
    }
    return _request_json(META_URL, params, request_limiter=request_limiter)


def summarize_meta(org_id, tbl_id):
    """
    get_meta(type=ITM) 결과를 "분류축(objL1 등)"과 "항목(itmId)"으로 나눠서 요약.
    """
    rows = get_meta(org_id, tbl_id, meta_type="ITM")
    items = [r for r in rows if r.get("OBJ_ID") == "ITEM"]
    classifications = {}
    for r in rows:
        if r.get("OBJ_ID") == "ITEM":
            continue
        key = (r.get("OBJ_ID"), r.get("OBJ_NM"))
        classifications.setdefault(key, []).append((r.get("ITM_ID"), r.get("ITM_NM")))
    return {
        "items": [(r.get("ITM_ID"), r.get("ITM_NM")) for r in items],
        "classifications": classifications,  # {(objId, 분류축이름): [(코드, 이름), ...]}
    }


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
