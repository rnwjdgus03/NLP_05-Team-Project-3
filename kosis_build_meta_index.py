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
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from kosis_api_test import (  # noqa: E402
    KosisExpiredKeyError,
    KosisInvalidKeyError,
    KosisRateLimitError,
    KosisServerError,
    get_meta,
    safe_exception_message,
)
from kosis_meta_coordinates import normalize_periodicity  # noqa: E402
from kosis_metadata_store import SQLiteKosisRequestLimiter  # noqa: E402


DEFAULT_TABLE_INDEX = PROJECT_DIR / "data/claims/kosis_table_index.csv"
DEFAULT_OUT = PROJECT_DIR / "data/claims/kosis_meta_index.csv"
MAX_WORKERS = 8
DEFAULT_DELAY = 0.5
RATE_LIMIT_COOLDOWN = 65.0


def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


# extrasaction="ignore" 라서 여기 없는 키는 **조용히 버려진다.**
# 2026-08-04: convert_meta_rows 에 prd_se_list 를 넣었는데 이 목록을 안 고쳐서
# 520개 표를 다 수집하고도 컬럼이 없었다. 사전만 검사하는 테스트는 이걸 못 잡는다.
FIELDS = [
    "org_id", "tbl_id", "tbl_name", "category_path",
    "axis_id", "axis_name", "axis_order",
    "code_id", "code_name", "parent_code_id",
    "is_item", "unit_id", "unit_name", "unit_eng_name",
    "prd_se_list", "prd_ranges",
]

FAILURE_FIELDS = [
    "org_id", "tbl_id", "tbl_name", "category_path",
    "stage", "attempts", "error_type", "error",
]


def append_csv(path: Path, rows, write_header=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = FIELDS
    mode = "w" if write_header else "a"
    with path.open(mode, encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def write_failures(path: Path, rows):
    """현재 실행에서 끝내 실패한 표만 결정적인 입력 순서로 기록한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FAILURE_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def norm_table_row(row):
    return {
        "org_id": row.get("org_id") or row.get("ORG_ID") or row.get("OrgId") or "",
        "tbl_id": row.get("tbl_id") or row.get("TBL_ID") or row.get("TblId") or "",
        "tbl_name": row.get("tbl_name") or row.get("TBL_NM") or row.get("TBL_NM_KOR") or "",
        "category_path": row.get("category_path") or row.get("path") or "",
    }


def periodicity_from_rows(rows):
    codes, spans = [], []
    for row in rows or []:
        code = normalize_periodicity(row.get("PRD_SE"))
        if code and code not in codes:
            codes.append(code)
        start = str(row.get("STRT_PRD_DE") or "").strip()
        end = str(row.get("END_PRD_DE") or "").strip()
        if start or end:
            spans.append(f"{code}:{start}~{end}")
    return "|".join(codes), ";".join(spans)


def collect_periodicity(org_id, tbl_id):
    """표가 어떤 주기를 제공하는가 (2026-08-04 추가).

    이걸 몰라서 **분기 주장에 연간을 물어봤다.** 홀드아웃1 의 거짓 불일치 하나가
    그 때문이다 — '소매판매액지수 2022년 2분기 -0.2%' 를 2022년 연간 +5.88% 와 대조했다.

    KOSIS 는 없는 주기를 물어도 **에러를 내지 않는다.** 실측(DT_127005_005):
    prdSe=M 으로 물으면 PRD_DE=['2019'..'2024'] 인 연간 행이 그대로 온다.
    그래서 조회 전에 표가 무엇을 줄 수 있는지 알아야 한다.

    반환: ('Y|Q|M', '1970~2025') 형태. 실패하면 ('', '') — 수집을 멈추지 않는다.
    """
    try:
        rows = get_meta(org_id, tbl_id, "PRD")
    except Exception:
        return "", ""
    return periodicity_from_rows(rows)


def convert_meta_rows(table, meta_rows):
    out = []
    for r in meta_rows:
        axis_id = r.get("OBJ_ID", "")
        is_item = axis_id == "ITEM"
        out.append({
            "org_id": table["org_id"],
            "tbl_id": table["tbl_id"],
            "tbl_name": table["tbl_name"],
            "category_path": table["category_path"],
            "axis_id": axis_id,
            "axis_name": r.get("OBJ_NM", ""),
            "axis_order": r.get("OBJ_ID_SN", ""),
            "code_id": r.get("ITM_ID", ""),
            "code_name": r.get("ITM_NM", ""),
            "parent_code_id": r.get("UP_ITM_ID", ""),
            "is_item": "Y" if is_item else "N",
            "unit_id": r.get("UNIT_ID", ""),
            "unit_name": r.get("UNIT_NM", ""),
            "unit_eng_name": r.get("UNIT_ENG_NM", ""),
            # 표 단위 값이라 행마다 같다. 하류가 표를 고를 때 이것만 보면 되도록 붙여둔다.
            "prd_se_list": table.get("prd_se_list", ""),
            "prd_ranges": table.get("prd_ranges", ""),
        })
    return out


def load_done(path: Path):
    if not path.exists():
        return set()
    done = set()
    with path.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            # A complete ITM response always has at least one ITEM row. Merely
            # seeing an OBJ row is not enough to prove the table finished.
            if (
                r.get("org_id") and r.get("tbl_id") and r.get("code_id")
                and r.get("axis_id") and r.get("is_item") == "Y"
            ):
                done.add((r["org_id"], r["tbl_id"]))
    return done


def repair_resume_output(path: Path):
    """Remove every row for a table containing a corrupt component row."""
    if not path.exists():
        return 0
    rows = read_csv(path)
    corrupt_tables = set()
    for row in rows:
        key = (
            str(row.get("org_id") or "").strip(),
            str(row.get("tbl_id") or "").strip(),
        )
        if not all((*key, str(row.get("axis_id") or "").strip(),
                    str(row.get("code_id") or "").strip())):
            corrupt_tables.add(key)
    valid = []
    for row in rows:
        key = (
            str(row.get("org_id") or "").strip(),
            str(row.get("tbl_id") or "").strip(),
        )
        if key not in corrupt_tables:
            valid.append(row)
    removed = len(rows) - len(valid)
    if removed:
        append_csv(path, valid, write_header=True)
    return removed


class RequestRateLimiter:
    """모든 워커의 KOSIS 요청 시작 간격을 전역적으로 제한한다."""

    def __init__(self, delay, *, clock=time.monotonic, sleeper=time.sleep):
        self.delay = max(0.0, float(delay))
        self._clock = clock
        self._sleep = sleeper
        self._lock = threading.Lock()
        self._next_request_at = 0.0
        self._cooldown_until = 0.0

    def cooldown(self, seconds):
        """Extend one shared cooldown observed by every worker."""
        with self._lock:
            self._cooldown_until = max(
                self._cooldown_until,
                self._clock() + max(0.0, float(seconds)),
            )

    def wait(self):
        if self.delay <= 0:
            with self._lock:
                wait_for = max(0.0, self._cooldown_until - self._clock())
            if wait_for:
                self._sleep(wait_for)
            return
        with self._lock:
            now = self._clock()
            allowed_at = max(self._next_request_at, self._cooldown_until)
            wait_for = max(0.0, allowed_at - now)
            self._next_request_at = max(now, allowed_at) + self.delay
        if wait_for:
            self._sleep(wait_for)

    def sleep(self, seconds):
        self._sleep(max(0.0, float(seconds)))


class MetaRequestError(RuntimeError):
    def __init__(self, stage, attempts, cause):
        super().__init__(str(cause))
        self.stage = stage
        self.attempts = attempts
        self.cause = cause


def validate_meta_response(rows, meta_type):
    """Reject KOSIS JSON error objects even when the HTTP response is 200."""
    rows = rows or []
    if meta_type == "ITM":
        if not rows:
            raise RuntimeError("invalid or empty ITM metadata response")
        for row in rows:
            if not isinstance(row, dict):
                raise RuntimeError("invalid ITM metadata row: expected object")
            axis_id = row.get("OBJ_ID")
            code_id = row.get("ITM_ID")
            if not str(axis_id or "").strip() or not str(code_id or "").strip():
                raise RuntimeError("invalid ITM metadata row: missing OBJ_ID or ITM_ID")
    return rows


def request_meta_with_retries(table, meta_type, retries, rate_limiter):
    """한 API 요청을 최대 ``retries + 1``번 수행한다."""
    attempts = max(0, int(retries)) + 1
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            if isinstance(rate_limiter, SQLiteKosisRequestLimiter):
                rows = get_meta(
                    table["org_id"], table["tbl_id"], meta_type,
                    request_limiter=rate_limiter,
                )
            else:
                rate_limiter.wait()
                rows = get_meta(table["org_id"], table["tbl_id"], meta_type)
            return validate_meta_response(rows, meta_type)
        except (KosisInvalidKeyError, KosisExpiredKeyError) as exc:
            raise MetaRequestError(meta_type, attempt, exc) from exc
        except KosisRateLimitError as exc:
            last_error = exc
            if not isinstance(rate_limiter, SQLiteKosisRequestLimiter):
                rate_limiter.cooldown(RATE_LIMIT_COOLDOWN)
            if attempt < attempts:
                continue
        except KosisServerError as exc:
            last_error = exc
        except Exception as exc:
            last_error = exc
        if attempt < attempts:
            # 전역 요청 간격과 별도로 실패한 표에만 짧은 지수 백오프를 준다.
            delay = getattr(rate_limiter, "delay", getattr(rate_limiter, "interval", 0.0))
            rate_limiter.sleep(max(delay, 0.1) * (2 ** (attempt - 1)))
    raise MetaRequestError(meta_type, attempts, last_error)


def fetch_table(table, with_periodicity, retries, rate_limiter):
    """워커에서 API만 호출하고 CSV에는 손대지 않는다."""
    table = dict(table)
    try:
        if with_periodicity:
            prd_rows = request_meta_with_retries(table, "PRD", retries, rate_limiter)
            table["prd_se_list"], table["prd_ranges"] = periodicity_from_rows(prd_rows)
        meta_rows = request_meta_with_retries(table, "ITM", retries, rate_limiter)
        return {"table": table, "rows": convert_meta_rows(table, meta_rows), "failure": None}
    except MetaRequestError as exc:
        failure = {
            **table,
            "stage": exc.stage,
            "attempts": exc.attempts,
            "error_type": type(exc.cause).__name__,
            "error": safe_exception_message(exc.cause),
        }
        return {"table": table, "rows": [], "failure": failure}
    except Exception as exc:
        failure = {
            **table,
            "stage": "CONVERT",
            "attempts": 0,
            "error_type": type(exc).__name__,
            "error": safe_exception_message(exc),
        }
        return {"table": table, "rows": [], "failure": failure}


def collect_tables(todo, out, failures_out, *, workers=1, retries=2,
                   delay=DEFAULT_DELAY,
                   with_periodicity=False, sqlite_rate_db=None):
    """병렬로 조회하되 결과 파일은 입력 순서대로 메인 스레드에서만 쓴다."""
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"workers must be between 1 and {MAX_WORKERS}")

    limiter = (
        SQLiteKosisRequestLimiter(sqlite_rate_db, interval=delay)
        if sqlite_rate_db else RequestRateLimiter(delay)
    )
    failures = []
    ok = 0
    fail = 0
    total = len(todo)

    # 전체 표를 Future로 만들지 않도록 작은 창 단위로 제출한다.
    window_size = max(workers, workers * 4)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for start in range(0, total, window_size):
            window = todo[start:start + window_size]
            futures = [
                executor.submit(fetch_table, table, with_periodicity, retries, limiter)
                for table in window
            ]
            # future.result()를 제출 순서로 읽어 출력 순서를 결정적으로 유지한다.
            for offset, future in enumerate(futures, start + 1):
                result = future.result()
                table = result["table"]
                if result["failure"] is None:
                    append_csv(out, result["rows"])
                    ok += 1
                else:
                    fail += 1
                    failures.append(result["failure"])
                    error = result["failure"]["error"]
                    print(f"\nFAIL {table['org_id']}/{table['tbl_id']} {table['tbl_name']}: {error}", flush=True)
                print(
                    f"\r{offset}/{total} ok={ok} fail={fail} "
                    f"{table['tbl_id']} {table['tbl_name'][:40]}",
                    end="", flush=True,
                )

    write_failures(failures_out, failures)
    return ok, fail


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--table-index", default=str(DEFAULT_TABLE_INDEX))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--limit", type=int, default=0, help="테스트용 처리 표 수. 0이면 전체")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    parser.add_argument(
        "--sqlite-rate-db", default="",
        help="프로세스 간 KOSIS 요청 간격/cooldown을 공유할 SQLite 파일",
    )
    parser.add_argument("--workers", type=int, default=1,
                        help="병렬 API 워커 수 (기본 1, 권장 4, 최대 8)")
    parser.add_argument("--retries", type=int, default=2,
                        help="요청별 추가 재시도 횟수")
    parser.add_argument("--failures-out", default="",
                        help="최종 실패 표 CSV (기본: OUT 이름 뒤에 _failures)")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--with-periodicity", action="store_true",
                        help="표별 수록 주기를 함께 수집한다 (표당 API 1회 추가)")
    parser.add_argument("--keyword", action="append", default=[], help="tbl_name/category_path 필터. 여러 번 가능")
    args = parser.parse_args()
    if not 1 <= args.workers <= MAX_WORKERS:
        parser.error(f"--workers must be between 1 and {MAX_WORKERS}")
    if args.retries < 0:
        parser.error("--retries must be non-negative")
    if args.delay < 0:
        parser.error("--delay must be non-negative")

    table_rows = [norm_table_row(r) for r in read_csv(Path(args.table_index).expanduser())]
    table_rows = [r for r in table_rows if r["org_id"] and r["tbl_id"]]
    if args.keyword:
        kws = args.keyword
        table_rows = [
            r for r in table_rows
            if any(k in f"{r['tbl_name']} {r['category_path']}" for k in kws)
        ]

    out = Path(args.out).expanduser()
    if args.resume:
        repaired = repair_resume_output(out)
        if repaired:
            print(f"repaired_resume_rows={repaired}", flush=True)
    done = load_done(out) if args.resume else set()
    todo = [r for r in table_rows if (r["org_id"], r["tbl_id"]) not in done]
    if args.limit:
        todo = todo[:args.limit]

    append_csv(out, [], write_header=not args.resume or not out.exists())
    failures_out = Path(args.failures_out).expanduser() if args.failures_out else out.with_name(
        f"{out.stem}_failures.csv"
    )
    ok, fail = collect_tables(
        todo,
        out,
        failures_out,
        workers=args.workers,
        retries=args.retries,
        delay=args.delay,
        with_periodicity=args.with_periodicity,
        sqlite_rate_db=args.sqlite_rate_db or None,
    )
    print()
    print(f"saved={out} failures={failures_out} tables_ok={ok} tables_fail={fail}")


if __name__ == "__main__":
    main()
