import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import kosis_build_meta_index as build


TABLE = {"org_id": "360", "tbl_id": "DT_TEST", "tbl_name": "테스트표", "category_path": ""}


class KosisBuildMetaIndexTests(unittest.TestCase):
    def test_normal_item_response_is_written_as_item(self):
        rows = build.convert_meta_rows(TABLE, [
            {"OBJ_ID": "ITEM", "OBJ_NM": "항목", "OBJ_ID_SN": "", "ITM_ID": "T1", "ITM_NM": "수출액", "UNIT_NM": "천달러"}
        ])
        self.assertEqual(rows[0]["code_id"], "T1")
        self.assertEqual(rows[0]["code_name"], "수출액")
        self.assertEqual(rows[0]["is_item"], "Y")
        self.assertEqual(rows[0]["unit_name"], "천달러")
        self.assertEqual(rows[0]["meta_status"], "PARTIAL")

    def test_normal_obj_response_is_written_as_obj(self):
        rows = build.convert_meta_rows(TABLE, [
            {"OBJ_ID": "A", "OBJ_NM": "품목별", "OBJ_ID_SN": "1", "ITM_ID": "A01", "ITM_NM": "반도체"}
        ])
        self.assertEqual(rows[0]["axis_id"], "A")
        self.assertEqual(rows[0]["axis_order"], "1")
        self.assertEqual(rows[0]["code_id"], "A01")
        self.assertEqual(rows[0]["is_item"], "N")

    def test_auth_error_is_not_converted_to_normal_meta(self):
        with self.assertRaises(build.MetaBuildFailure) as cm:
            build.convert_meta_rows(TABLE, [{"err": "20", "errMsg": "인증키 오류"}])
        self.assertEqual(cm.exception.code, "AUTH_ERROR")

    def test_empty_response_is_failure(self):
        with self.assertRaises(build.MetaBuildFailure) as cm:
            build.convert_meta_rows(TABLE, [])
        self.assertEqual(cm.exception.code, "EMPTY_META_RESPONSE")

    def test_unexpected_json_schema_is_failure(self):
        with self.assertRaises(build.MetaBuildFailure) as cm:
            build.convert_meta_rows(TABLE, [{"foo": "bar"}])
        self.assertEqual(cm.exception.code, "RESPONSE_SCHEMA_MISMATCH")

    def test_main_fail_fast_when_all_items_are_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            table_index = Path(tmp) / "tables.csv"
            out = Path(tmp) / "meta.csv"
            failures = Path(tmp) / "meta_failures.csv"
            with table_index.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["org_id", "tbl_id", "tbl_name", "category_path"])
                writer.writeheader()
                writer.writerow(TABLE)
            argv = [
                "kosis_build_meta_index.py",
                "--table-index", str(table_index),
                "--out", str(out),
                "--failure-out", str(failures),
                "--delay", "0",
            ]
            with patch("sys.argv", argv), patch("kosis_build_meta_index.get_meta", return_value=[]):
                with self.assertRaises(SystemExit) as cm:
                    build.main()
            self.assertIn("ITEM 행을 한 건도", str(cm.exception))
            with failures.open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]["failure_code"], "EMPTY_META_RESPONSE")


if __name__ == "__main__":
    unittest.main()
