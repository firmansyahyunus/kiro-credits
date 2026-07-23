import contextlib
import csv
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import kcredits  # noqa: E402


FIXTURES = Path(__file__).resolve().parent / "fixtures"


class KcreditsTests(unittest.TestCase):
    def setUp(self):
        self.original = {
            "V3_SESSIONS_DIR": kcredits.V3_SESSIONS_DIR,
            "CLASSIC_DB": kcredits.CLASSIC_DB,
            "DATA_DIR": kcredits.DATA_DIR,
            "CSV_PATH": kcredits.CSV_PATH,
            "LEGACY_CSV_PATH": kcredits.LEGACY_CSV_PATH,
        }

    def tearDown(self):
        for key, value in self.original.items():
            setattr(kcredits, key, value)

    def use_v3_fixture(self):
        kcredits.V3_SESSIONS_DIR = FIXTURES / "v3" / "sessions"

    def test_v3_turns_read_real_and_synthetic_event_ids(self):
        self.use_v3_fixture()

        turns = list(kcredits.iter_v3_turns())

        self.assertEqual(2, len(turns))
        self.assertEqual([1.25, 2.5], [turn["credits"] for turn in turns])
        self.assertEqual("event-001#0", turns[0]["event_id"])
        self.assertTrue(turns[1]["event_id"].startswith("synthetic-"))
        self.assertEqual("C:\\work\\example-project", turns[0]["project"])

    def test_snapshot_uses_private_data_dir_and_deduplicates(self):
        self.use_v3_fixture()
        with tempfile.TemporaryDirectory() as temp_dir:
            kcredits.DATA_DIR = Path(temp_dir) / "private-archive"
            kcredits.CSV_PATH = kcredits.DATA_DIR / "usage.csv"
            kcredits.CLASSIC_DB = Path(temp_dir) / "no-classic-store.sqlite3"

            self.assertEqual(2, kcredits._append_rows(list(kcredits.all_turns())))
            self.assertEqual(0, kcredits._append_rows(list(kcredits.all_turns())))

            rows = kcredits.CSV_PATH.read_text(encoding="utf-8").splitlines()
            self.assertEqual(3, len(rows))
            self.assertIn("event_id", rows[0])

    def test_archive_neutralizes_spreadsheet_formulas_and_control_characters(self):
        self.use_v3_fixture()
        with tempfile.TemporaryDirectory() as temp_dir:
            kcredits.DATA_DIR = Path(temp_dir) / "private-archive"
            kcredits.CSV_PATH = kcredits.DATA_DIR / "usage.csv"
            kcredits.CLASSIC_DB = Path(temp_dir) / "no-classic-store.sqlite3"
            turn = dict(next(kcredits.iter_v3_turns()))
            turn["project"] = "=WEBSERVICE(\"https://example.invalid\")"
            turn["model"] = "model\x1b[31m"

            self.assertEqual(1, kcredits._append_rows([turn]))

            with kcredits.CSV_PATH.open("r", encoding="utf-8", newline="") as handle:
                row = next(csv.DictReader(handle))
            self.assertTrue(row["project"].startswith("'="))
            self.assertNotIn("\x1b", row["model"])
            self.assertIn("\\x1b", row["model"])

    def test_credit_values_must_be_finite_and_non_negative(self):
        self.assertEqual(0.0, kcredits._credit_value(0))
        self.assertEqual(1.25, kcredits._credit_value("1.25"))
        self.assertIsNone(kcredits._credit_value(-1))
        self.assertIsNone(kcredits._credit_value("nan"))
        self.assertIsNone(kcredits._credit_value("inf"))
        self.assertIsNone(kcredits._credit_value("not-a-number"))

    def test_terminal_text_escapes_control_characters(self):
        self.assertEqual("safe\\x1b[31m", kcredits._display_text("safe\x1b[31m"))

    def test_migrate_does_not_overwrite_existing_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            kcredits.LEGACY_CSV_PATH = temp / "legacy.csv"
            kcredits.LEGACY_CSV_PATH.write_text("event_id\nlegacy-1\n", encoding="utf-8")
            kcredits.DATA_DIR = temp / "private"
            kcredits.CSV_PATH = kcredits.DATA_DIR / "usage.csv"

            self.assertEqual(0, kcredits.cmd_migrate_legacy_archive())
            self.assertEqual("event_id\nlegacy-1\n", kcredits.CSV_PATH.read_text(encoding="utf-8"))
            self.assertEqual(1, kcredits.cmd_migrate_legacy_archive())

    def test_doctor_json_is_read_only_and_lists_paths(self):
        self.use_v3_fixture()
        with tempfile.TemporaryDirectory() as temp_dir:
            kcredits.DATA_DIR = Path(temp_dir) / "private"
            kcredits.CSV_PATH = kcredits.DATA_DIR / "usage.csv"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(0, kcredits.cmd_doctor(as_json=True))

            details = json.loads(output.getvalue())
            self.assertTrue(details["v3_sessions_dir_exists"])
            self.assertEqual(1, details["v3_session_count"])
            self.assertFalse(kcredits.DATA_DIR.exists())

    def test_classic_store_is_opened_read_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "data.sqlite3"
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE conversations_v2 "
                "(conversation_id TEXT, key TEXT, updated_at INTEGER, value TEXT)"
            )
            value = {
                "user_turn_metadata": {"usage_info": [{"unit": "credit", "value": 3.75}]},
                "model_info": {"model_name": "classic-model"},
            }
            conn.execute(
                "INSERT INTO conversations_v2 VALUES (?, ?, ?, ?)",
                ("classic-session", "C:\\work\\classic", 1782864000000, json.dumps(value)),
            )
            conn.commit()
            conn.close()
            kcredits.CLASSIC_DB = db_path

            turns = list(kcredits.iter_classic_turns())

            self.assertEqual(1, len(turns))
            self.assertEqual(3.75, turns[0]["credits"])
            self.assertEqual("classic-session#0", turns[0]["event_id"])


if __name__ == "__main__":
    unittest.main()
