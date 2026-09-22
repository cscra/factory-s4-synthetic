#!/usr/bin/env python3
"""Read-only consistency checker for the public S4 G2 material.

The checker reads the proposed specification, machine-readable matrices, fixtures,
and task metadata. It never edits those inputs. With --output it writes only the
requested, deterministic result JSON.
"""
from __future__ import annotations

import argparse
import base64
import csv
from copy import deepcopy
import hashlib
import io
import json
import re
import sys
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from pathlib import Path
from typing import Any

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
KWH_RE = re.compile(r"^(0|[1-9]\d*)(\.\d{1,3})?$")
BUILDING_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def load_json(root: Path, relative: str) -> Any:
    return json.loads((root / relative).read_text(encoding="utf-8"))


def ac12_binding_mismatches(case_list: list[dict[str, Any]], invalid_cases: list[dict[str, Any]]) -> list[str]:
    """Return mismatches across the complete machine-readable AC-12 binding."""
    acceptance_by_id = {case.get("id"): case for case in case_list}
    mismatches: list[str] = []
    for invalid in invalid_cases:
        case_id = invalid.get("id")
        acceptance = acceptance_by_id.get(case_id)
        expected_binding = {
            "id": case_id,
            "kind": invalid.get("kind"),
            "dataset_id": invalid.get("dataset_id"),
            "ref": f"fixtures/G2-invalid-input-cases.json#{case_id}",
            "error": invalid.get("expected_error"),
            "status": "REJECT",
            "state": "NONE",
        }
        actual_binding = {
            "id": (acceptance or {}).get("id"),
            "kind": (acceptance or {}).get("kind"),
            "dataset_id": (acceptance or {}).get("dataset_id"),
            "ref": (acceptance or {}).get("input_file"),
            "error": ((acceptance or {}).get("expected") or {}).get("error"),
            "status": ((acceptance or {}).get("expected") or {}).get("status"),
            "state": ((acceptance or {}).get("expected") or {}).get("state_change"),
        }
        for field in expected_binding:
            if actual_binding[field] != expected_binding[field]:
                mismatches.append(f"{case_id}:{field}")
    return mismatches


def leading_bom_payload_is_valid(invalid_case: dict[str, Any]) -> bool:
    """Validate AC-12P's exact encoded wire position without mutating its input."""
    try:
        encoded = invalid_case["input"]["bytes_base64"]
        payload = base64.b64decode(encoded, validate=True)
    except (KeyError, TypeError, ValueError):
        return False
    bom = b"\xef\xbb\xbf"
    return payload.startswith(bom) and payload.count(bom) == 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, help="write the deterministic result JSON here")
    args = parser.parse_args()
    root = args.root.resolve()

    checks: list[dict[str, str]] = []
    failures: list[str] = []

    def check(check_id: str, condition: bool, detail: str) -> None:
        result = "PASS" if condition else "FAIL"
        checks.append({"id": check_id, "result": result, "detail": detail})
        if not condition:
            failures.append(f"{check_id}: {detail}")

    try:
        requirements_path = root / "specs/requirements.md"
        acceptance_path = root / "specs/acceptance.md"
        requirements = requirements_path.read_text(encoding="utf-8")
        acceptance = acceptance_path.read_text(encoding="utf-8")
        permissions = load_json(root, "specs/permissions.json")
        errors = load_json(root, "specs/error-catalog.json")
        cases_doc = load_json(root, "fixtures/G2-acceptance-cases.json")
        invalid_doc = load_json(root, "fixtures/G2-invalid-input-cases.json")
        expected = load_json(root, "fixtures/G2-expected-results.json")
        near = load_json(root, "fixtures/G2-near-threshold.json")
        tasks = load_json(root, "tasks/G2-PRODUCT.json")
        future = load_json(root, "tasks/G2-THRESHOLD-CHANGE-70.json")
    except Exception as exc:  # pragma: no cover - reported as a deterministic result
        result = {
            "schema": "factory-s4-g2-spec-oracle-result/v0.1",
            "status": "FAIL",
            "read_only": True,
            "product_code": False,
            "checks": [{"id": "LOAD", "result": "FAIL", "detail": str(exc)}],
            "failure_count": 1,
        }
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        else:
            print(json.dumps(result, indent=2))
        return 1

    required_phrases = [
        "NO_LOGIN_IN_G2",
        "identity_enforcement=NOT_PROVEN",
        "UTF-8 bytes with no BOM",
        "ordinary double-quote field quoting",
        "Embedded LF/CRLF inside a quoted field is rejected",
        "LF and CRLF record endings are both accepted",
        "^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$",
        "ROUND_HALF_EVEN",
        "quantized value",
        "333.333",
        "433.333",
    ]
    check("SPEC_REQUIRED_RULES", all(p in requirements for p in required_phrases), "required permission, wire, building, and precision rules are stated")
    check("ACCEPTANCE_BOUNDARY", "G2-AC-12A" in acceptance and "G2-AC-12R" in acceptance and "G2-AC-18" in acceptance, "split invalid cases, near-threshold case, and future gate are documented")

    roles = permissions.get("role_matrix", {})
    check("ROLE_NAMES", set(roles) == {"ANALYST", "REVIEWER"}, "role matrix has exactly ANALYST and REVIEWER")
    check("ANALYST_ACTIONS", roles.get("ANALYST") == {
        "import": "ALLOW_NEW_DATASET",
        "view_results": "ALLOW_SYNTHETIC_RESULTS",
        "view_history": "ALLOW_SYNTHETIC_HISTORY",
        "replay": "ALLOW_ATTEMPT_DATASET_REPLAY_REJECTED",
        "modify": "DENY_DIRECT_EDIT_DELETE_RECOMPUTE",
    }, "ANALYST can import/read, can only attempt replay, and cannot mutate")
    check("REVIEWER_ACTIONS", roles.get("REVIEWER") == {
        "import": "DENY_ROLE_NOT_PERMITTED",
        "view_results": "ALLOW_SYNTHETIC_RESULTS",
        "view_history": "ALLOW_SYNTHETIC_HISTORY",
        "replay": "DENY_ROLE_NOT_PERMITTED",
        "modify": "DENY_MUTATION_NOT_PERMITTED",
    }, "REVIEWER is read-only for results/history")
    check("NO_IDENTITY_CLAIM", permissions.get("identity_model") == "NO_LOGIN_IN_G2" and permissions.get("identity_enforcement") == "NOT_PROVEN", "no-login limitation is explicit")

    catalog_codes = [entry["code"] for entry in errors["codes"]]
    priorities = [entry["priority"] for entry in errors["codes"]]
    check("ERROR_CODES_UNIQUE", len(catalog_codes) == len(set(catalog_codes)), "error codes are unique")
    check("ERROR_PRIORITIES_TOTAL", priorities == sorted(priorities) and len(priorities) == len(set(priorities)), "error priority order is total and deterministic")
    check("CSV_CONTRACT_MACHINE_READABLE", errors["csv_contract"] == {
        "encoding": "UTF-8 strict",
        "bom": "BOM is not accepted at the start or anywhere in the payload; return INVALID_CSV_BOM.",
        "rfc4180": "Comma delimiter and ordinary double-quote field quoting are accepted; doubled quotes follow RFC 4180; embedded LF/CRLF inside a quoted field is rejected as INVALID_ROW_SHAPE; backslash is not an escape.",
        "line_endings": "LF and CRLF are each accepted as record separators; bare CR and mixed LF/CRLF are rejected.",
        "blank_records": "Blank records are INVALID_ROW_SHAPE; one terminal record separator is allowed; header-only is EMPTY_DATASET.",
    }, "UTF-8/BOM/RFC4180/line-ending/blank-record choices are fixed")

    # Primary CSV and arithmetic oracle.
    primary_bytes = (root / "fixtures/G2-valid.csv").read_bytes()
    check("PRIMARY_NO_BOM", not primary_bytes.startswith(b"\xef\xbb\xbf"), "primary fixture is UTF-8 without BOM")
    rows = list(csv.DictReader(io.StringIO(primary_bytes.decode("utf-8")), strict=True))
    check("PRIMARY_SHAPE", rows and set(rows[0]) == {"month", "building", "kwh"} and all(len(r) == 3 for r in rows), "primary CSV has exact month/building/kwh columns")
    totals: dict[str, Decimal] = {}
    values: dict[tuple[str, str], Decimal] = {}
    for row in rows:
        totals[row["month"]] = totals.get(row["month"], Decimal("0")) + Decimal(row["kwh"])
        values[(row["month"], row["building"])] = Decimal(row["kwh"])
    check("PRIMARY_TOTALS", totals == {"2026-01": Decimal("300"), "2026-02": Decimal("370")}, "primary monthly totals are 300 and 370 kWh")
    with localcontext() as ctx:
        ctx.prec = 50
        a_display = ((values[("2026-02", "A")] - values[("2026-01", "A")]) / values[("2026-01", "A")] * Decimal("100")).quantize(Decimal("0.001"), rounding=ROUND_HALF_EVEN)
        b_display = ((values[("2026-02", "B")] - values[("2026-01", "B")]) / values[("2026-01", "B")] * Decimal("100")).quantize(Decimal("0.001"), rounding=ROUND_HALF_EVEN)
    check("PRIMARY_PERCENTAGES", a_display == Decimal("60.000") and b_display == Decimal("5.000"), "primary percentages are 60.000 and 5.000")
    check("PRIMARY_ORACLE", expected["anomalies"] == ["2026-02/A"] and expected["building_comparisons"]["2026-02/A"]["anomaly"] is True and expected["building_comparisons"]["2026-02/B"]["anomaly"] is False, "only A is anomalous in the primary sample")
    check("PRIMARY_POLICY", expected["numeric_policy"]["threshold_comparison_basis"] == "QUANTIZED_DECIMAL_0.001" and expected["numeric_policy"]["percentage_display_rounding"] == "ROUND_HALF_EVEN" and expected["numeric_policy"]["percentage_context_precision"] == 50, "primary oracle fixes quantization, rounding, and precision")

    # Near-threshold oracle: quantize first, then compare.
    prior = Decimal("333.333")
    current = Decimal("433.333")
    with localcontext() as ctx:
        ctx.prec = 50
        unquantized = ((current - prior) / prior) * Decimal("100")
        display = unquantized.quantize(Decimal("0.001"), rounding=ROUND_HALF_EVEN)
    fraction_ok = near["expected"]["percent_change_exact_fraction"] == {"numerator": "10000000", "denominator": "333333"}
    check("NEAR_THRESHOLD_UNIQUE", unquantized > Decimal("30") and display == Decimal("30.000") and near["expected"]["anomaly"] is False and fraction_ok, "333.333 to 433.333 quantizes to 30.000 and is not anomalous")
    check("NEAR_THRESHOLD_BASIS", near["expected"]["threshold_comparison_basis"] == "QUANTIZED_DECIMAL_0.001" and near["expected"]["rounding"] == "ROUND_HALF_EVEN" and near["expected"]["decimal_context_precision"] == 50, "near-threshold basis is machine-readable")

    # Invalid cases and one-error/replay invariants.
    invalid_ids = [case["id"] for case in invalid_doc["cases"]]
    case_list = cases_doc["cases"]
    case_ids = [case["id"] for case in case_list]
    check("CASE_IDS_UNIQUE", len(case_ids) == len(set(case_ids)), "acceptance case IDs are unique")
    invalid_case_map = {case["id"]: case for case in case_list if case["id"].startswith("G2-AC-12")}
    check("AC12_SPLIT", set(invalid_ids) == set(invalid_case_map) and len(invalid_ids) == 18, "AC-12 is split into 18 machine-checkable one-input cases")
    error_set = set(catalog_codes)
    check("INVALID_CODES_MAPPED", all(case["expected_error"] in error_set for case in invalid_doc["cases"]), "every invalid fixture maps to a catalog code")
    check("AC12_ONE_ERROR", all(case["expected"].get("error") in error_set and isinstance(case["expected"].get("error"), str) and "errors" not in case["expected"] for case in invalid_case_map.values()), "each AC-12 case has exactly one expected error")
    replay_cases = {case["id"]: case for case in case_list if case["id"] in {"G2-AC-05", "G2-AC-06", "G2-AC-14"}}
    replay_ok = all(isinstance(case.get("expected", {}).get("error"), str) and "errors" not in case.get("expected", {}) and "#" in case.get("input_file", "") for case in replay_cases.values())
    check("REPLAY_ONE_VARIANT", set(replay_cases) == {"G2-AC-05", "G2-AC-06", "G2-AC-14"} and replay_ok, "each replay scenario has one fragment and one error")

    # Cross-reference fixture fragments and required special cases.
    for case in case_list:
        ref = case.get("input_file")
        if not ref:
            continue
        path_text = ref.split("#", 1)[0]
        if not (root / path_text).is_file():
            failures.append(f"FIXTURE_REF:{case['id']}:missing {path_text}")
    check("FIXTURE_REFS", not any(item.startswith("FIXTURE_REF:") for item in failures), "acceptance fixture references resolve")
    ac18 = next((case for case in case_list if case["id"] == "G2-AC-18"), {})
    ac19 = next((case for case in case_list if case["id"] == "G2-AC-19"), {})
    check("SPECIAL_CASES", ac18.get("expected", {}).get("anomaly") is False and ac19.get("kind") == "QUOTED_ORDINARY_FIELDS", "near-threshold and ordinary-quote cases are present")
    ac16 = next((case for case in case_list if case["id"] == "G2-AC-16"), {})
    ac17 = next((case for case in case_list if case["id"] == "G2-AC-17"), {})
    check(
        "ROLE_CASE_BINDINGS",
        ac16.get("role") == "ANALYST"
        and ac16.get("input_file") == "specs/permissions.json#ANALYST"
        and ac17.get("role") == "REVIEWER"
        and ac17.get("input_file") == "specs/permissions.json#REVIEWER",
        "acceptance role cases use the machine-readable uppercase role keys",
    )
    binding_mismatches = ac12_binding_mismatches(case_list, invalid_doc["cases"])
    check("AC12_BINDINGS", not binding_mismatches, "each split invalid case mirrors id, kind, dataset, ref, error, status, and state")
    ac12p = next((case for case in invalid_doc["cases"] if case.get("id") == "G2-AC-12P"), {})
    check("AC12P_BOM_POSITION", leading_bom_payload_is_valid(ac12p), "AC-12P base64 payload starts with one UTF-8 BOM and contains no second BOM")
    # Prove the two critical guards reject tampering, using only in-memory copies.
    mutated_cases = deepcopy(case_list)
    mutated_ac12p = next(case for case in mutated_cases if case.get("id") == "G2-AC-12P")
    mutated_ac12p["kind"] = "BOM_IN_MIDDLE"
    kind_mutation_rejected = bool(ac12_binding_mismatches(mutated_cases, invalid_doc["cases"]))
    mutated_invalid_cases = deepcopy(invalid_doc["cases"])
    mutated_invalid_ac12p = next(case for case in mutated_invalid_cases if case.get("id") == "G2-AC-12P")
    mutated_invalid_ac12p["input"]["bytes_base64"] = base64.b64encode(b"month,building,kwh\n2026-01,A,1\n").decode("ascii")
    position_mutation_rejected = not leading_bom_payload_is_valid(mutated_invalid_ac12p)
    check("MUTATION_NEGATIVE_SELF_TEST", kind_mutation_rejected and position_mutation_rejected, "in-memory wrong-kind and wrong-byte-position mutations fail closed")
    check("QUOTED_CASE_ID", ac19.get("dataset_id") == "g2-quoted-fields", "ordinary quoted-field case has its own dataset identity")

    # Task/gate and pending-binding invariants.
    binding = tasks.get("issue_binding", {})
    future_binding = future.get("issue_binding", {})
    check("CURRENT_TASK_SCOPE", tasks.get("material_change") is False and tasks.get("implementation_authorized") is False and tasks.get("prototype_authorized") is False, "G2-PRODUCT remains preparation-only")
    task_refs = tasks.get("acceptance_refs", [])
    check("TASK_ACCEPTANCE_REFS", bool(task_refs) and all((root / ref).is_file() for ref in task_refs), "every G2-PRODUCT acceptance reference resolves")
    check("PENDING_BINDINGS", binding.get("status") == "PENDING_OWNER_PAGE" and binding.get("issue_id") is None and binding.get("source_commit") is None, "current G2 binding remains pending")
    check("FUTURE_GATE_SEPARATE", future.get("material_change") is True and future.get("included_in_current_g2_approval") is False and future.get("decision") is None and future_binding.get("issue_id") is None, "30 to 70 remains an independent undecided gate")

    input_paths = [
        "README.md", "PUBLIC-SCOPE.md", "specs/requirements.md", "specs/acceptance.md", "specs/permissions.json", "specs/error-catalog.json",
        "tasks/G2-PRODUCT.json", "tasks/G2-THRESHOLD-CHANGE-70.json", "fixtures/G2-valid.csv",
        "fixtures/G2-duplicate.csv", "fixtures/G2-invalid-month.csv", "fixtures/G2-negative.csv", "fixtures/G2-replay.json",
        "fixtures/G2-expected-results.json", "fixtures/G2-acceptance-cases.json", "fixtures/G2-invalid-input-cases.json",
        "fixtures/G2-near-threshold.json", "fixtures/G2-quoted-fields.json",
        "submissions/SUB-S4-G2-001/delegation.json", "checks/g2_spec_oracle_check.py",
    ]
    input_hashes = []
    for relative in input_paths:
        data = (root / relative).read_bytes()
        input_hashes.append({"path": relative, "sha256": hashlib.sha256(data).hexdigest()})

    result = {
        "schema": "factory-s4-g2-spec-oracle-result/v0.1",
        "status": "PASS" if not failures else "FAIL",
        "read_only": True,
        "product_code": False,
        "checker": "checks/g2_spec_oracle_check.py",
        "input_hashes": input_hashes,
        "checks": checks,
        "failure_count": len(failures),
    }
    if failures:
        result["failures"] = failures
    payload = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8", newline="\n")
    else:
        print(payload, end="")
    if failures:
        if args.output:
            print("\n".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
