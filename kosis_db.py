"""KOSIS 파이프라인의 메타데이터/캐시를 CSV 파일이 아니라 SQLite로 관리한다.

오늘 겪었던 문제들의 근본 원인: "상태를 CSV 파일명으로 관리"했다는 것.
  - meta-index 파일명이 겹쳐서 무역+금융 2075개 데이터가 통째로 덮어써져 사라짐
  - 새로 추가한 표의 메타가 실제로 반영됐는지 CSV를 열어봐야만 알 수 있었음 (META_NOT_LOADED)
  - 검증 결과가 캐시되지 않아 같은 claim을 매번 처음부터 다시 조회

이 모듈은 그 문제를 없앤다:
  - INSERT ... ON CONFLICT DO UPDATE 라서 절대 덮어써서 사라지지 않음 (기존 값 보존)
  - "이 표의 메타가 있는가?"를 SQL 한 줄로 즉시 확인 가능
  - 이미 검증된 (claim, 좌표) 조합은 캐시에서 즉시 반환, API 재호출 없음

기존 CSV 파이프라인(kosis_build_meta_index.py, kosis_match_claims_to_index.py,
kosis_verify_claim_values.py)의 출력 스키마를 그대로 받아들이도록 설계했다 -
그 스크립트들을 고치지 않고도, 이 모듈로 결과를 옮겨서 조회할 수 있다.
"""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

csv.field_size_limit(2 ** 31 - 1)

SCHEMA = """
CREATE TABLE IF NOT EXISTS kosis_table_catalog (
    org_id TEXT NOT NULL,
    tbl_id TEXT NOT NULL,
    tbl_name TEXT,
    category_path TEXT,
    stat_id TEXT,
    updated_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (org_id, tbl_id)
);

CREATE TABLE IF NOT EXISTS kosis_codes (
    org_id TEXT NOT NULL,
    tbl_id TEXT NOT NULL,
    obj_id TEXT,
    obj_id_sn TEXT,
    obj_nm TEXT,
    obj_nm_eng TEXT,
    itm_id TEXT,
    itm_nm TEXT,
    itm_nm_eng TEXT,
    unit_id TEXT,
    unit_nm TEXT,
    unit_eng_nm TEXT,
    up_itm_id TEXT,
    prd_se_list TEXT,
    updated_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (org_id, tbl_id, obj_id, itm_id)
);
CREATE INDEX IF NOT EXISTS idx_kosis_codes_table ON kosis_codes (org_id, tbl_id);

CREATE TABLE IF NOT EXISTS verified_mappings (
    claim_measurement_id TEXT NOT NULL,
    org_id TEXT,
    tbl_id TEXT,
    selected_itm_id TEXT,
    selected_obj_l1 TEXT,
    selected_obj_l2 TEXT,
    selected_obj_l3 TEXT,
    mapping_type TEXT,
    mapping_override_rule TEXT,
    verdict TEXT,
    verdict_code TEXT,
    verdict_reason TEXT,
    value TEXT,
    kosis_value TEXT,
    source_run TEXT,
    checked_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (claim_measurement_id, org_id, tbl_id, selected_itm_id, selected_obj_l1, selected_obj_l2, selected_obj_l3)
);
"""


def get_connection(db_path):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(conn):
    conn.executescript(SCHEMA)
    conn.commit()


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def _nz(row, *keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def upsert_table_catalog(conn, rows):
    """kosis_table_summary.csv / *_kosis_top_tables.csv 형태의 행들을 반영.
    이미 있는 표는 tbl_name/category_path만 갱신, org_id/tbl_id 조합은 유지."""
    n = 0
    for row in rows:
        org_id = _nz(row, "org_id", "ORG_ID")
        tbl_id = _nz(row, "tbl_id", "TBL_ID")
        if not org_id or not tbl_id:
            continue
        conn.execute(
            """
            INSERT INTO kosis_table_catalog (org_id, tbl_id, tbl_name, category_path, stat_id, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT (org_id, tbl_id) DO UPDATE SET
                tbl_name = excluded.tbl_name,
                category_path = excluded.category_path,
                stat_id = excluded.stat_id,
                updated_at = datetime('now')
            """,
            (
                org_id, tbl_id,
                _nz(row, "tbl_name", "TBL_NM"),
                _nz(row, "category_path"),
                _nz(row, "stat_id", "STAT_ID"),
            ),
        )
        n += 1
    conn.commit()
    return n


def upsert_meta_rows(conn, rows):
    """kosis_build_meta_index.py 의 출력(원본 getMeta 행들)을 반영.
    이미 있는 (org_id,tbl_id,obj_id,itm_id) 조합은 재삽입하지 않고 건드리지 않는다
    (오늘 겪은 '재크롤링해도 기존 데이터가 그대로 있어야 한다'는 요구사항)."""
    n = 0
    for row in rows:
        org_id = _nz(row, "org_id", "ORG_ID")
        tbl_id = _nz(row, "tbl_id", "TBL_ID")
        if not org_id or not tbl_id:
            continue
        conn.execute(
            """
            INSERT INTO kosis_codes
                (org_id, tbl_id, obj_id, obj_id_sn, obj_nm, obj_nm_eng,
                 itm_id, itm_nm, itm_nm_eng, unit_id, unit_nm, unit_eng_nm,
                 up_itm_id, prd_se_list, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT (org_id, tbl_id, obj_id, itm_id) DO NOTHING
            """,
            (
                org_id, tbl_id,
                _nz(row, "OBJ_ID"), _nz(row, "OBJ_ID_SN"), _nz(row, "OBJ_NM"), _nz(row, "OBJ_NM_ENG"),
                _nz(row, "ITM_ID"), _nz(row, "ITM_NM"), _nz(row, "ITM_NM_ENG"),
                _nz(row, "UNIT_ID"), _nz(row, "UNIT_NM"), _nz(row, "UNIT_ENG_NM"),
                _nz(row, "UP_ITM_ID"), _nz(row, "prd_se_list"),
            ),
        )
        n += 1
    conn.commit()
    return n


def has_meta_for_table(conn, org_id, tbl_id):
    """META_NOT_LOADED 를 디버깅할 때 CSV를 열어 눈으로 찾는 대신 이걸 쓴다."""
    cur = conn.execute(
        "SELECT 1 FROM kosis_codes WHERE org_id = ? AND tbl_id = ? LIMIT 1",
        (str(org_id), str(tbl_id)),
    )
    return cur.fetchone() is not None


def missing_tables(conn, candidate_pairs):
    """candidate_pairs: [(org_id, tbl_id), ...] 중 메타가 없는 것만 반환."""
    return [(org_id, tbl_id) for org_id, tbl_id in candidate_pairs if not has_meta_for_table(conn, org_id, tbl_id)]


def cache_verified_mapping(conn, row, source_run=""):
    conn.execute(
        """
        INSERT INTO verified_mappings
            (claim_measurement_id, org_id, tbl_id, selected_itm_id,
             selected_obj_l1, selected_obj_l2, selected_obj_l3,
             mapping_type, mapping_override_rule, verdict, verdict_code,
             verdict_reason, value, kosis_value, source_run, checked_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT (claim_measurement_id, org_id, tbl_id, selected_itm_id, selected_obj_l1, selected_obj_l2, selected_obj_l3)
        DO UPDATE SET
            verdict = excluded.verdict,
            verdict_code = excluded.verdict_code,
            verdict_reason = excluded.verdict_reason,
            kosis_value = excluded.kosis_value,
            source_run = excluded.source_run,
            checked_at = datetime('now')
        """,
        (
            _nz(row, "claim_measurement_id"), _nz(row, "org_id"), _nz(row, "tbl_id"),
            _nz(row, "selected_itm_id"), _nz(row, "selected_obj_l1"),
            _nz(row, "selected_obj_l2"), _nz(row, "selected_obj_l3"),
            _nz(row, "mapping_type"), _nz(row, "mapping_override_rule"),
            _nz(row, "verdict"), _nz(row, "verdict_code"), _nz(row, "verdict_reason"),
            _nz(row, "value"), _nz(row, "kosis_value"), source_run,
        ),
    )
    conn.commit()


def get_cached_verdict(conn, claim_measurement_id, org_id, tbl_id, selected_itm_id, obj_l1="", obj_l2="", obj_l3=""):
    cur = conn.execute(
        """
        SELECT * FROM verified_mappings
        WHERE claim_measurement_id = ? AND org_id = ? AND tbl_id = ?
          AND selected_itm_id = ? AND selected_obj_l1 = ? AND selected_obj_l2 = ? AND selected_obj_l3 = ?
        """,
        (str(claim_measurement_id), str(org_id), str(tbl_id), str(selected_itm_id), str(obj_l1), str(obj_l2), str(obj_l3)),
    )
    row = cur.fetchone()
    return dict(row) if row else None
