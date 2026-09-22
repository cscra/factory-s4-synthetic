#!/usr/bin/env python3
"""Exercise the G2 Control binding against the real local Control readers.

This is a read-only synthetic check.  It constructs the future G2 runtime
task, its approved G1 parent, and the five registered source refs consumed by
``resolve_action_context`` and ``GitHubSources``.  The frozen public
delegation is deliberately expected to be rejected by the runtime equality
check; the separate control-delegation supplement must be accepted.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
CONTROL_ROOT = ROOT.parent / "control"
if str(CONTROL_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(CONTROL_ROOT / "src"))

from factory_v07.contracts import canonical_bytes  # noqa: E402
from factory_v07.github_sources import GitHubSources  # noqa: E402
from factory_v07.registry import _validate_task, resolve_action_context  # noqa: E402


FROZEN = "33f85f2656a561534f875ee5e690a4233d95aec6"
G1_COMMIT = "d22e8c591309b5a555d04474e5e172159b008afc"
G1_RECORD_COMMIT = "66eaabfad418e8f2e2722b63129488db5e91282e"
RECORD_REPOSITORY = "1378320648"
MATERIAL_REPOSITORY = "1380306809"
G2_ISSUE_ID = 5534844760
G2_ISSUE_NUMBER = 4
G2_HUMAN_ID = 31118604
G2_ISSUE_API_URL = (
    "https://api.github.com/repos/cscra/factory-control-records/issues/4"
)
G1_ISSUE_ID = 5533844036
G1_ISSUE_NUMBER = 3
G1_ISSUE_API_URL = (
    "https://api.github.com/repos/cscra/factory-control-records/issues/3"
)


def git_bytes(commit: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{commit}:{path}"],
        check=False,
        capture_output=True,
    )
    if result.returncode:
        raise RuntimeError(f"cannot read {commit}:{path}: {result.stderr.decode()}")
    return result.stdout


def current_commit() -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
    ).strip()


def source_ref(path: str, commit: str, raw: bytes) -> dict:
    return {
        "repository_id": MATERIAL_REPOSITORY,
        "commit": commit,
        "path": path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


class SyntheticAPI:
    """GET-only in-memory provider for the two public synthetic issues."""

    def __init__(self, payloads: dict[tuple[str, str], bytes]):
        self.payloads = payloads
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, path: str, data=None):
        self.calls.append((method, path))
        if "/contents/" in path:
            source_path, ref = path.split("/contents/", 1)[1].split("?ref=", 1)
            source_path = unquote(source_path)
            raw = self.payloads[(source_path, ref)]
            return {
                "type": "file",
                "path": source_path,
                "encoding": "base64",
                "content": base64.b64encode(raw).decode("ascii"),
            }, {}
        issue = {
            (G1_ISSUE_NUMBER, G1_ISSUE_ID, G1_ISSUE_API_URL),
            (G2_ISSUE_NUMBER, G2_ISSUE_ID, G2_ISSUE_API_URL),
        }
        for number, issue_id, api_url in issue:
            base = f"/repositories/{RECORD_REPOSITORY}/issues/{number}"
            if path == base:
                return {
                    "id": issue_id,
                    "number": number,
                    "comments": 0,
                    "updated_at": "2026-09-22T00:00:00Z",
                }, {}
            if path == base + "/comments?per_page=100&page=1":
                return [], {}
        raise AssertionError((method, path, data))


def build_task(
    *,
    task_ref: str,
    required_gate: str,
    submission: str,
    source_commit: str,
    issue_id: int,
    issue_number: int,
    issue_api_url: str,
    delegation_ref: str,
    source_refs: list[dict],
    parent_task_refs: list[str],
    activity: str,
) -> dict:
    task_source, submission_source, manifest_source, review_source, delegation_source = source_refs
    task = {
        "project_ref": "S4-P-001",
        "task_ref": task_ref,
        "task_revision_ref": "R1",
        "delegation_ref": delegation_ref,
        "principal_ref": "WORK",
        "host_ref": "S4-SYNTHETIC-HOST",
        "ruleset_ref": "RULES-v07-s4.1",
        "activity": activity,
        "allowed_actions": ["CHECK_READY", "START"],
        "required_gate": required_gate,
        "submission": submission,
        "source_commit": source_commit,
        "material_repository_id": MATERIAL_REPOSITORY,
        "manifest_path": f"submissions/{submission}/manifest.json",
        "issue_id": issue_id,
        "decision_repository_id": RECORD_REPOSITORY,
        "issue_number": issue_number,
        "issue_api_url": issue_api_url,
        "human_ids": [31118604],
        "parent_task_refs": parent_task_refs,
        "registered_source_refs": source_refs,
        "input_refs": [task_source],
        "task_source": task_source,
        "submission_source": submission_source,
        "manifest_source": manifest_source,
        "review_source": review_source,
        "delegation_source": delegation_source,
        "decision_ancestors": [],
        "change_sources": [],
        "delegation": {
            "principal_ref": "WORK",
            "role": "BUILDER",
            "task_ref": task_ref,
        },
    }
    return task


def build_case(delegation_path: Path) -> tuple[dict, dict, dict]:
    current = current_commit()
    payloads: dict[tuple[str, str], bytes] = {}

    def ref(path: str, commit: str, raw: bytes) -> dict:
        payloads[(path, commit)] = raw
        return source_ref(path, commit, raw)

    g1_task_path = "tasks/G1-PRODUCT.json"
    g1_submission_path = "submissions/SUB-S4-G1-001/submission.json"
    g1_manifest_path = "submissions/SUB-S4-G1-001/manifest.json"
    g1_review_path = "submissions/SUB-S4-G1-001/review.json"
    g1_delegation_path = "submissions/SUB-S4-G1-001/delegation.json"
    g1_refs = [
        ref(g1_task_path, G1_COMMIT, git_bytes(G1_COMMIT, g1_task_path)),
        ref(g1_submission_path, G1_RECORD_COMMIT, git_bytes(G1_RECORD_COMMIT, g1_submission_path)),
        ref(g1_manifest_path, G1_COMMIT, git_bytes(G1_COMMIT, g1_manifest_path)),
        ref(g1_review_path, G1_RECORD_COMMIT, git_bytes(G1_RECORD_COMMIT, g1_review_path)),
        ref(g1_delegation_path, G1_COMMIT, git_bytes(G1_COMMIT, g1_delegation_path)),
    ]
    g1 = build_task(
        task_ref="G1-PRODUCT",
        required_gate="G1",
        submission="SUB-S4-G1-001",
        source_commit=G1_COMMIT,
        issue_id=G1_ISSUE_ID,
        issue_number=G1_ISSUE_NUMBER,
        issue_api_url=G1_ISSUE_API_URL,
        delegation_ref="DEL-S4-G1-PRODUCT-R1",
        source_refs=g1_refs,
        parent_task_refs=[],
        activity="PRODUCT_DEFINITION",
    )

    g2_task_path = "tasks/G2-PRODUCT.json"
    g2_submission_path = "submissions/SUB-S4-G2-001/submission.json"
    g2_manifest_path = "submissions/SUB-S4-G2-001/manifest.json"
    g2_review_path = "submissions/SUB-S4-G2-001/review.json"
    delegation_commit = FROZEN if delegation_path.name == "delegation.json" else current
    delegation_raw = (
        git_bytes(FROZEN, str(delegation_path.relative_to(ROOT)))
        if delegation_commit == FROZEN
        else delegation_path.read_bytes()
    )
    g2_refs = [
        ref(g2_task_path, FROZEN, git_bytes(FROZEN, g2_task_path)),
        ref(g2_submission_path, current, (ROOT / g2_submission_path).read_bytes()),
        ref(g2_manifest_path, FROZEN, git_bytes(FROZEN, g2_manifest_path)),
        ref(g2_review_path, current, (ROOT / g2_review_path).read_bytes()),
        ref(str(delegation_path.relative_to(ROOT)), delegation_commit, delegation_raw),
    ]
    g2 = build_task(
        task_ref="G2-PRODUCT",
        required_gate="G2",
        submission="SUB-S4-G2-001",
        source_commit=FROZEN,
        issue_id=G2_ISSUE_ID,
        issue_number=G2_ISSUE_NUMBER,
        issue_api_url=G2_ISSUE_API_URL,
        delegation_ref="DEL-S4-G2-PRODUCT-R1",
        source_refs=g2_refs,
        parent_task_refs=["G1-PRODUCT"],
        activity="ACCEPTANCE_REVIEW",
    )
    registry = {"project_ref": "S4-P-001", "tasks": {"G1-PRODUCT": g1, "G2-PRODUCT": g2}}
    return registry, g2, payloads


def request_for(registry: dict, task: dict) -> dict:
    ordered: list[str] = []

    def visit(task_ref: str) -> None:
        for parent in registry["tasks"][task_ref]["parent_task_refs"]:
            visit(parent)
        if task_ref not in ordered:
            ordered.append(task_ref)

    visit(task["task_ref"])
    source_refs = [
        ref
        for task_ref in ordered
        for ref in registry["tasks"][task_ref]["registered_source_refs"]
    ]
    return {
        "schema": "factory-evaluate-request/v0.7-s4.1",
        "request_id": "Q-G2-CONTROL-BINDING",
        "project_ref": "S4-P-001",
        "task_ref": task["task_ref"],
        "task_revision_ref": task["task_revision_ref"],
        "delegation_ref": task["delegation_ref"],
        "principal_ref": task["principal_ref"],
        "host_ref": task["host_ref"],
        "purpose": "CONSULT",
        "action": "CHECK_READY",
        "activity": task["activity"],
        "expected_ruleset_ref": task["ruleset_ref"],
        "candidate_ref": task["source_commit"],
        "input_refs": task["input_refs"],
        "source_refs": source_refs,
        "operation_ref": "OP-G2-CONTROL-BINDING",
        "attempt_ref": "ATT-G2-CONTROL-BINDING",
        "reservation_ref": "RES-G2-CONTROL-BINDING",
        "resource_set_sha256": "a" * 64,
        "execution_intent_sha256": "b" * 64,
    }


def run_case(delegation_path: Path, expected_valid: bool) -> dict:
    registry, task, payloads = build_case(delegation_path)
    for key, value in registry["tasks"].items():
        _validate_task(value, registry["project_ref"], key)
    request = request_for(registry, task)
    context = resolve_action_context(request, registry, [])
    assert context["closure_task_refs"] == ["G1-PRODUCT", "G2-PRODUCT"]
    assert len(context["required_source_refs"]) == 10
    assert context["task"]["decision_ancestors"][0]["task_ref"] == "G1-PRODUCT"
    source_names = {name for name in context["task"] if name.endswith("_source")}
    assert source_names == {
        "task_source",
        "submission_source",
        "manifest_source",
        "review_source",
        "delegation_source",
    }
    source_refs = context["required_source_refs"]
    config = {
        "mode": "S4_ACCEPTANCE",
        "record_repository_id": RECORD_REPOSITORY,
        "source_refs": source_refs,
    }
    sources = GitHubSources(config, SyntheticAPI({}), SyntheticAPI(payloads))
    # Replace the empty record API with an issue-aware API while retaining the
    # same material payload map.  Content and issue reads remain separate.
    sources.api = SyntheticAPI(payloads)
    facts = sources.read_required({"config": context["task"]})
    assert facts.complete, facts.errors
    assert facts.current["delegation_valid"] is expected_valid
    assert facts.current["review_verified"] is True
    assert facts.current["binding"]["issue_id"] == G2_ISSUE_ID
    assert facts.current["binding"]["source_commit"] == FROZEN
    assert context["task"]["issue_number"] == G2_ISSUE_NUMBER
    assert context["task"]["issue_api_url"] == G2_ISSUE_API_URL
    assert context["task"]["human_ids"] == [G2_HUMAN_ID]
    submission = json.loads(
        (ROOT / "submissions/SUB-S4-G2-001/submission.json").read_text(encoding="utf-8")
    )
    review = json.loads(
        (ROOT / "submissions/SUB-S4-G2-001/review.json").read_text(encoding="utf-8")
    )
    binding = review["data"]["details"]["binding"]
    assert binding == submission
    assert canonical_bytes(binding) == canonical_bytes(submission)
    assert "legacy 12-field delegation.json" in review["data"]["details"]["review_text"]
    assert "control-delegation.json" in review["data"]["details"]["review_text"]
    parent = facts.current["ancestors"]
    assert len(parent) == 1 and parent[0]["config"]["task_ref"] == "G1-PRODUCT"
    assert parent[0]["complete"] is True
    assert parent[0]["current"]["delegation_valid"] is True
    assert len(context["task"]["registered_source_refs"]) == 5
    return {
        "delegation_path": str(delegation_path.relative_to(ROOT)),
        "delegation_valid": facts.current["delegation_valid"],
        "closure_task_refs": context["closure_task_refs"],
        "source_count_per_task": 5,
        "required_source_count": len(context["required_source_refs"]),
        "issue": {"id": G2_ISSUE_ID, "number": G2_ISSUE_NUMBER, "api_url": G2_ISSUE_API_URL, "human_id": G2_HUMAN_ID},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    checks: list[dict] = []
    failures: list[str] = []

    def check(check_id: str, condition: bool, detail: str, result=None) -> None:
        checks.append({"id": check_id, "result": "PASS" if condition else "FAIL", "detail": detail, **({"case": result} if result is not None else {})})
        if not condition:
            failures.append(f"{check_id}: {detail}")

    legacy_path = ROOT / "submissions/SUB-S4-G2-001/delegation.json"
    canonical_path = ROOT / "submissions/SUB-S4-G2-001/control-delegation.json"
    try:
        legacy = run_case(legacy_path, False)
        check("LEGACY_DELEGATION_RED", legacy["delegation_valid"] is False, "frozen 12-field public delegation is not a runtime delegation", legacy)
    except Exception as exc:
        check("LEGACY_DELEGATION_RED", False, f"legacy exercise errored: {type(exc).__name__}: {exc}")

    if not canonical_path.is_file():
        check("CANONICAL_SOURCE_PRESENT", False, "control-delegation.json is required")
    else:
        try:
            canonical_raw = json.loads(canonical_path.read_text(encoding="utf-8"))
            check(
                "CANONICAL_SOURCE_SHAPE",
                canonical_raw == {"principal_ref": "WORK", "role": "BUILDER", "task_ref": "G2-PRODUCT"},
                "Control source is exactly the three runtime delegation fields",
            )
            canonical = run_case(canonical_path, True)
            check("CANONICAL_DELEGATION_GREEN", canonical["delegation_valid"] is True, "Control delegation is accepted by the five-source reader", canonical)
            check("G1_PARENT_CLOSURE", canonical["closure_task_refs"] == ["G1-PRODUCT", "G2-PRODUCT"], "G2 resolves its G1 parent closure")
            check("G2_ISSUE_BINDING", canonical["issue"] == {"id": G2_ISSUE_ID, "number": G2_ISSUE_NUMBER, "api_url": G2_ISSUE_API_URL, "human_id": G2_HUMAN_ID}, "runtime task keeps exact Issue #4 and Human binding")
        except Exception as exc:
            check("CANONICAL_DELEGATION_GREEN", False, f"canonical exercise errored: {type(exc).__name__}: {exc}")

    result = {
        "schema": "factory-s4-g2-control-binding-check/v0.1",
        "status": "PASS" if not failures else "FAIL",
        "read_only": True,
        "product_code": False,
        "checks": checks,
        "failure_count": len(failures),
    }
    if failures:
        result["failures"] = failures
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
