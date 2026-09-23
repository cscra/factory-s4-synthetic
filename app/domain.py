"""Strict synthetic energy-import domain rules for the approved first slice."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal, DecimalException, ROUND_HALF_EVEN, localcontext
import hashlib
import io
import json
import re


CRITERION_VERSION = "G2-30PCT-R1"
THRESHOLD_PERCENT = Decimal("30.000")
_DATASET_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
_MONTH = re.compile(r"([0-9]{4})-(0[1-9]|1[0-2])\Z")
_BUILDING = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_KWH = re.compile(r"(0|[1-9][0-9]*)(?:\.([0-9]{1,3}))?\Z")
_NEGATIVE_KWH = re.compile(r"-(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
_SCALE_EXCEEDED = re.compile(r"(?:0|[1-9][0-9]*)\.([0-9]{4,})\Z")


class DomainError(ValueError):
    """A stable, machine-readable rejection of an entire candidate batch."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class CalculationError(RuntimeError):
    """A technical failure to produce the frozen three-decimal result."""

    code = "INTERNAL_CALCULATION_ERROR"

    def __init__(self):
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class EnergyRow:
    ordinal: int
    month: str
    building: str
    kwh_token: str
    kwh_milli_text: str

    def to_public_dict(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "month": self.month,
            "building": self.building,
            "kwh_token": self.kwh_token,
            "kwh": format_milli(self.kwh_milli_text),
        }


@dataclass(frozen=True, slots=True)
class Comparison:
    month: str
    building: str
    status: str
    current_milli_text: str
    prior_month: str | None
    prior_milli_text: str | None
    percent_change_milli_text: str | None
    anomaly: bool

    @property
    def key(self) -> str:
        return f"{self.month}/{self.building}"

    def to_public_dict(self) -> dict[str, object]:
        return {
            "current_kwh": format_milli(self.current_milli_text),
            "prior_month": self.prior_month,
            "prior_kwh": (
                None
                if self.prior_milli_text is None
                else format_milli(self.prior_milli_text)
            ),
            "comparison_status": self.status,
            "percent_change": (
                None
                if self.percent_change_milli_text is None
                else format_milli(self.percent_change_milli_text)
            ),
            "anomaly": self.anomaly,
        }


@dataclass(frozen=True, slots=True)
class DatasetCandidate:
    dataset_id: str
    source_bytes: bytes
    source_sha256: str
    canonical_sha256: str
    record_id: str
    criterion_version: str
    rows: tuple[EnergyRow, ...]
    monthly_totals: tuple[tuple[str, str], ...]
    comparisons: tuple[Comparison, ...]
    anomalies: tuple[str, ...]

    def to_public_dict(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "record_id": self.record_id,
            "source_sha256": self.source_sha256,
            "canonical_sha256": self.canonical_sha256,
            "criterion_version": self.criterion_version,
            "rows": [row.to_public_dict() for row in self.rows],
            "monthly_totals_kwh": {
                month: format_milli(total)
                for month, total in self.monthly_totals
            },
            "building_comparisons": {
                comparison.key: comparison.to_public_dict()
                for comparison in self.comparisons
            },
            "anomalies": list(self.anomalies),
        }


def _canonical_unsigned_integer_text(digits: str) -> str:
    canonical = digits.lstrip("0")
    return canonical or "0"


def canonical_integer_text(value: str) -> str:
    """Canonicalize signed decimal integer text without Python ``int``."""

    sign = ""
    digits = value
    if value.startswith("-"):
        sign = "-"
        digits = value[1:]
    if not digits or not digits.isascii() or not digits.isdigit():
        raise ValueError("value must be signed decimal integer text")
    canonical = _canonical_unsigned_integer_text(digits)
    return sign + canonical if sign and canonical != "0" else canonical


def format_milli(value: str) -> str:
    """Serialize canonical integer-thousandths text without bounded conversion."""

    canonical = canonical_integer_text(value)
    sign = ""
    digits = canonical
    if canonical.startswith("-"):
        sign = "-"
        digits = canonical[1:]
    padded = digits.zfill(4)
    return f"{sign}{padded[:-3]}.{padded[-3:]}"


def previous_month(month: str) -> str:
    year = int(month[:4])
    number = int(month[5:])
    if number == 1:
        year -= 1
        number = 12
    else:
        number -= 1
    return f"{year:04d}-{number:02d}"


def _parse_kwh_milli(token: str) -> str:
    match = _KWH.fullmatch(token)
    if match is None:
        raise AssertionError("kWh token must be validated before conversion")
    whole = match.group(1)
    fraction = (match.group(2) or "").ljust(3, "0")
    return _canonical_unsigned_integer_text(whole + fraction)


def _add_unsigned_integer_text(left: str, right: str) -> str:
    """Add arbitrary-length canonical digit strings using bounded digit work."""

    left_index = len(left) - 1
    right_index = len(right) - 1
    carry = 0
    reversed_result: list[str] = []
    while left_index >= 0 or right_index >= 0 or carry:
        left_digit = ord(left[left_index]) - 48 if left_index >= 0 else 0
        right_digit = ord(right[right_index]) - 48 if right_index >= 0 else 0
        total = left_digit + right_digit + carry
        reversed_result.append(chr(48 + total % 10))
        carry = total // 10
        left_index -= 1
        right_index -= 1
    return "".join(reversed(reversed_result))


def _quantized_decimal_to_milli_text(value: Decimal) -> str:
    rendered = format(value, "f")
    sign = ""
    if rendered.startswith("-"):
        sign = "-"
        rendered = rendered[1:]
    whole, separator, fraction = rendered.partition(".")
    if separator != "." or len(fraction) != 3:
        raise CalculationError()
    return canonical_integer_text(sign + whole + fraction)


def _canonical_rows_bytes(rows: tuple[EnergyRow, ...]) -> bytes:
    value = [
        {
            "building": row.building,
            "kwh": format_milli(row.kwh_milli_text),
            "month": row.month,
        }
        for row in sorted(rows, key=lambda item: (item.month, item.building))
    ]
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def make_record_id(
    dataset_id: str, canonical_sha256: str, criterion_version: str = CRITERION_VERSION
) -> str:
    material = json.dumps(
        {
            "canonical_sha256": canonical_sha256,
            "criterion_version": criterion_version,
            "dataset_id": dataset_id,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return "sha256:" + hashlib.sha256(material).hexdigest()


def candidate_from_parts(
    *,
    dataset_id: str,
    source_bytes: bytes,
    source_sha256: str,
    canonical_sha256: str,
    criterion_version: str,
    rows: tuple[EnergyRow, ...],
    monthly_totals: tuple[tuple[str, str], ...],
    comparisons: tuple[Comparison, ...],
) -> DatasetCandidate:
    """Rebuild one previously validated immutable candidate from persistence."""

    anomalies = tuple(item.key for item in comparisons if item.anomaly)
    return DatasetCandidate(
        dataset_id=dataset_id,
        source_bytes=source_bytes,
        source_sha256=source_sha256,
        canonical_sha256=canonical_sha256,
        record_id=make_record_id(dataset_id, canonical_sha256, criterion_version),
        criterion_version=criterion_version,
        rows=rows,
        monthly_totals=monthly_totals,
        comparisons=comparisons,
        anomalies=anomalies,
    )


def _read_csv(text: str, line_ending: str) -> list[list[str]]:
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        records: list[list[str]] = []
        previous_line = 0
        for record in reader:
            consumed = reader.line_num - previous_line
            previous_line = reader.line_num
            if consumed != 1:
                raise DomainError("INVALID_ROW_SHAPE")
            records.append(record)
    except csv.Error as error:
        raise DomainError("INVALID_ROW_SHAPE") from error

    # csv.reader does not emit a record for one permitted terminal separator.
    # More than one terminal separator still creates a blank physical record.
    if text.endswith(line_ending + line_ending):
        raise DomainError("INVALID_ROW_SHAPE")
    return records


def parse_dataset(dataset_id: str, source_bytes: bytes) -> DatasetCandidate:
    """Validate, canonicalize and derive an immutable synthetic dataset."""

    if not isinstance(source_bytes, bytes):
        raise TypeError("source_bytes must be bytes")
    try:
        text = source_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise DomainError("INVALID_UTF8") from error

    if "\ufeff" in text:
        raise DomainError("INVALID_CSV_BOM")

    without_crlf = source_bytes.replace(b"\r\n", b"")
    if b"\r" in without_crlf:
        raise DomainError("INVALID_CSV_LINE_ENDING")
    has_crlf = b"\r\n" in source_bytes
    has_lf = b"\n" in without_crlf
    if has_crlf and has_lf:
        raise DomainError("INVALID_CSV_LINE_ENDING")

    if not isinstance(dataset_id, str) or _DATASET_ID.fullmatch(dataset_id) is None:
        raise DomainError("INVALID_DATASET_ID")

    line_ending = "\r\n" if has_crlf else "\n"
    if text.split(line_ending, 1)[0] != "month,building,kwh":
        raise DomainError("INVALID_HEADER")
    records = _read_csv(text, line_ending)
    if not records or records[0] != ["month", "building", "kwh"]:
        raise DomainError("INVALID_HEADER")
    if len(records) == 1:
        raise DomainError("EMPTY_DATASET")

    raw_rows = records[1:]
    if any(len(row) != 3 for row in raw_rows):
        raise DomainError("INVALID_ROW_SHAPE")

    # Apply the catalog's numeric priority across the complete payload.
    if any(_MONTH.fullmatch(row[0]) is None for row in raw_rows):
        raise DomainError("INVALID_MONTH")
    if any(_BUILDING.fullmatch(row[1]) is None for row in raw_rows):
        raise DomainError("INVALID_BUILDING")
    if any(_NEGATIVE_KWH.fullmatch(row[2]) is not None for row in raw_rows):
        raise DomainError("NEGATIVE_KWH")
    if any(_SCALE_EXCEEDED.fullmatch(row[2]) is not None for row in raw_rows):
        raise DomainError("KWH_SCALE_EXCEEDED")
    if any(_KWH.fullmatch(row[2]) is None for row in raw_rows):
        raise DomainError("INVALID_KWH_FORMAT")

    rows = tuple(
        EnergyRow(
            ordinal=index,
            month=row[0],
            building=row[1],
            kwh_token=row[2],
            kwh_milli_text=_parse_kwh_milli(row[2]),
        )
        for index, row in enumerate(raw_rows, start=1)
    )

    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row.month, row.building)
        if key in seen:
            raise DomainError("DUPLICATE_MONTH_BUILDING")
        seen.add(key)

    canonical_bytes = _canonical_rows_bytes(rows)
    canonical_sha256 = hashlib.sha256(canonical_bytes).hexdigest()
    totals: dict[str, str] = {}
    by_key: dict[tuple[str, str], EnergyRow] = {}
    for row in rows:
        totals[row.month] = _add_unsigned_integer_text(
            totals.get(row.month, "0"), row.kwh_milli_text
        )
        by_key[(row.month, row.building)] = row

    comparisons: list[Comparison] = []
    for row in sorted(rows, key=lambda item: (item.month, item.building)):
        prior_month = previous_month(row.month)
        prior = by_key.get((prior_month, row.building))
        if prior is None:
            comparisons.append(
                Comparison(
                    month=row.month,
                    building=row.building,
                    status="NO_PRIOR_MONTH",
                    current_milli_text=row.kwh_milli_text,
                    prior_month=None,
                    prior_milli_text=None,
                    percent_change_milli_text=None,
                    anomaly=False,
                )
            )
            continue
        if prior.kwh_milli_text == "0":
            comparisons.append(
                Comparison(
                    month=row.month,
                    building=row.building,
                    status="ZERO_BASELINE",
                    current_milli_text=row.kwh_milli_text,
                    prior_month=prior_month,
                    prior_milli_text=prior.kwh_milli_text,
                    percent_change_milli_text=None,
                    anomaly=False,
                )
            )
            continue
        try:
            with localcontext() as context:
                context.prec = 50
                percent = (
                    (Decimal(row.kwh_milli_text) - Decimal(prior.kwh_milli_text))
                    / Decimal(prior.kwh_milli_text)
                    * Decimal(100)
                ).quantize(Decimal("0.001"), rounding=ROUND_HALF_EVEN)
        except DecimalException as error:
            raise CalculationError() from error
        percent_milli_text = _quantized_decimal_to_milli_text(percent)
        comparisons.append(
            Comparison(
                month=row.month,
                building=row.building,
                status="COMPARED",
                current_milli_text=row.kwh_milli_text,
                prior_month=prior_month,
                prior_milli_text=prior.kwh_milli_text,
                percent_change_milli_text=percent_milli_text,
                anomaly=percent > THRESHOLD_PERCENT,
            )
        )

    comparison_tuple = tuple(comparisons)
    return DatasetCandidate(
        dataset_id=dataset_id,
        source_bytes=source_bytes,
        source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        canonical_sha256=canonical_sha256,
        record_id=make_record_id(dataset_id, canonical_sha256),
        criterion_version=CRITERION_VERSION,
        rows=rows,
        monthly_totals=tuple(
            (month, total)
            for month, total in sorted(totals.items())
        ),
        comparisons=comparison_tuple,
        anomalies=tuple(item.key for item in comparison_tuple if item.anomaly),
    )
