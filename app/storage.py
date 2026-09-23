"""SQLite persistence for immutable synthetic energy datasets."""

from __future__ import annotations

from contextlib import closing, suppress
import hashlib
import json
from pathlib import Path
import sqlite3

from .domain import (
    Comparison,
    DatasetCandidate,
    EnergyRow,
    candidate_from_parts,
    previous_month,
)


SCHEMA_VERSION = 1
_REQUIRED_TABLES = {"datasets", "source_rows", "monthly_totals", "comparisons"}


class StorageError(RuntimeError):
    """A stable storage or replay rejection."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class EnergyStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()

    def _read_write_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
        except sqlite3.Error:
            with suppress(sqlite3.Error):
                connection.close()
            raise
        return connection

    def _read_only_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path.as_uri() + "?mode=ro",
            uri=True,
            timeout=5,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        """Create the fixed schema once; validate existing databases read-only."""

        if self.path.exists():
            self._validate_existing_schema()
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._read_write_connection()) as connection:
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE datasets (
                    dataset_id TEXT PRIMARY KEY,
                    source_bytes BLOB NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    canonical_sha256 TEXT NOT NULL,
                    criterion_version TEXT NOT NULL,
                    accepted_sequence INTEGER NOT NULL UNIQUE
                );
                CREATE TABLE source_rows (
                    dataset_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
                    month TEXT NOT NULL,
                    building TEXT NOT NULL,
                    kwh_token TEXT NOT NULL,
                    kwh_milli_text TEXT NOT NULL,
                    PRIMARY KEY (dataset_id, ordinal),
                    UNIQUE (dataset_id, month, building),
                    FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT
                );
                CREATE TABLE monthly_totals (
                    dataset_id TEXT NOT NULL,
                    month TEXT NOT NULL,
                    total_milli_text TEXT NOT NULL,
                    PRIMARY KEY (dataset_id, month),
                    FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT
                );
                CREATE TABLE comparisons (
                    dataset_id TEXT NOT NULL,
                    month TEXT NOT NULL,
                    building TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN ('NO_PRIOR_MONTH', 'ZERO_BASELINE', 'COMPARED')
                    ),
                    percent_change_milli_text TEXT,
                    anomaly INTEGER NOT NULL CHECK (anomaly IN (0, 1)),
                    PRIMARY KEY (dataset_id, month, building),
                    CHECK (
                        (status = 'COMPARED' AND percent_change_milli_text IS NOT NULL)
                        OR
                        (status <> 'COMPARED' AND percent_change_milli_text IS NULL)
                    ),
                    CHECK (status = 'COMPARED' OR anomaly = 0),
                    FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT
                );
                PRAGMA user_version=1;
                COMMIT;
                """
            )

    def _validate_existing_schema(self) -> None:
        try:
            with closing(self._read_only_connection()) as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_schema WHERE type='table'"
                    )
                }
                integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
        except sqlite3.Error as error:
            raise StorageError("DATABASE_SCHEMA_INVALID") from error
        if version != SCHEMA_VERSION or not _REQUIRED_TABLES.issubset(tables):
            raise StorageError("DATABASE_SCHEMA_INVALID")
        if integrity != "ok":
            raise StorageError("DATABASE_INTEGRITY_FAILED")

    def save(self, candidate: DatasetCandidate) -> dict[str, object]:
        if not isinstance(candidate, DatasetCandidate):
            raise TypeError("candidate must be a DatasetCandidate")
        response = candidate.to_public_dict()
        connection: sqlite3.Connection | None = None
        try:
            connection = self._read_write_connection()
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT canonical_sha256 FROM datasets WHERE dataset_id=?",
                (candidate.dataset_id,),
            ).fetchone()
            if existing is not None:
                code = (
                    "DUPLICATE_DATASET_REPLAY"
                    if existing[0] == candidate.canonical_sha256
                    else "DATASET_ID_REUSE_CONFLICT"
                )
                connection.execute("ROLLBACK")
                raise StorageError(code)

            sequence = connection.execute(
                "SELECT COALESCE(MAX(accepted_sequence), 0) + 1 FROM datasets"
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO datasets(
                    dataset_id, source_bytes, source_sha256, canonical_sha256,
                    criterion_version, accepted_sequence
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.dataset_id,
                    sqlite3.Binary(candidate.source_bytes),
                    candidate.source_sha256,
                    candidate.canonical_sha256,
                    candidate.criterion_version,
                    sequence,
                ),
            )
            connection.executemany(
                """
                INSERT INTO source_rows(
                    dataset_id, ordinal, month, building, kwh_token,
                    kwh_milli_text
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        candidate.dataset_id,
                        row.ordinal,
                        row.month,
                        row.building,
                        row.kwh_token,
                        row.kwh_milli_text,
                    )
                    for row in candidate.rows
                ),
            )
            connection.executemany(
                """
                INSERT INTO monthly_totals(dataset_id, month, total_milli_text)
                VALUES (?, ?, ?)
                """,
                (
                    (candidate.dataset_id, month, total)
                    for month, total in candidate.monthly_totals
                ),
            )
            connection.executemany(
                """
                INSERT INTO comparisons(
                    dataset_id, month, building, status,
                    percent_change_milli_text, anomaly
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        candidate.dataset_id,
                        item.month,
                        item.building,
                        item.status,
                        item.percent_change_milli_text,
                        int(item.anomaly),
                    )
                    for item in candidate.comparisons
                ),
            )
            persisted = self._load_candidate(connection, candidate.dataset_id)
            if persisted is None or persisted != candidate:
                raise StorageError("DATABASE_READBACK_FAILED")
            connection.execute("COMMIT")
        except StorageError:
            self._rollback_quietly(connection)
            raise
        except sqlite3.Error as error:
            self._rollback_quietly(connection)
            raise StorageError("INTERNAL_STORAGE_ERROR") from error
        except Exception as error:
            self._rollback_quietly(connection)
            raise StorageError("INTERNAL_STORAGE_ERROR") from error
        finally:
            if connection is not None:
                with suppress(sqlite3.Error):
                    connection.close()
        return response

    @staticmethod
    def _rollback_quietly(connection: sqlite3.Connection | None) -> None:
        if connection is None or not connection.in_transaction:
            return
        with suppress(sqlite3.Error):
            connection.execute("ROLLBACK")

    def _load_candidate(
        self, connection: sqlite3.Connection, dataset_id: str
    ) -> DatasetCandidate | None:
        envelope = connection.execute(
            """
            SELECT dataset_id, source_bytes, source_sha256, canonical_sha256,
                   criterion_version
            FROM datasets WHERE dataset_id=?
            """,
            (dataset_id,),
        ).fetchone()
        if envelope is None:
            return None
        rows = tuple(
            EnergyRow(
                ordinal=row[0],
                month=row[1],
                building=row[2],
                kwh_token=row[3],
                kwh_milli_text=row[4],
            )
            for row in connection.execute(
                """
                SELECT ordinal, month, building, kwh_token, kwh_milli_text
                FROM source_rows WHERE dataset_id=? ORDER BY ordinal
                """,
                (dataset_id,),
            )
        )
        totals = tuple(
            (row[0], row[1])
            for row in connection.execute(
                """
                SELECT month, total_milli_text FROM monthly_totals
                WHERE dataset_id=? ORDER BY month
                """,
                (dataset_id,),
            )
        )
        source_by_key = {(row.month, row.building): row for row in rows}
        comparisons: list[Comparison] = []
        for item in connection.execute(
            """
            SELECT month, building, status, percent_change_milli_text, anomaly
            FROM comparisons WHERE dataset_id=? ORDER BY month, building
            """,
            (dataset_id,),
        ):
            current = source_by_key[(item[0], item[1])]
            if item[2] == "NO_PRIOR_MONTH":
                prior_name = None
                prior_value = None
            else:
                prior_name = previous_month(item[0])
                prior = source_by_key.get((prior_name, item[1]))
                if prior is None:
                    raise StorageError("DATABASE_INTEGRITY_FAILED")
                prior_value = prior.kwh_milli_text
            comparisons.append(
                Comparison(
                    month=item[0],
                    building=item[1],
                    status=item[2],
                    current_milli_text=current.kwh_milli_text,
                    prior_month=prior_name,
                    prior_milli_text=prior_value,
                    percent_change_milli_text=item[3],
                    anomaly=bool(item[4]),
                )
            )
        return candidate_from_parts(
            dataset_id=envelope[0],
            source_bytes=bytes(envelope[1]),
            source_sha256=envelope[2],
            canonical_sha256=envelope[3],
            criterion_version=envelope[4],
            rows=rows,
            monthly_totals=totals,
            comparisons=tuple(comparisons),
        )

    def get(self, dataset_id: str) -> dict[str, object] | None:
        try:
            with closing(self._read_only_connection()) as connection:
                candidate = self._load_candidate(connection, dataset_id)
                result = None if candidate is None else candidate.to_public_dict()
                if result is not None:
                    json.dumps(
                        result,
                        ensure_ascii=True,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
        except StorageError:
            raise
        except (sqlite3.Error, OSError, ValueError, TypeError, KeyError, IndexError) as error:
            raise StorageError("INTERNAL_STORAGE_ERROR") from error
        return result

    def list_datasets(self) -> list[dict[str, object]]:
        try:
            with closing(self._read_only_connection()) as connection:
                rows = connection.execute(
                    """
                    SELECT dataset_id, canonical_sha256, criterion_version,
                           accepted_sequence
                    FROM datasets ORDER BY accepted_sequence
                    """
                ).fetchall()
                results = []
                for row in rows:
                    candidate = self._load_candidate(connection, row[0])
                    if candidate is None:
                        raise StorageError("DATABASE_INTEGRITY_FAILED")
                    # Force persisted fixed-point decoding and public serialization
                    # while all storage failures remain inside this boundary.
                    candidate.to_public_dict()
                    results.append(
                        {
                            "dataset_id": row[0],
                            "record_id": candidate.record_id,
                            "canonical_sha256": row[1],
                            "criterion_version": row[2],
                            "accepted_sequence": row[3],
                            "anomaly_count": len(candidate.anomalies),
                        }
                    )
                json.dumps(
                    results,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                )
        except StorageError:
            raise
        except (sqlite3.Error, OSError, ValueError, TypeError, KeyError, IndexError) as error:
            raise StorageError("INTERNAL_STORAGE_ERROR") from error
        return results

    def snapshot(self) -> dict[str, tuple[tuple[object, ...], ...]]:
        """Return deterministic logical table contents for atomicity checks."""

        queries = {
            "datasets": """
                SELECT dataset_id, hex(source_bytes), source_sha256,
                       canonical_sha256, criterion_version, accepted_sequence
                FROM datasets ORDER BY dataset_id
            """,
            "source_rows": """
                SELECT dataset_id, ordinal, month, building, kwh_token,
                       kwh_milli_text
                FROM source_rows ORDER BY dataset_id, ordinal
            """,
            "monthly_totals": """
                SELECT dataset_id, month, total_milli_text
                FROM monthly_totals ORDER BY dataset_id, month
            """,
            "comparisons": """
                SELECT dataset_id, month, building, status,
                       percent_change_milli_text, anomaly
                FROM comparisons ORDER BY dataset_id, month, building
            """,
        }
        with closing(self._read_only_connection()) as connection:
            return {
                name: tuple(tuple(row) for row in connection.execute(query))
                for name, query in queries.items()
            }

    def database_identity(self) -> str:
        try:
            source = self.path.read_bytes()
        except OSError as error:
            raise StorageError("INTERNAL_STORAGE_ERROR") from error
        return "sha256:" + hashlib.sha256(source).hexdigest()
