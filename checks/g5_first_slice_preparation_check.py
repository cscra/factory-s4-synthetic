#!/usr/bin/env python3
"""Fail-closed preparation check for the bounded G5 first-slice package."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_CANDIDATE = "0f4547851c267c2094d1716ff0f1e14fc2e40bcc"
AUTHORIZED_G4_PACKAGE = "2b7ad3eec9b25a79c2a458de5aebd318366a9ea4"
OBSERVATION = "OBS-S4-G4-FIRST-SLICE-004"
MANIFEST_SHA256 = "805fb25735727046f7c5e9975623e56dc59a3a17a3c5dc2f2bb247f6f15eb89c"

PATHS = {
    "source": "evidence/g4-first-slice/source-package.json",
    "execution": "evidence/g4-first-slice/execution-summary.json",
    "attestation": "control-inputs/G4-FIRST-SLICE-execution-attestation-004.json",
    "source_verification": "control-inputs/G4-FIRST-SLICE-verification-source-004.json",
    "technical_verification": "control-inputs/G4-FIRST-SLICE-verification-technical-004.json",
    "product_verification": "control-inputs/G4-FIRST-SLICE-verification-product-004.json",
    "claim": "control-inputs/G4-FIRST-SLICE-completion-claim-004.json",
}

SOURCE_COVERAGE = {
    "SOURCE_COMMIT",
    "BUILD_INPUTS",
    "ARTIFACT_BYTES",
    "PROCESS_AND_DATABASE_IDENTITY",
}
TECHNICAL_COVERAGE = {
    "TECHNICAL_REVIEW_RECORD",
    "ONE_EXECUTION_OBSERVATION",
    "REAL_LOOPBACK_HTTP_API",
    "FIRST_SLICE_ACTOR_PREFLIGHT",
    "DENIED_ACTION_NO_MUTATION",
    "HTTP_METHOD_AND_BODY_LIMITS",
    "SQLITE_ATOMIC_IMPORT",
    "INVALID_BATCH_NO_MUTATION",
    "EXACT_DECIMAL_CALCULATION",
    "PROCESS_EXIT_RESTART_SAME_ID_RELOAD",
}
PRODUCT_COVERAGE = {
    "PRODUCT_REVIEW_RECORD",
    "ONE_EXECUTION_OBSERVATION",
    "G3_EXPERIENCE_ALIGNMENT",
    "REAL_BROWSER_CRITICAL_PATH",
    "SYNTHETIC_ONLY_SCOPE",
    "KNOWN_LIMITATIONS_DISCLOSED",
    "NO_LATER_BATCH_DEPLOYMENT_REAL_BUSINESS_ADOPTION_OR_THRESHOLD_CHANGE",
}


def load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def sha256(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def eligible(package: dict) -> tuple[bool, list[str]]:
    failures: list[str] = []
    source = package["source"]
    execution = package["execution"]
    attestation = package["attestation"]["details"]
    verifications = [item["details"] for item in package["verifications"]]
    claim = package["claim"]["details"]

    if source.get("source_commit") != SOURCE_CANDIDATE:
        failures.append("SOURCE_CANDIDATE_MISMATCH")
    if execution.get("status") != "PASS" or execution.get("terminal") is not True:
        failures.append("EXECUTION_NOT_TERMINAL_PASS")
    if execution.get("source_commit") != SOURCE_CANDIDATE:
        failures.append("EXECUTION_SOURCE_MISMATCH")
    if execution.get("observation_ref") != OBSERVATION:
        failures.append("EXECUTION_OBSERVATION_MISMATCH")
    if execution.get("private_evidence_manifest_sha256") != MANIFEST_SHA256:
        failures.append("EVIDENCE_MANIFEST_MISMATCH")

    if attestation.get("record_ref") != OBSERVATION:
        failures.append("ATTESTATION_OBSERVATION_MISMATCH")
    if attestation.get("candidate_ref") != AUTHORIZED_G4_PACKAGE:
        failures.append("AUTHORIZED_PACKAGE_MISMATCH")
    if attestation.get("status") != "SUCCESS" or attestation.get("terminal") is not True:
        failures.append("ATTESTATION_NOT_TERMINAL_SUCCESS")

    artifacts = attestation.get("artifact_refs", [])
    artifact_ids = {item.get("artifact_ref") for item in artifacts}
    roles = {item.get("role") for item in artifacts}
    if roles != {"FIRST_SLICE_SOURCE_PACKAGE", "FIRST_SLICE_EXECUTION_EVIDENCE"}:
        failures.append("OUTPUT_ROLE_SET_MISMATCH")
    expected_hashes = {
        "FIRST_SLICE_SOURCE_PACKAGE": sha256(PATHS["source"]),
        "FIRST_SLICE_EXECUTION_EVIDENCE": sha256(PATHS["execution"]),
    }
    for artifact in artifacts:
        if artifact.get("sha256") != expected_hashes.get(artifact.get("role")):
            failures.append("OUTPUT_ARTIFACT_HASH_MISMATCH")

    expected_rows = [
        ("SOURCE_AUTHENTICITY", SOURCE_COVERAGE),
        ("BUSINESS_COMPLIANCE", TECHNICAL_COVERAGE),
        ("BUSINESS_COMPLIANCE", PRODUCT_COVERAGE),
    ]
    verification_refs: list[str] = []
    for verification, (purpose, coverage) in zip(verifications, expected_rows, strict=True):
        verification_refs.append(verification.get("record_ref"))
        if verification.get("observation_ref") != OBSERVATION:
            failures.append("VERIFICATION_OBSERVATION_MISMATCH")
        if verification.get("candidate_ref") != AUTHORIZED_G4_PACKAGE:
            failures.append("VERIFICATION_PACKAGE_MISMATCH")
        if verification.get("purpose") != purpose or not coverage.issubset(
            set(verification.get("coverage", []))
        ):
            failures.append("VERIFICATION_COVERAGE_MISMATCH")
        if verification.get("result") != "PASS":
            failures.append("VERIFICATION_NOT_PASS")
        if verification.get("independent") is not True or verification.get("authorized") is not True:
            failures.append("VERIFICATION_NOT_INDEPENDENT_AUTHORIZED")
        if set(verification.get("artifact_refs", [])) != artifact_ids:
            failures.append("VERIFICATION_ARTIFACT_SET_MISMATCH")

    if len(set(verification_refs)) != 3:
        failures.append("VERIFICATION_IDENTITIES_NOT_DISTINCT")
    if claim.get("observation_refs") != [OBSERVATION]:
        failures.append("CLAIM_REQUIRES_EXACTLY_ONE_OBSERVATION")
    if claim.get("verification_refs") != verification_refs:
        failures.append("CLAIM_VERIFICATION_SET_MISMATCH")
    if claim.get("candidate_ref") != AUTHORIZED_G4_PACKAGE:
        failures.append("CLAIM_PACKAGE_MISMATCH")
    if set(claim.get("output_roles", {})) != roles:
        failures.append("CLAIM_OUTPUT_ROLE_SET_MISMATCH")

    return not failures, sorted(set(failures))


def prepared_package() -> dict:
    return {
        "source": load(PATHS["source"]),
        "execution": load(PATHS["execution"]),
        "attestation": load(PATHS["attestation"]),
        "verifications": [
            load(PATHS["source_verification"]),
            load(PATHS["technical_verification"]),
            load(PATHS["product_verification"]),
        ],
        "claim": load(PATHS["claim"]),
    }


def main() -> int:
    package = prepared_package()
    exact_ok, exact_failures = eligible(package)
    cases: dict[str, bool] = {"exact_obs004_package_accepted": exact_ok}

    wrong_candidate = copy.deepcopy(package)
    wrong_candidate["source"]["source_commit"] = "7cd8dd0db4fd447d74fa3113b643975542cbc2f4"
    cases["historical_wrong_source_candidate_rejected"] = not eligible(wrong_candidate)[0]

    failed_observation = copy.deepcopy(package)
    failed_observation["execution"].update(
        status="FAIL", observation_ref="OBS-S4-G4-FIRST-SLICE-002"
    )
    cases["historical_failed_observation_rejected"] = not eligible(failed_observation)[0]

    multiple_observations = copy.deepcopy(package)
    multiple_observations["claim"]["details"]["observation_refs"].append(
        "OBS-S4-G4-FIRST-SLICE-003"
    )
    cases["multiple_observations_rejected"] = not eligible(multiple_observations)[0]

    collapsed_reviews = copy.deepcopy(package)
    collapsed_reviews["verifications"][2]["details"]["record_ref"] = (
        collapsed_reviews["verifications"][1]["details"]["record_ref"]
    )
    collapsed_reviews["claim"]["details"]["verification_refs"][2] = (
        collapsed_reviews["claim"]["details"]["verification_refs"][1]
    )
    cases["collapsed_technical_product_identity_rejected"] = not eligible(
        collapsed_reviews
    )[0]

    mismatched_review = copy.deepcopy(package)
    mismatched_review["verifications"][2]["details"]["observation_ref"] = (
        "OBS-S4-G4-FIRST-SLICE-003"
    )
    cases["mismatched_review_observation_rejected"] = not eligible(mismatched_review)[0]

    result = {
        "schema": "factory-s4-g5-preparation-check/v0.1",
        "status": "PASS" if all(cases.values()) else "FAIL",
        "source_candidate": SOURCE_CANDIDATE,
        "authorized_g4_package": AUTHORIZED_G4_PACKAGE,
        "eligible_observation": OBSERVATION,
        "exact_package_failures": exact_failures,
        "checks": cases,
        "input_sha256": {name: sha256(path) for name, path in PATHS.items()},
        "limits": [
            "AGENT_COMPLIANCE_PREPARATION_CONTROL",
            "DOES_NOT_CREATE_HUMAN_G5_APPROVAL",
            "DOES_NOT_REPLACE_CONTROL_FORMAL_RECORD_VALIDATION",
        ],
    }
    output = ROOT / "checks/G5-first-slice-preparation-result.json"
    output.write_text(
        json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
