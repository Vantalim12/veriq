import copy
import json
from pathlib import Path

import pytest
import yaml

from veriq.contracts import Policy, Predicate
from veriq.ingestion import InputError, MAX_BYTES, load_json, read_policy, read_workflow
from veriq.semantics import satisfiable
from veriq.verifier import evaluate, verify

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"
EXAMPLES = ROOT / "examples"
CASES = json.loads((FIXTURES / "cases.json").read_text())


@pytest.fixture
def policy():
    return read_policy(EXAMPLES / "veriq.rules.yaml")


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_labeled_workflows(case):
    rules, policy_hash = read_policy(FIXTURES / case["rules"])
    workflow = read_workflow(FIXTURES / case["workflow"])
    report = verify(workflow, rules, policy_hash)
    actual = {item["rule_id"]: item["verdict"] for item in report["findings"]}
    assert actual == case["expected"]
    assert report["summary"]["exit_code"] == (1 if "FAIL" in actual.values() else 0)
    for item in report["findings"]:
        evidence = item["evidence"]
        assert set(evidence.get("nodes", [])) <= workflow.nodes.keys()
        for route in evidence.get("counterexamples", []):
            assert len(route["path_edges"]) == len(route["nodes"]) - 1
            for index, edge in enumerate(route["path_edges"]):
                assert edge in [connection.record() for connection in workflow.edges]
                assert (edge["source"], edge["target"]) == tuple(route["nodes"][index:index + 2])
        if "parameter_pointer" in evidence:
            data = json.loads((FIXTURES / case["workflow"]).read_text())
            for part in evidence["parameter_pointer"].lstrip("/").split("/"):
                data = data[int(part)] if isinstance(data, list) else data[part]
            assert isinstance(data, dict)


def test_counterexample_and_regression(policy):
    rules, policy_hash = policy
    baseline = read_workflow(EXAMPLES / "purchase-v1.json")
    candidate = read_workflow(EXAMPLES / "purchase-v2.json")
    report = verify(candidate, rules, policy_hash, baseline)
    first = report["findings"][0]
    assert first["verdict"] == "FAIL"
    assert first["regression"] == "INTRODUCED"
    assert first["evidence"]["counterexample_path"] == ["intake", "intake-route", "threshold", "fulfillment"]
    assert first["evidence"]["path_edges"][-1]["output_index"] == 0
    assert report["summary"]["exit_code"] == 1


@pytest.mark.parametrize("name", ["name-only-change", "node-order-change", "canvas-only-change"])
def test_nonmaterial_edits_preserve_semantics(policy, name):
    rules, policy_hash = policy
    baseline = read_workflow(EXAMPLES / "purchase-v1.json")
    candidate = read_workflow(FIXTURES / (name + ".json"))
    report = verify(candidate, rules, policy_hash, baseline)
    assert baseline.graph_hash == candidate.graph_hash
    assert report["summary"]["exit_code"] == 0
    assert {item["regression"] for item in report["findings"]} == {"PERSISTING"}


def test_repeatable_canonical_audit(policy):
    rules, policy_hash = policy
    baseline = read_workflow(EXAMPLES / "purchase-v1.json")
    candidate = read_workflow(EXAMPLES / "purchase-v2.json")
    runs = [verify(candidate, rules, policy_hash, baseline) for _ in range(3)]
    assert runs[0] == runs[1] == runs[2]


def test_standalone_and_persisting_failure_policies(policy):
    rules, policy_hash = policy
    broken = read_workflow(EXAMPLES / "purchase-v2.json")
    standalone = verify(broken, rules, policy_hash)
    assert standalone["summary"]["exit_code"] == 1
    assert standalone["baseline_hash"] is None
    assert all(item["regression"] is None for item in standalone["findings"])
    assert verify(broken, rules, policy_hash, broken)["summary"]["exit_code"] == 0
    assert verify(broken, rules, policy_hash, broken, fail_on_all=True)["summary"]["exit_code"] == 1


def test_resolved_failure(policy):
    rules, policy_hash = policy
    good = read_workflow(EXAMPLES / "purchase-v1.json")
    broken = read_workflow(EXAMPLES / "purchase-v2.json")
    assert verify(good, rules, policy_hash, broken)["findings"][0]["regression"] == "RESOLVED"


@pytest.mark.parametrize("source_document", [None, {"path": "sop.pdf"}])
def test_new_path_in_an_already_failing_rule_is_introduced(policy, tmp_path, source_document):
    rules, policy_hash = policy
    rules.source_document = source_document
    old = read_workflow(EXAMPLES / "purchase-v2.json")
    data = json.loads((EXAMPLES / "purchase-v2.json").read_text())
    data["connections"]["High value purchase"]["main"][0].append({"node": "Review route", "type": "main", "index": 0})
    data["connections"]["Review route"]["main"][0] = [{"node": "Fulfillment waypoint", "type": "main", "index": 0}]
    path = tmp_path / "new-path.json"
    path.write_text(json.dumps(data))
    report = verify(read_workflow(path), rules, policy_hash, old)
    assert report["findings"][0]["regression"] == "INTRODUCED"
    assert report["findings"][0]["evidence"]["introduced_counterexamples"]
    assert report["summary"]["exit_code"] == 1


@pytest.mark.parametrize("gate_change", [{"disabled": True}, {"type": "n8n-nodes-base.code"}])
def test_disconnected_unsupported_gate_cannot_hide_bypass(policy, tmp_path, gate_change):
    rules, policy_hash = policy
    data = json.loads((EXAMPLES / "purchase-v2.json").read_text())
    next(node for node in data["nodes"] if node["id"] == "approval-gate").update(gate_change)
    path = tmp_path / "bypass.json"
    path.write_text(json.dumps(data))
    audit = verify(read_workflow(path), rules, policy_hash, read_workflow(EXAMPLES / "purchase-v1.json"))
    assert audit["findings"][0]["verdict"] == "FAIL"
    assert audit["findings"][0]["regression"] == "INTRODUCED"
    assert audit["summary"]["exit_code"] == 1


def test_missing_citations_set_review_flags(policy):
    rules, policy_hash = policy
    rules.source_document = {"path": "sop.pdf"}
    audit = verify(read_workflow(EXAMPLES / "purchase-v1.json"), rules, policy_hash)
    assert audit["summary"]["needs_review"] == len(rules.rules)
    assert all(item["review_required"] for item in audit["findings"])


def test_nonblocking_gate_on_relevant_route_remains_uncertain(policy):
    rules, policy_hash = policy
    workflow = read_workflow(EXAMPLES / "purchase-v1.json")
    workflow.nodes["approval-gate"].type = "n8n-nodes-base.noOp"
    workflow.nodes["approval-gate"].parameters = {}
    audit = verify(workflow, rules, policy_hash, strict_unknown=True)
    assert audit["findings"][0]["verdict"] == "NEEDS_REVIEW"
    assert audit["summary"]["exit_code"] == 3


def test_path_uncertainty_still_prevents_claiming_complete_comparison(policy):
    rules, policy_hash = policy
    workflow = read_workflow(FIXTURES / "failure-plus-unknown.json")
    audit = verify(workflow, rules, policy_hash, workflow, strict_unknown=True)
    assert audit["findings"][0]["verdict"] == "FAIL"
    assert audit["findings"][0]["regression"] == "UNKNOWN_IMPACT"
    assert audit["summary"]["exit_code"] == 3


def test_uncertainty_cannot_resolve_a_failure(policy):
    rules, policy_hash = policy
    broken = read_workflow(EXAMPLES / "purchase-v2.json")
    unknown = read_workflow(FIXTURES / "unknown-code.json")
    result = verify(unknown, rules, policy_hash, broken, strict_unknown=True)
    assert result["findings"][0]["regression"] == "UNKNOWN_IMPACT"
    assert result["findings"][0]["review_required"]
    assert result["summary"]["exit_code"] == 3


def test_failure_survives_unknown_paths_and_wins_exit_precedence(policy):
    rules, policy_hash = policy
    workflow = read_workflow(FIXTURES / "failure-plus-unknown.json")
    result = verify(workflow, rules, policy_hash, strict_unknown=True)
    assert result["findings"][0]["verdict"] == "FAIL"
    assert result["findings"][0]["limitations"]
    assert result["summary"]["exit_code"] == 1


def test_budget_exhaustion_cannot_pass(policy):
    rules, _ = policy
    result = evaluate(read_workflow(EXAMPLES / "purchase-v1.json"), rules, max_states=1)
    assert result[0]["verdict"] == "NEEDS_REVIEW"
    assert "path exploration state budget exhausted" in result[0]["limitations"]


@pytest.mark.parametrize("terms,expected", [
    ([("gt", 100, True), ("le", 100, True)], False),
    ([("gt", 100, True), ("lt", 101, True)], True),
    ([("eq", 100, True), ("ne", 100, True)], False),
    ([("ge", 100, True), ("le", 100, True)], True),
    ([("eq", "urgent", False), ("eq", "urgent", True)], False),
    ([("eq", "urgent", False), ("eq", "routine", False)], True),
])
def test_typed_constraint_feasibility(terms, expected):
    constraints = [(Predicate(field="amount", operator=op, value=value), truth) for op, value, truth in terms]
    assert satisfiable(constraints) is expected


@pytest.mark.parametrize("payload", [b'{"a": 1, "a": 2}', b'{"a": NaN}', b'{"a": 1e400}', b'{"a": Infinity}', b'{broken', b'[' * 33 + b']' * 33])
def test_unsafe_json_rejected(payload):
    with pytest.raises(InputError):
        load_json(payload)


def test_depth_scanner_ignores_quoted_braces():
    value = {"message": '[\\"' * 100}
    assert load_json(json.dumps(value).encode()) == value


@pytest.mark.parametrize("kind", ["duplicate-id", "duplicate-name", "dangling-edge", "too-many-nodes", "string-disabled", "too-many-edges"])
def test_invalid_exports_rejected(kind, tmp_path):
    data = json.loads((EXAMPLES / "purchase-v1.json").read_text())
    if kind == "duplicate-id":
        data["nodes"][1]["id"] = data["nodes"][0]["id"]
    elif kind == "duplicate-name":
        data["nodes"][1]["name"] = data["nodes"][0]["name"]
    elif kind == "dangling-edge":
        data["connections"]["Purchase intake"]["main"][0][0]["node"] = "missing"
    elif kind == "too-many-nodes":
        data["nodes"] *= 12
    elif kind == "string-disabled":
        data["nodes"][0]["disabled"] = "false"
    else:
        edge = data["connections"]["Purchase intake"]["main"][0][0]
        data["connections"]["Purchase intake"]["main"][0] = [edge] * 1001
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(data))
    with pytest.raises(InputError):
        read_workflow(path)


def test_oversized_input_rejected(tmp_path):
    path = tmp_path / "large.json"
    path.write_bytes(b" " * (MAX_BYTES + 1))
    with pytest.raises(InputError):
        read_workflow(path)


@pytest.mark.parametrize("payload", [
    "schema_version: 1\nschema_version: 1\n",
    "x: &anchor [1, 2]\ny: *anchor\n",
    "x: !!python/object/apply:os.system ['never execute']\n",
    "x: .nan\n",
    "x: 2026-10-16\n",
])
def test_unsafe_yaml_rejected(payload, tmp_path):
    path = tmp_path / "unsafe.yaml"
    path.write_text(payload)
    with pytest.raises(InputError):
        read_policy(path)


@pytest.mark.parametrize("kind", ["unapproved", "duplicate-rule", "wrong-field-type", "boolean-literal", "unknown-rule-field"])
def test_policy_validation(kind, tmp_path):
    data = yaml.safe_load((EXAMPLES / "veriq.rules.yaml").read_text())
    if kind == "unapproved":
        del data["rules"][0]["approved"]
    elif kind == "duplicate-rule":
        data["rules"].append(copy.deepcopy(data["rules"][0]))
    elif kind == "wrong-field-type":
        data["fields"]["body.amount"] = "string"
    elif kind == "boolean-literal":
        data["rules"][0]["when"]["value"] = True
    else:
        data["rules"][0]["auto_approve"] = True
    path = tmp_path / "invalid.rules.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(InputError):
        read_policy(path)


def test_imported_code_and_expressions_are_data(policy, tmp_path, monkeypatch):
    import socket
    monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: pytest.fail("offline verification attempted network I/O"))
    data = json.loads((FIXTURES / "unknown-code.json").read_text())
    sentinel = tmp_path / "executed"
    data["nodes"][3]["parameters"]["jsCode"] = f"__import__('pathlib').Path({str(sentinel)!r}).touch()"
    path = tmp_path / "untrusted.json"
    path.write_text(json.dumps(data))
    rules, policy_hash = policy
    assert verify(read_workflow(path), rules, policy_hash)["findings"][0]["verdict"] == "NEEDS_REVIEW"
    assert not sentinel.exists()


def test_literal_schema_version_is_not_a_boolean(policy):
    rules, _ = policy
    data = rules.model_dump()
    data["schema_version"] = True
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Policy.model_validate(data)


def test_explicit_reviewed_non_applicability(policy):
    rules, policy_hash = policy
    data = rules.model_dump()
    data["rules"][0].update(applicable=False, not_applicable_reason="Excluded from this reviewed workflow scope")
    excluded = Policy.model_validate(data)
    report = verify(read_workflow(EXAMPLES / "purchase-v2.json"), excluded, policy_hash)
    assert report["findings"][0]["verdict"] == "NOT_APPLICABLE"
    assert report["summary"]["exit_code"] == 0


def test_evidence_validation_rejects_invented_references(policy):
    from veriq.verifier import validate_evidence
    rules, policy_hash = policy
    workflow = read_workflow(EXAMPLES / "purchase-v2.json")
    report = verify(workflow, rules, policy_hash)
    report["findings"][0]["evidence"]["nodes"][0] = "invented"
    with pytest.raises(RuntimeError, match="nonexistent node"):
        validate_evidence(report["findings"], workflow)


def test_reordering_a_failed_workflow_preserves_finding_identity(policy, tmp_path):
    rules, policy_hash = policy
    baseline = read_workflow(EXAMPLES / "purchase-v2.json")
    data = json.loads((EXAMPLES / "purchase-v2.json").read_text())
    data["nodes"].reverse()
    path = tmp_path / "reordered.json"
    path.write_text(json.dumps(data))
    report = verify(read_workflow(path), rules, policy_hash, baseline)
    assert report["findings"][0]["regression"] == "PERSISTING"
    assert report["findings"][0]["fingerprint"] == report["baseline_findings"][0]["fingerprint"]


def test_trigger_cannot_be_assumed_to_accept_an_input(policy, tmp_path):
    rules, policy_hash = policy
    data = json.loads((EXAMPLES / "purchase-v1.json").read_text())
    data["nodes"][3].update(type="n8n-nodes-base.webhook", parameters={})
    path = tmp_path / "trigger-in-route.json"
    path.write_text(json.dumps(data))
    assert verify(read_workflow(path), rules, policy_hash)["findings"][0]["verdict"] == "NEEDS_REVIEW"


def test_connection_list_reordering_does_not_invent_a_new_bypass(policy, tmp_path):
    rules, policy_hash = policy
    data = json.loads((EXAMPLES / "purchase-v2.json").read_text())
    data["connections"]["High value purchase"]["main"][0].append({"node": "Review route", "type": "main", "index": 0})
    baseline_path = tmp_path / "before.json"
    baseline_path.write_text(json.dumps(data))
    data["connections"]["High value purchase"]["main"][0].reverse()
    candidate_path = tmp_path / "after.json"
    candidate_path.write_text(json.dumps(data))
    report = verify(read_workflow(candidate_path), rules, policy_hash, read_workflow(baseline_path))
    assert report["findings"][0]["regression"] == "PERSISTING"
    assert report["summary"]["exit_code"] == 0
