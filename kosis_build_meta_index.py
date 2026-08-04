#!/usr/bin/env python3
"""
KOSIS 메타 인덱스 생성기.

입력
- 통계표 인덱스 CSV: org_id/tbl_id/tbl_name/category_path

출력
- kosis_meta_index.csv: 표별 분류축/항목 코드 long format

왜 필요한가
- tbl_id만으로는 claim 검증이 불가능하다.
- 실제 검증에는 obj_l1/obj_l2/itm_id/unit까지 필요하므로 getMeta 결과를
  검색 가능한 long table로 만들어둔다.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from kosis_api_test import (  # noqa: E402
    META_URL,
    REQUEST_TIMEOUT,
    SESSION,
    _parse_kosis_json,
    _require_api_key,
    get_meta,
)


DEFAULT_TABLE_INDEX = PROJECT_DIR / "data/claims/kosis_table_index.csv"
DEFAULT_OUT = PROJECT_DIR / "data/claims/kosis_meta_index.csv"

META_FIELDS = [
    "org_id", "tbl_id", "tbl_name", "category_path",
    "axis_id", "axis_name", "axis_order",
    "code_id", "code_name", "parent_code_id",
    "is_item", "unit_id", "unit_name", "unit_eng_name",
    "raw_response_rows", "parsed_meta_rows", "item_rows", "obj_rows", "unit_rows", "meta_status",
]

FAILURE_FIELDS = [
    "org_id", "tbl_id", "tbl_name",
    "failure_code", "failure_message", "http_status", "response_type",
    "response_row_count", "retryable",
]


class MetaBuildFailure(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: str = "",
        response_type: str = "",
        response_row_count: int = 0,
        retryable: str = "N",
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.response_type = response_type
        self.response_row_count = response_row_count
        self.retryable = retryable


def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def append_csv(path: Path, rows, write_header=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if write_header else "a"
    with path.open(mode, encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=META_FIELDS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def append_failure_csv(path: Path, rows, write_header=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if write_header else "a"
    with path.open(mode, encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FAILURE_FIELDS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def norm_table_row(row):
    return {
        "org_id": row.get("org_id") or row.get("ORG_ID") or row.get("OrgId") or "",
        "tbl_id": row.get("tbl_id") or row.get("TBL_ID") or row.get("TblId") or "",
        "tbl_name": row.get("tbl_name") or row.get("TBL_NM") or row.get("TBL_NM_KOR") or "",
        "category_path": row.get("category_path") or row.get("path") or "",
    }


def _is_kosis_error(row):
    if not isinstance(row, dict):
        return False
    return any(key in row for key in ("err", "ERR", "error", "ERROR", "errMsg", "ERR_MSG"))


def _error_code(row):
    return str(row.get("err") or row.get("ERR") or row.get("error") or row.get("ERROR") or "").strip()


def _error_message(row):
    return str(row.get("errMsg") or row.get("ERR_MSG") or row.get("message") or row.get("msg") or row).strip()


def classify_kosis_error(row):
    code = _error_code(row)
    message = _error_message(row)
    lower = message.lower()
    if code in {"20", "30"} and ("인증" in message or "key" in lower or "api" in lower):
        return "AUTH_ERROR", message
    if "인증" in message or "api key" in lower or "apikey" in lower:
        return "AUTH_ERROR", message
    if "잘못" in message or "요청" in message:
        return "HTTP_ERROR", message
    return "RESPONSE_SCHEMA_MISMATCH", message


def convert_meta_rows(table, meta_rows):
    if meta_rows is None:
        raise MetaBuildFailure("EMPTY_META_RESPONSE", "getMeta 응답이 None입니다.")
    if not isinstance(meta_rows, list):
        raise MetaBuildFailure(
            "RESPONSE_SCHEMA_MISMATCH",
            f"getMeta 응답이 list가 아닙니다: {type(meta_rows).__name__}",
            response_type=type(meta_rows).__name__,
        )
    raw_response_rows = len(meta_rows)
    if raw_response_rows == 0:
        raise MetaBuildFailure("EMPTY_META_RESPONSE", "getMeta 응답이 빈 배열입니다.", response_type="list")
    if len(meta_rows) == 1 and _is_kosis_error(meta_rows[0]):
        code, message = classify_kosis_error(meta_rows[0])
        raise MetaBuildFailure(code, message, response_type="error_object", response_row_count=1)

    out = []
    for r in meta_rows:
        if not isinstance(r, dict):
            raise MetaBuildFailure(
                "RESPONSE_SCHEMA_MISMATCH",
                f"메타 행이 object가 아닙니다: {type(r).__name__}",
                response_type=type(r).__name__,
                response_row_count=raw_response_rows,
            )
        axis_id = r.get("OBJ_ID", "")
        is_item = axis_id == "ITEM"
        code_id = r.get("ITM_ID", "")
        code_name = r.get("ITM_NM", "")
        if not str(code_id).strip():
            continue
        out.append({
            "org_id": table["org_id"],
            "tbl_id": table["tbl_id"],
            "tbl_name": table["tbl_name"],
            "category_path": table["category_path"],
            "axis_id": axis_id,
            "axis_name": r.get("OBJ_NM", ""),
            "axis_order": r.get("OBJ_ID_SN", ""),
            "code_id": code_id,
            "code_name": code_name,
            "parent_code_id": r.get("UP_ITM_ID", ""),
            "is_item": "Y" if is_item else "N",
            "unit_id": r.get("UNIT_ID", ""),
            "unit_name": r.get("UNIT_NM", ""),
            "unit_eng_name": r.get("UNIT_ENG_NM", ""),
        })
    if not out:
        raise MetaBuildFailure(
            "RESPONSE_SCHEMA_MISMATCH",
            "getMeta 응답은 있었지만 ITM_ID/code_id가 있는 행이 없습니다.",
            response_type="list",
            response_row_count=raw_response_rows,
        )
    item_rows = sum(1 for row in out if row["is_item"] == "Y")
    obj_rows = len(out) - item_rows
    unit_rows = sum(1 for row in out if str(row.get("unit_name", "")).strip())
    meta_status = "SUCCESS" if item_rows > 0 and obj_rows > 0 else "PARTIAL"
    for row in out:
        row.update({
            "raw_response_rows": raw_response_rows,
            "parsed_meta_rows": len(out),
            "item_rows": item_rows,
            "obj_rows": obj_rows,
            "unit_rows": unit_rows,
            "meta_status": meta_status,
        })
    return out


def failure_row(table, failure: MetaBuildFailure):
    return {
        "org_id": table["org_id"],
        "tbl_id": table["tbl_id"],
        "tbl_name": table["tbl_name"],
        "failure_code": failure.code,
        "failure_message": failure.message,
        "http_status": failure.http_status,
        "response_type": failure.response_type,
        "response_row_count": failure.response_row_count,
        "retryable": failure.retryable,
    }


def load_done(path: Path):
    if not path.exists():
        return set()
    done = set()
    with path.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("org_id") and r.get("tbl_id"):
                done.add((r["org_id"], r["tbl_id"]))
    return done


def masked_url(url: str, params: dict[str, str]) -> str:
    safe = dict(params)
    if "apiKey" in safe:
        safe["apiKey"] = "***"
    return f"{url}?{urlencode(safe)}"


def fetch_meta_raw(org_id: str, tbl_id: str, meta_type: str = "ITM"):
    api_key = _require_api_key()
    params = {
        "method": "getMeta",
        "type": meta_type,
        "apiKey": api_key,
        "orgId": org_id,
        "tblId": tbl_id,
        "format": "json",
    }
    res = SESSION.get(META_URL, params=params, timeout=REQUEST_TIMEOUT)
    body = res.text
    parsed = None
    parse_error = ""
    try:
        parsed = _parse_kosis_json(body)
    except Exception as exc:
        parse_error = f"{type(exc).__name__}: {exc}"
    top_type = type(parsed).__name__ if parsed is not None else "unparsed"
    top_keys = []
    if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
        top_keys = sorted(parsed[0].keys())
    elif isinstance(parsed, dict):
        top_keys = sorted(parsed.keys())
    err_code = ""
    err_msg = ""
    row_count = len(parsed) if isinstance(parsed, list) else (1 if isinstance(parsed, dict) else 0)
    if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict) and _is_kosis_error(parsed[0]):
        err_code = _error_code(parsed[0])
        err_msg = _error_message(parsed[0])
    return {
        "endpoint": META_URL,
        "masked_url": masked_url(META_URL, params),
        "param_names": sorted(params.keys()),
        "org_id": org_id,
        "tbl_id": tbl_id,
        "meta_type": meta_type,
        "http_status": res.status_code,
        "content_type": res.headers.get("content-type", ""),
        "top_level_type": top_type,
        "top_level_keys": top_keys,
        "response_row_count": row_count,
        "kosis_error_code": err_code,
        "kosis_error_message": err_msg,
        "parse_error": parse_error,
        "parsed": parsed,
        "text_prefix": body[:500],
    }


def run_debug_tables(table_rows, debug_tables, debug_dir: Path):
    debug_dir.mkdir(parents=True, exist_ok=True)
    table_by_id = {row["tbl_id"]: row for row in table_rows}
    summary = {
        "api_key_present": "Y" if os.environ.get("KOSIS_API_KEY") else "N",
        "api_key_length": len(os.environ.get("KOSIS_API_KEY") or ""),
        "tables": [],
    }
    for tbl_id in debug_tables:
        table = table_by_id.get(tbl_id, {"org_id": "", "tbl_id": tbl_id, "tbl_name": "", "category_path": ""})
        try:
            raw = fetch_meta_raw(table["org_id"], table["tbl_id"], "ITM")
        except Exception as exc:
            raw = {
                "endpoint": META_URL,
                "param_names": ["apiKey", "format", "method", "orgId", "tblId", "type"],
                "org_id": table["org_id"],
                "tbl_id": table["tbl_id"],
                "meta_type": "ITM",
                "http_status": "",
                "content_type": "",
                "top_level_type": "",
                "top_level_keys": [],
                "response_row_count": 0,
                "kosis_error_code": "KOSIS_API_KEY_MISSING" if "KOSIS_API_KEY" in str(exc) else type(exc).__name__,
                "kosis_error_message": str(exc),
                "parse_error": "",
                "parsed": None,
                "text_prefix": "",
            }
        raw_path = debug_dir / f"{table['tbl_id']}_raw.json"
        raw_path.write_text(json.dumps({k: v for k, v in raw.items() if k != "masked_url"}, ensure_ascii=False, indent=2), encoding="utf-8")
        summary["tables"].append({k: v for k, v in raw.items() if k not in {"parsed", "text_prefix"}})
    (debug_dir / "meta_debug_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--table-index", default=str(DEFAULT_TABLE_INDEX))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--limit", type=int, default=0, help="테스트용 처리 표 수. 0이면 전체")
    parser.add_argument("--delay", type=float, default=0.12)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--keyword", action="append", default=[], help="tbl_name/category_path 필터. 여러 번 가능")
    parser.add_argument("--failure-out", default="", help="메타 수집 실패 CSV. 기본은 <out>_failures.csv")
    parser.add_argument("--debug-dir", default="", help="대표 표 raw 응답 저장 디렉터리")
    parser.add_argument("--debug-table", action="append", default=[], help="raw 응답을 저장할 tbl_id. 여러 번 가능")
    args = parser.parse_args()

    table_rows = [norm_table_row(r) for r in read_csv(Path(args.table_index).expanduser())]
    table_rows = [r for r in table_rows if r["org_id"] and r["tbl_id"]]
    if args.keyword:
        kws = args.keyword
        table_rows = [
            r for r in table_rows
            if any(k in f"{r['tbl_name']} {r['category_path']}" for k in kws)
        ]

    out = Path(args.out).expanduser()
    failure_out = Path(args.failure_out).expanduser() if args.failure_out else out.with_name(out.stem + "_failures.csv")
    done = load_done(out) if args.resume else set()
    todo = [r for r in table_rows if (r["org_id"], r["tbl_id"]) not in done]
    if args.limit:
        todo = todo[:args.limit]

    append_csv(out, [], write_header=not args.resume or not out.exists())
    append_failure_csv(failure_out, [], write_header=not args.resume or not failure_out.exists())
    if args.debug_table:
        debug_dir = Path(args.debug_dir).expanduser() if args.debug_dir else out.parent / "kosis_meta_debug"
        summary = run_debug_tables(table_rows, args.debug_table, debug_dir)
        print(json.dumps({k: v for k, v in summary.items() if k != "tables"}, ensure_ascii=False))
        for row in summary["tables"]:
            print(json.dumps(row, ensure_ascii=False))

    ok = 0
    fail = 0
    total_parsed = 0
    total_item = 0
    total_obj = 0
    for i, table in enumerate(todo, 1):
        try:
            meta = get_meta(table["org_id"], table["tbl_id"], "ITM")
            rows = convert_meta_rows(table, meta)
            append_csv(out, rows)
            ok += 1
            total_parsed += len(rows)
            total_item += sum(1 for row in rows if row["is_item"] == "Y")
            total_obj += sum(1 for row in rows if row["is_item"] != "Y")
            print(f"\r{i}/{len(todo)} ok={ok} fail={fail} {table['tbl_id']} {table['tbl_name'][:40]}", end="", flush=True)
        except MetaBuildFailure as exc:
            fail += 1
            append_failure_csv(failure_out, [failure_row(table, exc)])
            print(f"\nFAIL {table['org_id']}/{table['tbl_id']} {table['tbl_name']}: {exc.code} {exc.message}", flush=True)
        except Exception as exc:
            fail += 1
            if "KOSIS_API_KEY" in str(exc):
                code = "KOSIS_API_KEY_MISSING"
            elif isinstance(exc, json.JSONDecodeError):
                code = "INVALID_JSON"
            else:
                code = type(exc).__name__
            append_failure_csv(failure_out, [failure_row(table, MetaBuildFailure(code, str(exc), retryable="Y"))])
            print(f"\nFAIL {table['org_id']}/{table['tbl_id']} {table['tbl_name']}: {exc}", flush=True)
        time.sleep(args.delay)
    print()
    print(f"saved={out} failures={failure_out} tables_ok={ok} tables_fail={fail} parsed_meta_rows={total_parsed} item_rows={total_item} obj_rows={total_obj}")
    if total_parsed == 0 or total_item == 0 or ok == 0:
        raise SystemExit(
            "KOSIS 메타데이터에서 ITEM 행을 한 건도 수집하지 못했습니다. "
            "후속 ITEM/OBJ 매핑과 API 검증을 중단합니다."
        )


if __name__ == "__main__":
    main()
