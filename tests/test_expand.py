"""G5 expansion checks against the frozen public synthetic contract."""

from contextlib import closing
import base64
import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
VALID = (FIXTURES / "G2-valid.csv").read_bytes()


def csv_rows(rows):
    return ("month,building,kwh\n" + "".join(
        f"{row['month']},{row['building']},{row['kwh']}\n" for row in rows
    )).encode("ascii")


def invalid_case_bytes(case):
    source = case["input"]
    if "csv" in source:
        return source["csv"].encode("utf-8")
    if "bytes_hex" in source:
        return bytes.fromhex(source["bytes_hex"])
    return base64.b64decode(source["bytes_base64"])


def request(port, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    raw = response.read()
    content_type = response.getheader("Content-Type")
    connection.close()
    return response.status, content_type, json.loads(raw)


class ExpandedDomainTests(unittest.TestCase):
    def test_all_frozen_invalid_fixture_codes(self):
        from app.domain import DomainError, parse_dataset

        cases = json.loads((FIXTURES / "G2-invalid-input-cases.json").read_text())["cases"]
        for case in cases:
            with self.subTest(case=case["id"]), self.assertRaises(DomainError) as caught:
                parse_dataset(case["dataset_id"], invalid_case_bytes(case))
            self.assertEqual(caught.exception.code, case["expected_error"])

    def test_precedence_uses_catalog_priority_across_complete_batch(self):
        from app.domain import DomainError, parse_dataset

        examples = (
            (b"\xff\xef\xbb\xbf", "INVALID_UTF8"),
            (b"\xef\xbb\xbfmonth,building,kwh\r\n2026-01,A,1\n", "INVALID_CSV_BOM"),
            (b"bad,header,kwh\n2026-13,A,1\n", "INVALID_HEADER"),
            (b"month,building,kwh\n2026-13,A,1,extra\n", "INVALID_ROW_SHAPE"),
            (b"month,building,kwh\n2026-01,A,-1\n2026-13,B,2\n", "INVALID_MONTH"),
            (b"month,building,kwh\n2026-01,A,-1\n2026-01,B/B,2\n", "INVALID_BUILDING"),
            (b"month,building,kwh\n2026-01,A,1.0001\n2026-01,B,-1\n", "NEGATIVE_KWH"),
            (b"month,building,kwh\n2026-01,A,1e2\n2026-01,B,1.0001\n", "KWH_SCALE_EXCEEDED"),
            (b"month,building,kwh\n2026-01,A,1\n2026-01,A,bad\n", "INVALID_KWH_FORMAT"),
        )
        for raw, expected in examples:
            with self.subTest(expected=expected), self.assertRaises(DomainError) as caught:
                parse_dataset("g2-precedence", raw)
            self.assertEqual(caught.exception.code, expected)

    def test_quoted_csv_and_crlf_preserve_canonical_rows(self):
        from app.domain import parse_dataset

        quoted = json.loads((FIXTURES / "G2-quoted-fields.json").read_text())["csv"]
        original = parse_dataset("g2-quoted", VALID)
        for raw in (quoted.encode("ascii"), quoted.replace("\n", "\r\n").encode("ascii")):
            with self.subTest(ending="CRLF" if b"\r\n" in raw else "LF"):
                candidate = parse_dataset("g2-quoted", raw)
                self.assertEqual(candidate.canonical_sha256, original.canonical_sha256)
                self.assertEqual(candidate.monthly_totals, original.monthly_totals)
                self.assertEqual(candidate.comparisons, original.comparisons)

    def test_quoted_comma_and_doubled_quote_reach_field_validation(self):
        from app.domain import DomainError, parse_dataset

        for building in ('"A,B"', '"A""B"'):
            with self.subTest(building=building), self.assertRaises(DomainError) as caught:
                parse_dataset("g2-quoted-invalid-building", f"month,building,kwh\n2026-01,{building},1\n".encode("ascii"))
            self.assertEqual(caught.exception.code, "INVALID_BUILDING")

    def test_quote_in_unquoted_field_is_malformed_row(self):
        from app.domain import DomainError, parse_dataset

        raw = b'month,building,kwh\n2026-01,A"B,1\n'
        with self.assertRaises(DomainError) as caught:
            parse_dataset("g2-malformed-unquoted-quote", raw)
        self.assertEqual(caught.exception.code, "INVALID_ROW_SHAPE")

    def test_quoted_embedded_lf_is_row_shape_even_with_crlf_records(self):
        from app.domain import DomainError, parse_dataset

        raw = b'month,building,kwh\r\n2026-01,"A\nB",1\r\n'
        with self.assertRaises(DomainError) as caught:
            parse_dataset("g2-quoted-embedded-lf", raw)
        self.assertEqual(caught.exception.code, "INVALID_ROW_SHAPE")

    def test_decimal_threshold_missing_month_and_zero_baseline_oracles(self):
        from app.domain import parse_dataset

        cases = json.loads((FIXTURES / "G2-acceptance-cases.json").read_text())["cases"]
        for case in cases:
            if case["id"] not in {"G2-AC-07", "G2-AC-08", "G2-AC-09", "G2-AC-10", "G2-AC-11"}:
                continue
            with self.subTest(case=case["id"]):
                result = parse_dataset(case["dataset_id"], csv_rows(case["rows"])).to_public_dict()
                expected = case["expected"]
                if "monthly_totals_kwh" in expected:
                    self.assertEqual(result["monthly_totals_kwh"], expected["monthly_totals_kwh"])
                for key, expected_fields in expected["comparison"].items():
                    for field, value in expected_fields.items():
                        self.assertEqual(result["building_comparisons"][key][field], value)

        near = json.loads((FIXTURES / "G2-near-threshold.json").read_text())
        result = parse_dataset(near["dataset_id"], csv_rows(near["rows"])).to_public_dict()
        self.assertEqual(result["building_comparisons"]["2026-02/N"]["percent_change"], "30.000")
        self.assertFalse(result["building_comparisons"]["2026-02/N"]["anomaly"])

    def test_large_valid_comparison_uses_50_digit_ratio_and_three_digit_display(self):
        from app.domain import parse_dataset

        current = "1" + "0" * 60
        raw = f"month,building,kwh\n2026-01,A,1\n2026-02,A,{current}\n".encode("ascii")
        result = parse_dataset("g2-large-ratio", raw).to_public_dict()
        compared = result["building_comparisons"]["2026-02/A"]
        self.assertEqual(compared["percent_change"], "1" + "0" * 62 + ".000")
        self.assertTrue(compared["anomaly"])
        self.assertEqual(result["criterion_version"], "G2-30PCT-R1")


class ExpandedHttpTests(unittest.TestCase):
    def setUp(self):
        from app.server import make_server

        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "expanded.sqlite"
        self.server = make_server("127.0.0.1", 0, self.db_path, build_ref="G5-TEST")
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp.cleanup()

    @staticmethod
    def headers(dataset_id, actor="ANALYST"):
        return {"Content-Type": "text/csv", "X-Dataset-ID": dataset_id, "X-Synthetic-Actor": actor}

    def snapshot(self):
        from app.storage import EnergyStore

        return EnergyStore(self.db_path).snapshot(), self.db_path.read_bytes()

    def test_all_invalid_fixtures_return_exact_code_without_sqlite_mutation(self):
        cases = json.loads((FIXTURES / "G2-invalid-input-cases.json").read_text())["cases"]
        before = self.snapshot()
        for case in cases:
            with self.subTest(case=case["id"]):
                status, _, body = request(self.port, "POST", "/api/datasets", invalid_case_bytes(case), self.headers(case["dataset_id"]))
                self.assertEqual(status, 422)
                self.assertEqual(body["error"]["code"], case["expected_error"])
                self.assertEqual(self.snapshot(), before)

    def test_remaining_acceptance_cases_commit_exact_results(self):
        cases = json.loads((FIXTURES / "G2-acceptance-cases.json").read_text())["cases"]
        ids = {"G2-AC-07", "G2-AC-08", "G2-AC-09", "G2-AC-10", "G2-AC-11"}
        for case in cases:
            if case["id"] not in ids:
                continue
            with self.subTest(case=case["id"]):
                status, _, created = request(self.port, "POST", "/api/datasets", csv_rows(case["rows"]), self.headers(case["dataset_id"]))
                self.assertEqual(status, 201)
                result = created["dataset"]
                expected = case["expected"]
                if "monthly_totals_kwh" in expected:
                    self.assertEqual(result["monthly_totals_kwh"], expected["monthly_totals_kwh"])
                for key, expected_fields in expected["comparison"].items():
                    for field, value in expected_fields.items():
                        self.assertEqual(result["building_comparisons"][key][field], value)
                status, _, loaded = request(self.port, "GET", f"/api/datasets/{case['dataset_id']}", headers={"X-Synthetic-Actor": "REVIEWER"})
                self.assertEqual(status, 200)
                self.assertEqual(loaded["dataset"], result)

        near = json.loads((FIXTURES / "G2-near-threshold.json").read_text())
        status, _, created = request(self.port, "POST", "/api/datasets", csv_rows(near["rows"]), self.headers(near["dataset_id"]))
        self.assertEqual(status, 201)
        self.assertEqual(created["dataset"]["building_comparisons"]["2026-02/N"]["percent_change"], "30.000")
        self.assertFalse(created["dataset"]["building_comparisons"]["2026-02/N"]["anomaly"])

        quoted = json.loads((FIXTURES / "G2-quoted-fields.json").read_text())
        status, _, created = request(self.port, "POST", "/api/datasets", quoted["csv"].encode("ascii"), self.headers(quoted["dataset_id"]))
        self.assertEqual(status, 201)
        self.assertEqual(created["dataset"]["monthly_totals_kwh"], {"2026-01": "300.000", "2026-02": "370.000"})
        self.assertEqual(created["dataset"]["anomalies"], ["2026-02/A"])
        status, _, loaded = request(self.port, "GET", f"/api/datasets/{quoted['dataset_id']}", headers={"X-Synthetic-Actor": "REVIEWER"})
        self.assertEqual(status, 200)
        self.assertEqual(loaded["dataset"], created["dataset"])

    def test_invalid_month_and_mixed_valid_negative_batch_are_atomic(self):
        from app.storage import EnergyStore

        before = self.snapshot()
        cases = json.loads((FIXTURES / "G2-acceptance-cases.json").read_text())["cases"]
        mixed = next(case for case in cases if case["id"] == "G2-AC-13")
        for dataset_id, raw, code in (
            ("g2-invalid-month", (FIXTURES / "G2-invalid-month.csv").read_bytes(), "INVALID_MONTH"),
            (mixed["dataset_id"], csv_rows(mixed["rows"]), "NEGATIVE_KWH"),
        ):
            with self.subTest(dataset_id=dataset_id):
                status, _, rejected = request(self.port, "POST", "/api/datasets", raw, self.headers(dataset_id))
                self.assertEqual(status, 422)
                self.assertEqual(rejected["error"]["code"], code)
                self.assertEqual(self.snapshot(), before)
                self.assertIsNone(EnergyStore(self.db_path).get(dataset_id))

    def test_replay_reordered_replay_and_conflict_preserve_first_record(self):
        replay = json.loads((FIXTURES / "G2-replay.json").read_text())
        dataset_id = replay["dataset_id"]
        status, _, created = request(self.port, "POST", "/api/datasets", VALID, self.headers(dataset_id))
        self.assertEqual(status, 201)
        before = self.snapshot()
        for variant in ("exact_replay", "reordered_replay", "changed_replay"):
            with self.subTest(variant=variant):
                raw = csv_rows(replay[variant]["canonical_rows"])
                status, _, body = request(self.port, "POST", "/api/datasets", raw, self.headers(dataset_id))
                self.assertEqual(status, 409)
                self.assertEqual(body["error"]["code"], replay[variant]["expected_error"])
                self.assertEqual(self.snapshot(), before)
        quoted = json.loads((FIXTURES / "G2-quoted-fields.json").read_text())["csv"].encode("ascii")
        status, _, body = request(self.port, "POST", "/api/datasets", quoted, self.headers(dataset_id))
        self.assertEqual(status, 409)
        self.assertEqual(body["error"]["code"], "DUPLICATE_DATASET_REPLAY")
        self.assertEqual(self.snapshot(), before)
        status, _, body = request(self.port, "POST", "/api/datasets", b"month,building,kwh\n2026-01,A,-1\n", self.headers(dataset_id))
        self.assertEqual(status, 422)
        self.assertEqual(body["error"]["code"], "NEGATIVE_KWH")
        self.assertEqual(self.snapshot(), before)
        status, _, loaded = request(self.port, "GET", f"/api/datasets/{dataset_id}", headers={"X-Synthetic-Actor": "REVIEWER"})
        self.assertEqual(status, 200)
        self.assertEqual(loaded["dataset"], created["dataset"])

    def test_large_comparison_round_trips_exact_text_through_sqlite_and_http(self):
        current = "1" + "0" * 60
        raw = f"month,building,kwh\n2026-01,A,1\n2026-02,A,{current}\n".encode("ascii")
        status, _, created = request(self.port, "POST", "/api/datasets", raw, self.headers("g2-http-large-ratio"))
        self.assertEqual(status, 201)
        expected = "1" + "0" * 62 + ".000"
        self.assertEqual(created["dataset"]["building_comparisons"]["2026-02/A"]["percent_change"], expected)
        status, _, loaded = request(self.port, "GET", "/api/datasets/g2-http-large-ratio", headers={"X-Synthetic-Actor": "REVIEWER"})
        self.assertEqual(status, 200)
        self.assertEqual(loaded["dataset"], created["dataset"])
        with closing(sqlite3.connect(self.db_path)) as connection:
            stored = connection.execute("SELECT percent_change_milli_text FROM comparisons WHERE dataset_id=? AND month=?", ("g2-http-large-ratio", "2026-02")).fetchone()[0]
        self.assertEqual(stored, "1" + "0" * 65)

    def test_maximum_wire_length_keeps_large_ratio_defined(self):
        from app.server import MAX_BODY_BYTES

        prefix = b"month,building,kwh\n2026-01,A,1\n2026-02,A,"
        current = "1" + "0" * (MAX_BODY_BYTES - len(prefix) - 2)
        raw = prefix + current.encode("ascii") + b"\n"
        self.assertEqual(len(raw), MAX_BODY_BYTES)
        status, _, created = request(self.port, "POST", "/api/datasets", raw, self.headers("g2-max-wire-ratio"))
        self.assertEqual(status, 201)
        compared = created["dataset"]["building_comparisons"]["2026-02/A"]
        self.assertEqual(compared["percent_change"], "1" + "0" * (len(current) + 1) + ".000")
        status, _, loaded = request(self.port, "GET", "/api/datasets/g2-max-wire-ratio", headers={"X-Synthetic-Actor": "REVIEWER"})
        self.assertEqual(status, 200)
        self.assertEqual(loaded["dataset"], created["dataset"])

    def test_declarative_role_matrix_reads_replay_and_mutation_denial(self):
        status, _, created = request(self.port, "POST", "/api/datasets", VALID, self.headers("g2-role-matrix"))
        self.assertEqual(status, 201)
        before = self.snapshot()
        for actor in ("ANALYST", "REVIEWER"):
            with self.subTest(actor=actor):
                header = {"X-Synthetic-Actor": actor}
                status, _, history = request(self.port, "GET", "/api/datasets", headers=header)
                self.assertEqual(status, 200)
                self.assertEqual(history["datasets"][0]["dataset_id"], "g2-role-matrix")
                status, _, item = request(self.port, "GET", "/api/datasets/g2-role-matrix", headers=header)
                self.assertEqual(status, 200)
                self.assertEqual(item["dataset"], created["dataset"])
                for method in ("PUT", "PATCH", "DELETE"):
                    status, _, denied = request(self.port, method, "/api/datasets/g2-role-matrix", b"{}", header)
                    self.assertEqual(status, 405)
                    self.assertEqual(denied["error"]["code"], "METHOD_NOT_ALLOWED")
                    self.assertEqual(self.snapshot(), before)

        status, _, denied = request(self.port, "POST", "/api/datasets", b"\xff", self.headers("g2-role-matrix", "REVIEWER"))
        self.assertEqual(status, 403)
        self.assertEqual(denied["error"]["code"], "ROLE_NOT_PERMITTED")
        self.assertEqual(self.snapshot(), before)
        status, _, denied = request(self.port, "POST", "/api/datasets", VALID, self.headers("g2-reviewer-new", "REVIEWER"))
        self.assertEqual(status, 403)
        self.assertEqual(denied["error"]["code"], "ROLE_NOT_PERMITTED")
        self.assertEqual(self.snapshot(), before)
        status, _, replay = request(self.port, "POST", "/api/datasets", VALID, self.headers("g2-role-matrix"))
        self.assertEqual(status, 409)
        self.assertEqual(replay["error"]["code"], "DUPLICATE_DATASET_REPLAY")
        self.assertEqual(self.snapshot(), before)
