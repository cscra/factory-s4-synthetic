import ast
from contextlib import closing
import hashlib
import http.client
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
VALID = (FIXTURES / "G2-valid.csv").read_bytes()
NEGATIVE = (FIXTURES / "G2-negative.csv").read_bytes()
DUPLICATE = (FIXTURES / "G2-duplicate.csv").read_bytes()


def assert_no_float(testcase, value):
    if isinstance(value, dict):
        for item in value.values():
            assert_no_float(testcase, item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            assert_no_float(testcase, item)
    else:
        testcase.assertNotIsInstance(value, float)


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def request(port, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    raw = response.read()
    content_type = response.getheader("Content-Type")
    connection.close()
    return response.status, content_type, json.loads(raw)


class SqlFailureConnection:
    """Delegate to a real SQLite connection and fail one selected statement."""

    def __init__(self, connection, statement_prefix):
        self.connection = connection
        self.statement_prefix = statement_prefix
        self.failed = False

    @property
    def in_transaction(self):
        return self.connection.in_transaction

    def execute(self, sql, parameters=()):
        normalized = " ".join(sql.split()).upper()
        if not self.failed and normalized.startswith(self.statement_prefix):
            self.failed = True
            raise sqlite3.OperationalError("injected storage fault")
        return self.connection.execute(sql, parameters)

    def __getattr__(self, name):
        return getattr(self.connection, name)


class StaticPageParser(HTMLParser):
    """Extract the static page contracts without assuming a browser engine."""

    def __init__(self):
        super().__init__()
        self.dataset_id_patterns = []
        self.favicon_hrefs = []
        self.csp_policies = []
        self.styles = []
        self._in_style = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "input" and attributes.get("id") == "dataset-id":
            self.dataset_id_patterns.append(attributes.get("pattern"))
        if tag == "link" and attributes.get("rel") == "icon":
            self.favicon_hrefs.append(attributes.get("href"))
        if tag == "meta" and attributes.get("http-equiv") == "Content-Security-Policy":
            self.csp_policies.append(attributes.get("content", ""))
        if tag == "style":
            self._in_style = True

    def handle_endtag(self, tag):
        if tag == "style":
            self._in_style = False

    def handle_data(self, data):
        if self._in_style:
            self.styles.append(data)


class DomainTests(unittest.TestCase):
    def test_valid_fixture_has_exact_decimal_results(self):
        from app.domain import parse_dataset

        result = parse_dataset("g2-sample-2026-01-02", VALID).to_public_dict()

        self.assertEqual(
            result["monthly_totals_kwh"],
            {"2026-01": "300.000", "2026-02": "370.000"},
        )
        self.assertEqual(result["building_comparisons"]["2026-02/A"]["percent_change"], "60.000")
        self.assertTrue(result["building_comparisons"]["2026-02/A"]["anomaly"])
        self.assertEqual(result["building_comparisons"]["2026-02/B"]["percent_change"], "5.000")
        self.assertFalse(result["building_comparisons"]["2026-02/B"]["anomaly"])
        self.assertEqual(result["building_comparisons"]["2026-01/A"]["comparison_status"], "NO_PRIOR_MONTH")
        self.assertEqual(result["anomalies"], ["2026-02/A"])
        self.assertEqual(result["criterion_version"], "G2-30PCT-R1")
        assert_no_float(self, result)

    def test_negative_and_duplicate_batches_have_exact_codes(self):
        from app.domain import DomainError, parse_dataset

        for dataset_id, raw, code in (
            ("g2-negative-atomic", NEGATIVE, "NEGATIVE_KWH"),
            ("g2-duplicate-atomic", DUPLICATE, "DUPLICATE_MONTH_BUILDING"),
        ):
            with self.subTest(code=code), self.assertRaises(DomainError) as caught:
                parse_dataset(dataset_id, raw)
            self.assertEqual(caught.exception.code, code)

    def test_threshold_compares_quantized_decimal_with_strict_greater_than(self):
        from app.domain import parse_dataset

        raw = (
            b"month,building,kwh\n"
            b"2026-01,A,100\n2026-02,A,130\n"
            b"2026-01,B,100\n2026-02,B,130.001\n"
        )
        result = parse_dataset("g2-threshold-slice", raw).to_public_dict()

        self.assertEqual(result["building_comparisons"]["2026-02/A"]["percent_change"], "30.000")
        self.assertFalse(result["building_comparisons"]["2026-02/A"]["anomaly"])
        self.assertEqual(result["building_comparisons"]["2026-02/B"]["percent_change"], "30.001")
        self.assertTrue(result["building_comparisons"]["2026-02/B"]["anomaly"])

    def test_legal_4301_digit_kwh_has_no_implicit_integer_limit(self):
        from app.domain import parse_dataset

        huge = "9" * 4301
        raw = f"month,building,kwh\n2026-01,A,{huge}\n".encode("ascii")
        result = parse_dataset("g2-large-legal", raw).to_public_dict()

        self.assertEqual(result["rows"][0]["kwh"], huge + ".000")
        self.assertEqual(result["monthly_totals_kwh"], {"2026-01": huge + ".000"})
        self.assertEqual(
            result["building_comparisons"]["2026-01/A"]["comparison_status"],
            "NO_PRIOR_MONTH",
        )
        assert_no_float(self, result)

    def test_undefined_50_digit_percentage_fails_closed_with_stable_code(self):
        from app.domain import CalculationError, parse_dataset

        huge = "9" * 4301
        raw = (
            "month,building,kwh\n"
            "2026-01,A,1\n"
            f"2026-02,A,{huge}\n"
        ).encode("ascii")
        with self.assertRaises(CalculationError) as caught:
            parse_dataset("g2-large-ratio", raw)
        self.assertEqual(caught.exception.code, "INTERNAL_CALCULATION_ERROR")


class StorageTests(unittest.TestCase):
    def setUp(self):
        from app.storage import EnergyStore

        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "energy.sqlite"
        self.store = EnergyStore(self.db_path)
        self.store.initialize()

    def tearDown(self):
        self.temp.cleanup()

    def test_rejected_domain_batches_leave_sqlite_logically_unchanged(self):
        from app.domain import DomainError, parse_dataset

        self.store.save(parse_dataset("g2-sample-2026-01-02", VALID))
        before = self.store.snapshot()
        for dataset_id, raw in (
            ("g2-negative-atomic", NEGATIVE),
            ("g2-duplicate-atomic", DUPLICATE),
        ):
            with self.assertRaises(DomainError):
                self.store.save(parse_dataset(dataset_id, raw))
            self.assertEqual(self.store.snapshot(), before)

    def test_same_dataset_id_is_immutable_for_exact_and_changed_replay(self):
        from app.domain import parse_dataset
        from app.storage import StorageError

        self.store.save(parse_dataset("g2-sample-2026-01-02", VALID))
        before = self.store.snapshot()
        with self.assertRaises(StorageError) as exact:
            self.store.save(parse_dataset("g2-sample-2026-01-02", VALID))
        self.assertEqual(exact.exception.code, "DUPLICATE_DATASET_REPLAY")
        changed = VALID.replace(b"2026-02,A,160", b"2026-02,A,161")
        with self.assertRaises(StorageError) as conflict:
            self.store.save(parse_dataset("g2-sample-2026-01-02", changed))
        self.assertEqual(conflict.exception.code, "DATASET_ID_REUSE_CONFLICT")
        self.assertEqual(self.store.snapshot(), before)

    def test_readback_preserves_record_identity_and_canonical_text(self):
        from app.domain import parse_dataset

        candidate = parse_dataset("g2-sample-2026-01-02", VALID)
        saved = self.store.save(candidate)
        loaded = self.store.get("g2-sample-2026-01-02")

        self.assertEqual(loaded, saved)
        self.assertEqual(loaded["record_id"], candidate.record_id)
        self.assertEqual(loaded["monthly_totals_kwh"]["2026-01"], "300.000")
        self.assertEqual(self.store.list_datasets()[0]["dataset_id"], "g2-sample-2026-01-02")
        assert_no_float(self, loaded)

    def test_sqlite_schema_preserves_fixed_point_text_and_foreign_keys(self):
        from app.domain import parse_dataset

        self.store.save(parse_dataset("g2-sample-2026-01-02", VALID))
        with closing(sqlite3.connect(self.db_path)) as connection:
            foreign_key_tables = {
                row[2]
                for table in ("source_rows", "monthly_totals", "comparisons")
                for row in connection.execute(f"PRAGMA foreign_key_list({table})")
            }
            stored = connection.execute(
                """
                SELECT d.criterion_version, s.kwh_milli_text,
                       m.total_milli_text, c.percent_change_milli_text,
                       typeof(s.kwh_milli_text), typeof(m.total_milli_text),
                       typeof(c.percent_change_milli_text)
                FROM datasets d
                JOIN source_rows s USING(dataset_id)
                JOIN monthly_totals m ON m.dataset_id=d.dataset_id AND m.month='2026-01'
                JOIN comparisons c ON c.dataset_id=d.dataset_id
                  AND c.month='2026-02' AND c.building='A'
                WHERE s.month='2026-01' AND s.building='A'
                """
            ).fetchone()

        self.assertEqual(foreign_key_tables, {"datasets"})
        self.assertEqual(
            stored,
            ("G2-30PCT-R1", "100000", "300000", "60000", "text", "text", "text"),
        )

    def test_precommit_and_commit_faults_roll_back_with_stable_error(self):
        from app.domain import parse_dataset
        from app.storage import StorageError

        for dataset_id, statement in (
            ("g2-precommit-fault", "INSERT INTO DATASETS"),
            ("g2-commit-fault", "COMMIT"),
        ):
            with self.subTest(statement=statement):
                candidate = parse_dataset(dataset_id, VALID)
                before = self.store.snapshot()
                real_connection = self.store._read_write_connection()
                failing = SqlFailureConnection(real_connection, statement)
                with mock.patch.object(
                    self.store, "_read_write_connection", return_value=failing
                ):
                    with self.assertRaises(StorageError) as caught:
                        self.store.save(candidate)
                self.assertEqual(caught.exception.code, "INTERNAL_STORAGE_ERROR")
                self.assertEqual(self.store.snapshot(), before)
                self.assertIsNone(self.store.get(dataset_id))

    def test_save_has_no_postcommit_database_read_failure_window(self):
        from app.domain import parse_dataset

        candidate = parse_dataset("g2-no-postcommit-read", VALID)
        with mock.patch.object(
            self.store,
            "_read_only_connection",
            side_effect=sqlite3.OperationalError("injected post-commit read fault"),
        ) as postcommit_read:
            saved = self.store.save(candidate)

        postcommit_read.assert_not_called()
        self.assertEqual(saved, candidate.to_public_dict())
        self.assertEqual(self.store.get(candidate.dataset_id), saved)


class HttpTests(unittest.TestCase):
    def setUp(self):
        from app.server import make_server

        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "energy.sqlite"
        self.server = make_server("127.0.0.1", 0, self.db_path, build_ref="TEST-BUILD")
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temp.cleanup()

    @staticmethod
    def post_headers(dataset_id="g2-sample-2026-01-02", actor="ANALYST", media="text/csv"):
        return {
            "X-Dataset-ID": dataset_id,
            "X-Synthetic-Actor": actor,
            "Content-Type": media,
        }

    def test_non_loopback_listener_is_rejected(self):
        from app.server import make_server

        with self.assertRaises(ValueError):
            make_server("0.0.0.0", 0, self.db_path, build_ref="TEST-BUILD")

    def test_real_http_import_and_readback(self):
        status, content_type, created = request(
            self.port, "POST", "/api/datasets", VALID, self.post_headers()
        )
        self.assertEqual(status, 201)
        self.assertEqual(content_type, "application/json; charset=utf-8")
        self.assertTrue(created["ok"])
        status, _, loaded = request(
            self.port,
            "GET",
            "/api/datasets/g2-sample-2026-01-02",
            headers={"X-Synthetic-Actor": "REVIEWER"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(loaded["dataset"], created["dataset"])

    def test_actor_method_length_and_media_preflight_do_not_mutate(self):
        from app.storage import EnergyStore

        store = EnergyStore(self.db_path)
        before = store.snapshot()
        status, _, body = request(
            self.port,
            "POST",
            "/api/datasets",
            b"not utf8 \xff",
            self.post_headers(actor="REVIEWER", media="application/octet-stream"),
        )
        self.assertEqual((status, body["error"]["code"]), (403, "ROLE_NOT_PERMITTED"))
        status, _, body = request(self.port, "PUT", "/api/datasets", b"", {})
        self.assertEqual((status, body["error"]["code"]), (405, "METHOD_NOT_ALLOWED"))
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.putrequest("POST", "/api/datasets")
        connection.putheader("X-Dataset-ID", "g2-missing-length")
        connection.putheader("X-Synthetic-Actor", "ANALYST")
        connection.putheader("Content-Type", "text/csv")
        connection.endheaders()
        response = connection.getresponse()
        missing = json.loads(response.read())
        connection.close()
        self.assertEqual((response.status, missing["error"]["code"]), (411, "HTTP_LENGTH_REQUIRED"))
        status, _, wrong_media = request(
            self.port,
            "POST",
            "/api/datasets",
            VALID,
            self.post_headers(media="application/json"),
        )
        self.assertEqual((status, wrong_media["error"]["code"]), (415, "HTTP_MEDIA_TYPE_REQUIRED"))
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.putrequest("POST", "/api/datasets")
        connection.putheader("X-Dataset-ID", "g2-too-large")
        connection.putheader("X-Synthetic-Actor", "ANALYST")
        connection.putheader("Content-Type", "text/csv")
        connection.putheader("Content-Length", "65537")
        connection.endheaders()
        response = connection.getresponse()
        oversized = json.loads(response.read())
        connection.close()
        self.assertEqual((response.status, oversized["error"]["code"]), (413, "HTTP_PAYLOAD_TOO_LARGE"))
        self.assertEqual(store.snapshot(), before)

    def test_trace_and_connect_return_bounded_405_without_mutation(self):
        from app.storage import EnergyStore

        store = EnergyStore(self.db_path)
        before = store.snapshot()
        for method in ("TRACE", "CONNECT"):
            with self.subTest(method=method):
                status, content_type, body = request(
                    self.port,
                    method,
                    "/api/datasets",
                    VALID,
                    self.post_headers(),
                )
                self.assertEqual(status, 405)
                self.assertEqual(content_type, "application/json; charset=utf-8")
                self.assertEqual(body["error"]["code"], "METHOD_NOT_ALLOWED")
                self.assertEqual(store.snapshot(), before)

    def test_read_only_sqlite_returns_bounded_json_without_mutation(self):
        from app.storage import EnergyStore

        store = EnergyStore(self.db_path)
        before = store.snapshot()
        original_mode = self.db_path.stat().st_mode
        os.chmod(self.db_path, 0o444)
        try:
            status, content_type, body = request(
                self.port,
                "POST",
                "/api/datasets",
                VALID,
                self.post_headers(dataset_id="g2-read-only"),
            )
            self.assertEqual(status, 500)
            self.assertEqual(content_type, "application/json; charset=utf-8")
            self.assertEqual(body["error"]["code"], "INTERNAL_STORAGE_ERROR")
            self.assertEqual(store.snapshot(), before)
        finally:
            os.chmod(self.db_path, original_mode)

    def test_non_sqlite_readback_failure_returns_bounded_json_and_rolls_back(self):
        from app.storage import EnergyStore

        store = EnergyStore(self.db_path)
        before = store.snapshot()
        with mock.patch.object(
            self.server.store,
            "_load_candidate",
            side_effect=ValueError("injected readback conversion fault"),
        ):
            status, content_type, body = request(
                self.port,
                "POST",
                "/api/datasets",
                VALID,
                self.post_headers(dataset_id="g4-readback-value-error"),
            )

        self.assertEqual(status, 500)
        self.assertEqual(content_type, "application/json; charset=utf-8")
        self.assertEqual(body["error"]["code"], "INTERNAL_STORAGE_ERROR")
        self.assertEqual(store.snapshot(), before)

    def test_large_legal_http_value_is_accepted_and_undefined_ratio_is_atomic(self):
        from app.storage import EnergyStore

        huge = "9" * 4301
        accepted_raw = f"month,building,kwh\n2026-01,A,{huge}\n".encode("ascii")
        status, _, created = request(
            self.port,
            "POST",
            "/api/datasets",
            accepted_raw,
            self.post_headers(dataset_id="g2-large-http"),
        )
        self.assertEqual(status, 201)
        self.assertEqual(created["dataset"]["rows"][0]["kwh"], huge + ".000")

        store = EnergyStore(self.db_path)
        before = store.snapshot()
        undefined_raw = (
            "month,building,kwh\n"
            "2026-01,A,1\n"
            f"2026-02,A,{huge}\n"
        ).encode("ascii")
        status, content_type, rejected = request(
            self.port,
            "POST",
            "/api/datasets",
            undefined_raw,
            self.post_headers(dataset_id="g2-large-ratio-http"),
        )
        self.assertEqual(status, 500)
        self.assertEqual(content_type, "application/json; charset=utf-8")
        self.assertEqual(
            rejected["error"]["code"], "INTERNAL_CALCULATION_ERROR"
        )
        self.assertEqual(store.snapshot(), before)

    def test_public_4xx_codes_are_frozen_business_or_explicit_transport(self):
        from http import HTTPStatus

        catalog = json.loads((ROOT / "specs" / "error-catalog.json").read_text())
        catalog_codes = {item["code"] for item in catalog["codes"]}

        domain_tree = ast.parse((ROOT / "app" / "domain.py").read_text())
        domain_codes = {
            node.args[0].value
            for node in ast.walk(domain_tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "DomainError"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        }

        server_tree = ast.parse((ROOT / "app" / "server.py").read_text())
        literal_4xx = set()
        for node in ast.walk(server_tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_error"
                and len(node.args) >= 2
                and isinstance(node.args[0], ast.Attribute)
                and isinstance(node.args[0].value, ast.Name)
                and node.args[0].value.id == "HTTPStatus"
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
            ):
                continue
            status = getattr(HTTPStatus, node.args[0].attr)
            if 400 <= int(status) < 500:
                literal_4xx.add(node.args[1].value)

        replay_codes = {"DUPLICATE_DATASET_REPLAY", "DATASET_ID_REUSE_CONFLICT"}
        transport_codes = {
            "METHOD_NOT_ALLOWED",
            "HTTP_LENGTH_REQUIRED",
            "HTTP_PAYLOAD_TOO_LARGE",
            "HTTP_MEDIA_TYPE_REQUIRED",
            "HTTP_BODY_INCOMPLETE",
            "DATASET_NOT_FOUND",
            "RESOURCE_NOT_FOUND",
        }
        public_business_codes = domain_codes | replay_codes | (
            literal_4xx - transport_codes
        )

        self.assertLessEqual(public_business_codes, catalog_codes)
        self.assertLessEqual(literal_4xx, catalog_codes | transport_codes)
        self.assertNotIn("INTERNAL_CALCULATION_ERROR", public_business_codes)
        self.assertNotIn("INTERNAL_CALCULATION_ERROR", transport_codes)

    def test_negative_and_duplicate_http_batches_do_not_mutate(self):
        from app.storage import EnergyStore

        store = EnergyStore(self.db_path)
        before = store.snapshot()
        for dataset_id, raw, code in (
            ("g2-negative-atomic", NEGATIVE, "NEGATIVE_KWH"),
            ("g2-duplicate-atomic", DUPLICATE, "DUPLICATE_MONTH_BUILDING"),
        ):
            status, _, body = request(
                self.port,
                "POST",
                "/api/datasets",
                raw,
                self.post_headers(dataset_id=dataset_id),
            )
            self.assertEqual(status, 422)
            self.assertEqual(body["error"]["code"], code)
            self.assertEqual(store.snapshot(), before)

    def test_index_exposes_real_api_controls_and_limitations(self):
        status, content_type, _ = request(self.port, "GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/json; charset=utf-8")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.request("GET", "/")
        response = connection.getresponse()
        html = response.read().decode("utf-8")
        connection.close()
        self.assertEqual(response.status, 200)
        for marker in (
            'id="dataset-id"',
            'id="csv-file"',
            'id="import-form"',
            'id="history"',
            "fetch('/api/datasets'",
            "NO_LOGIN",
            "IDENTITY_ENFORCEMENT_NOT_PROVEN",
            "connect-src 'self'",
            "G2-30PCT-R1",
        ):
            self.assertIn(marker, html)
        self.assertEqual(html.count("台账未改变"), 1)

        page = StaticPageParser()
        page.feed(html)
        self.assertEqual(page.dataset_id_patterns, [r"[a-z0-9][a-z0-9._\-]{0,63}"])
        self.assertEqual(page.favicon_hrefs, ["data:,"])
        self.assertEqual(len(page.csp_policies), 1)
        self.assertIn("img-src 'self' data:", page.csp_policies[0])

        css = "\n".join(page.styles)
        self.assertRegex(
            css,
            r"(?s)@media\s*\(max-width:\s*760px\)\s*\{.*?main\s*\{\s*width:\s*min\(calc\(100%\s*-\s*20px\),\s*680px\)",
        )
        self.assertRegex(
            css,
            r"(?s)@media\s*\(max-width:\s*760px\)\s*\{.*?\.grid\s*\{\s*grid-template-columns:\s*minmax\(0,\s*1fr\);",
        )
        self.assertRegex(css, r"\.grid\s*>\s*section\s*\{\s*min-width:\s*0;")
        self.assertRegex(
            css,
            r"\.table-wrap\s*\{\s*min-width:\s*0;\s*overflow-x:\s*auto;",
        )
        self.assertRegex(css, r"table\s*\{[^}]*min-width:\s*690px;")

    def test_index_distinguishes_confirmed_rejection_from_unknown_outcome(self):
        html = (ROOT / "app" / "static" / "index.html").read_text()

        for marker in (
            "CONFIRMED_REJECTION_CODES",
            "confirmed_rejection",
            "response.status >= 400 && response.status < 500",
            "CONFIRMED_REJECTION_CODES.has(code)",
            "结果未知，请刷新历史确认",
        ):
            self.assertIn(marker, html)

    def test_missing_static_file_is_bounded_and_api_reads_remain_healthy(self):
        missing = Path(self.temp.name) / "missing-index.html"
        with mock.patch("app.server.STATIC_INDEX", missing):
            for path in ("/", "/index.html"):
                with self.subTest(path=path):
                    status, content_type, body = request(self.port, "GET", path)
                    self.assertEqual(status, 500)
                    self.assertEqual(content_type, "application/json; charset=utf-8")
                    self.assertEqual(body["error"]["code"], "INTERNAL_SERVER_ERROR")
                    self.assertNotIn(str(missing), json.dumps(body))

            status, _, health = request(self.port, "GET", "/api/health")
            self.assertEqual((status, health["ok"]), (200, True))
            status, _, history = request(
                self.port,
                "GET",
                "/api/datasets",
                headers={"X-Synthetic-Actor": "ANALYST"},
            )
            self.assertEqual((status, history["ok"]), (200, True))

    def test_corrupt_persisted_value_is_bounded_on_list_and_item_reads(self):
        from app.domain import parse_dataset
        from app.storage import EnergyStore

        store = EnergyStore(self.db_path)
        store.save(parse_dataset("g2-corrupt-read", VALID))
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                """
                UPDATE source_rows SET kwh_milli_text='not-milli'
                WHERE dataset_id='g2-corrupt-read' AND ordinal=1
                """
            )
            connection.commit()

        for path in ("/api/datasets", "/api/datasets/g2-corrupt-read"):
            with self.subTest(path=path):
                status, content_type, body = request(
                    self.port,
                    "GET",
                    path,
                    headers={"X-Synthetic-Actor": "REVIEWER"},
                )
                self.assertEqual(status, 500)
                self.assertEqual(content_type, "application/json; charset=utf-8")
                self.assertEqual(body["error"]["code"], "INTERNAL_STORAGE_ERROR")
                rendered = json.dumps(body)
                self.assertNotIn("not-milli", rendered)
                self.assertNotIn(str(self.db_path), rendered)

        status, _, health = request(self.port, "GET", "/api/health")
        self.assertEqual((status, health["ok"]), (200, True))
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.request("GET", "/")
        response = connection.getresponse()
        response.read()
        connection.close()
        self.assertEqual(response.status, 200)

    def test_success_response_is_serialized_before_storage_and_not_after(self):
        import app.server as server_module

        original_json_bytes = server_module._json_bytes
        original_save = self.server.store.save
        state = {"save_returned": False, "success_serializations": 0}

        def tracked_json_bytes(value):
            if isinstance(value, dict) and value.get("ok") is True and "dataset" in value:
                self.assertFalse(state["save_returned"])
                state["success_serializations"] += 1
            return original_json_bytes(value)

        def tracked_save(candidate):
            result = original_save(candidate)
            state["save_returned"] = True
            return result

        with mock.patch.object(server_module, "_json_bytes", tracked_json_bytes), mock.patch.object(
            self.server.store, "save", tracked_save
        ):
            status, _, body = request(
                self.port,
                "POST",
                "/api/datasets",
                VALID,
                self.post_headers(dataset_id="g2-pre-serialized"),
            )

        self.assertEqual((status, body["ok"]), (201, True))
        self.assertTrue(state["save_returned"])
        self.assertEqual(state["success_serializations"], 1)

    def test_success_serialization_failure_occurs_before_any_write(self):
        import app.server as server_module
        from app.storage import EnergyStore

        original_json_bytes = server_module._json_bytes

        def fail_success_json(value):
            if isinstance(value, dict) and value.get("ok") is True and "dataset" in value:
                raise ValueError("injected success serialization fault")
            return original_json_bytes(value)

        store = EnergyStore(self.db_path)
        before = store.snapshot()
        with mock.patch.object(server_module, "_json_bytes", fail_success_json):
            status, content_type, body = request(
                self.port,
                "POST",
                "/api/datasets",
                VALID,
                self.post_headers(dataset_id="g2-serialization-fault"),
            )

        self.assertEqual(status, 500)
        self.assertEqual(content_type, "application/json; charset=utf-8")
        self.assertEqual(body["error"]["code"], "INTERNAL_SERVER_ERROR")
        self.assertEqual(store.snapshot(), before)

    def test_storage_faults_on_all_get_routes_return_bounded_json(self):
        backup = self.db_path.with_name("energy-backup.sqlite")
        os.replace(self.db_path, backup)
        self.db_path.mkdir()
        try:
            routes = (
                ("/api/health", {}),
                ("/api/datasets", {"X-Synthetic-Actor": "ANALYST"}),
                (
                    "/api/datasets/g2-sample-2026-01-02",
                    {"X-Synthetic-Actor": "REVIEWER"},
                ),
            )
            for path, headers in routes:
                with self.subTest(path=path):
                    status, content_type, body = request(
                        self.port, "GET", path, headers=headers
                    )
                    self.assertEqual(status, 500)
                    self.assertEqual(content_type, "application/json; charset=utf-8")
                    self.assertEqual(body["error"]["code"], "INTERNAL_STORAGE_ERROR")
                    self.assertNotIn(str(self.db_path), json.dumps(body))
        finally:
            self.db_path.rmdir()
            os.replace(backup, self.db_path)


class RestartProcessTests(unittest.TestCase):
    def start_server(self, port, db_path, build_ref):
        process = subprocess.Popen(
            [
                sys.executable,
                "-B",
                "-m",
                "app.server",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--db",
                str(db_path),
                "--build-ref",
                build_ref,
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                self.fail(f"server exited early: {stdout}\n{stderr}")
            try:
                status, _, _ = request(port, "GET", "/api/health")
                if status == 200:
                    return process
            except OSError:
                time.sleep(0.05)
        process.terminate()
        process.wait(timeout=3)
        self.fail("server did not become ready")

    def stop_server(self, process):
        process.terminate()
        process.wait(timeout=4)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
        self.assertIsNotNone(process.returncode)

    def test_process_b_reloads_same_id_from_process_a_database(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "restart.sqlite"
            port_a = free_port()
            process_a = self.start_server(port_a, db_path, "PROCESS-A")
            status, _, created = request(
                port_a,
                "POST",
                "/api/datasets",
                VALID,
                {
                    "X-Dataset-ID": "g2-sample-2026-01-02",
                    "X-Synthetic-Actor": "ANALYST",
                    "Content-Type": "text/csv",
                },
            )
            self.assertEqual(status, 201)
            pid_a = process_a.pid
            self.stop_server(process_a)
            before = hashlib.sha256(db_path.read_bytes()).hexdigest()

            port_b = free_port()
            process_b = self.start_server(port_b, db_path, "PROCESS-B")
            try:
                status, _, loaded = request(
                    port_b,
                    "GET",
                    "/api/datasets/g2-sample-2026-01-02",
                    headers={"X-Synthetic-Actor": "ANALYST"},
                )
                self.assertEqual(status, 200)
                self.assertNotEqual(pid_a, process_b.pid)
                self.assertEqual(loaded["dataset"], created["dataset"])
                self.assertEqual(hashlib.sha256(db_path.read_bytes()).hexdigest(), before)
            finally:
                self.stop_server(process_b)


if __name__ == "__main__":
    unittest.main()
