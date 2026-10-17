"""Bounded per-item control-flow verification and conservative comparison."""

from collections import deque

from . import __version__
from .ingestion import MAX_BYTES, MAX_DEPTH, MAX_EDGES, MAX_ITEMS, MAX_NODES, digest
from .traceability import matrix, source_evidence
from .semantics import ADAPTER_VERSION, UnknownSemantics, node_problem, read_condition, satisfiable

MAX_STATES = 10_000
# shortcut: retain eight witnesses per rule; expand storage when larger comparisons need more detail.
MAX_COUNTEREXAMPLES = 8
MODEL_LIMITATIONS = [
    "Static per-item control-flow model; no workflow execution or external-service verification.",
    "Declared fields are assumed present, correctly typed, and unchanged across supported routing nodes.",
    "A configured Wait proves a blocking route waypoint, not manager identity or live authorization.",
]
UNKNOWN = {"NEEDS_REVIEW", "UNSUPPORTED"}


def semantic_evidence(value):
    if isinstance(value, dict):
        return {key: semantic_evidence(item) for key, item in value.items() if key not in ("parameter_pointer", "connection_index")}
    if isinstance(value, list):
        return [semantic_evidence(item) for item in value]
    return value


def finding(rule, verdict, reason, evidence=None, limitations=None):
    evidence = evidence or {}
    witness = {key: evidence[key] for key in ("nodes", "path_edges", "counterexamples", "expected", "observed", "condition_pointer") if key in evidence}
    return {"rule_id": rule.id, "title": rule.title, "verdict": verdict, "severity": rule.severity,
            "regression": None, "reason": reason, "evidence": evidence,
            "fingerprint": digest({"rule_id": rule.id, "verdict": verdict, "witness": semantic_evidence(witness), "reason": reason}),
            "limitations": sorted(set(limitations or [])),
            "coverage_complete": verdict not in UNKNOWN and not limitations,
            "review_required": verdict != "PASS"}


def condition_finding(workflow, rule, policy):
    node = workflow.nodes.get(rule.node_id)
    if node is None:
        return finding(rule, "NEEDS_REVIEW", "condition node is missing; identity mapping needs review")
    try:
        observed, constant, pointer = read_condition(node, policy.fields)
    except UnknownSemantics as exc:
        return finding(rule, "UNSUPPORTED", str(exc), {"nodes": [node.id]})
    expected = rule.condition.model_dump()
    actual = observed.model_dump() if observed else {"constant_result": constant}
    evidence = {"nodes": [node.id], "parameter_pointer": workflow.pointers[node.id] + pointer,
                "condition_pointer": pointer, "expected": expected, "observed": actual}
    passed = expected == actual
    return finding(rule, "PASS" if passed else "FAIL", "approved literal condition matches" if passed else "supported condition contradicts the approved condition", evidence)


def path_finding(workflow, rule, policy, max_states):
    source, target = rule.scope.source_node_id, rule.scope.target_node_id
    required = [source, target] + ([rule.gate_node_id] if rule.gate_node_id else [])
    if any(node_id not in workflow.nodes for node_id in required):
        return finding(rule, "NEEDS_REVIEW", "scope/control node is missing; identity mapping needs review")
    gate_issue = None
    if rule.gate_node_id:
        gate = workflow.nodes[rule.gate_node_id]
        if gate.type != "n8n-nodes-base.wait" or node_problem(gate):
            gate_issue = "reviewed control mapping requires a supported blocking Wait v1"

    reverse = {target}
    while True:
        expanded = reverse | {edge.source for edge in workflow.edges if edge.target in reverse}
        if expanded == reverse:
            break
        reverse = expanded
    if source not in reverse:
        if rule.type == "forbid_path":
            return finding(rule, "PASS", "no graph route exists between the declared endpoints", {"nodes": [source, target]})
        return finding(rule, "NEEDS_REVIEW", "no applicable source-to-target route; applicability needs review")

    constraints = [(rule.when, True)] if rule.when else []
    queue = deque([(source, [source], [], constraints, [], False, [])])
    limitations = set()
    counterexamples = []
    known_routes = 0
    explored = 0
    while queue:
        explored += 1
        if explored > max_states:
            limitations.add("path exploration state budget exhausted")
            break
        node_id, path, path_edges, terms, uncertainty, payload_changed, branches = queue.popleft()
        node = workflow.nodes[node_id]
        problem = node_problem(node)
        if problem:
            uncertainty = uncertainty + [f"{node_id}: {problem}"]
        if gate_issue and node_id == rule.gate_node_id:
            uncertainty = uncertainty + [gate_issue]
        if node_id == target:
            if uncertainty:
                limitations.update(uncertainty)
            else:
                known_routes += 1
                bypass = rule.gate_node_id not in path if rule.gate_node_id else True
                if bypass:
                    if len(counterexamples) < MAX_COUNTEREXAMPLES:
                        counterexamples.append({"nodes": path, "path_edges": [edge.record() for edge in path_edges],
                                                "branch_conditions": branches,
                                                "when": rule.when.model_dump() if rule.when else None})
                    else:
                        limitations.add("counterexample evidence capped at 8 routes; comparison coverage is incomplete")
            continue
        predicate = constant = condition_pointer = None
        if node.type == "n8n-nodes-base.if":
            try:
                predicate, constant, condition_pointer = read_condition(node, policy.fields)
                if predicate and payload_changed:
                    raise UnknownSemantics("field identity after Wait/unknown payload transformation is not established")
            except UnknownSemantics as exc:
                uncertainty = uncertainty + [f"{node_id}: {exc}"]
                predicate = constant = None
        next_payload_changed = payload_changed or bool(problem) or node.type == "n8n-nodes-base.wait"
        for edge in workflow.outgoing(node_id):
            if edge.target not in reverse:
                continue
            next_uncertainty = list(uncertainty)
            max_output = 1 if node.type == "n8n-nodes-base.if" else 0
            normal_edge = (edge.channel == "main" and edge.input_index == 0 and edge.output_index <= max_output
                           and workflow.nodes[edge.target].type != "n8n-nodes-base.webhook")
            if not normal_edge:
                next_uncertainty.append(f"{node_id}: unsupported connection channel or port")
            next_terms = terms
            next_branches = branches
            if node.type == "n8n-nodes-base.if" and normal_edge and not problem:
                truth = edge.output_index == 0
                if constant is not None and constant != truth:
                    continue
                if predicate:
                    next_terms = terms + [(predicate, truth)]
                    if not satisfiable(next_terms):
                        continue
                if predicate or constant is not None:
                    next_branches = branches + [{"node_id": node_id, "condition_pointer": condition_pointer,
                                                  "parameter_pointer": workflow.pointers[node_id] + condition_pointer,
                                                  "predicate": predicate.model_dump() if predicate else None,
                                                  "constant_result": constant, "truth": truth}]
            if edge.target in path:
                limitations.add("cycle affects source-to-target coverage")
                continue
            if explored + len(queue) >= max_states:
                limitations.add("path exploration state budget exhausted")
                continue
            queue.append((edge.target, path + [edge.target], path_edges + [edge], next_terms, next_uncertainty, next_payload_changed, next_branches))
    if counterexamples:
        counterexamples.sort(key=lambda item: (len(item["nodes"]), digest(semantic_evidence(item))))
        evidence = dict(counterexamples[0])
        evidence["counterexample_path"] = evidence["nodes"]
        evidence["counterexamples"] = counterexamples
        return finding(rule, "FAIL", "supported route bypasses the required control" if rule.gate_node_id else "supported prohibited route exists", evidence, limitations)
    if limitations:
        return finding(rule, "NEEDS_REVIEW", "relevant path semantics or exploration coverage are unresolved", {"nodes": [source, target]}, limitations)
    if rule.type == "must_pass_through" and known_routes == 0:
        return finding(rule, "NEEDS_REVIEW", "no feasible applicable route; applicability needs review")
    return finding(rule, "PASS", "all applicable supported routes satisfy the path rule", {"nodes": required})


def evaluate(workflow, policy, max_states=MAX_STATES, *, document=None):
    results = []
    for rule in policy.rules:
        if not rule.applicable:
            result = finding(rule, "NOT_APPLICABLE", "reviewed scope exclusion: " + rule.not_applicable_reason)
        else:
            result = condition_finding(workflow, rule, policy) if rule.type == "require_condition" else path_finding(workflow, rule, policy, max_states)
        if rule.source or policy.source_document:
            result["source"], limitation = source_evidence(rule, policy, document)
            if limitation:
                result["limitations"].append(limitation)
        result["review_required"] = result["verdict"] not in {"PASS", "NOT_APPLICABLE"} or bool(result["limitations"])
        results.append(result)
    return results


def classify(current, previous):
    before, after = previous["verdict"], current["verdict"]
    current["baseline_verdict"] = before
    if before in UNKNOWN or after in UNKNOWN:
        return "UNKNOWN_IMPACT"
    if before == after == "FAIL" and not (previous["coverage_complete"] and current["coverage_complete"]):
        return "UNKNOWN_IMPACT"
    if current["fingerprint"] == previous["fingerprint"]:
        return "PERSISTING"
    if after == "FAIL" and before == "PASS":
        return "INTRODUCED"
    if before == "FAIL" and after == "PASS":
        return "RESOLVED"
    if before == after == "FAIL":
        def route_id(item):
            return digest(semantic_evidence({"nodes": item["nodes"], "path_edges": item["path_edges"]}))
        old_paths = {route_id(item) for item in previous["evidence"].get("counterexamples", [])}
        new_paths = [item for item in current["evidence"].get("counterexamples", []) if route_id(item) not in old_paths]
        if new_paths:
            current["evidence"]["introduced_counterexamples"] = new_paths
            return "INTRODUCED"
    return "CHANGED"


def structural_diff(baseline, candidate):
    changes = []
    for node_id in sorted(baseline.nodes.keys() | candidate.nodes.keys()):
        old, new = baseline.nodes.get(node_id), candidate.nodes.get(node_id)
        if old is None or new is None:
            changes.append({"kind": "node_added" if old is None else "node_removed", "node_id": node_id})
            continue
        if old.name != new.name:
            changes.append({"kind": "node_renamed", "node_id": node_id})
        old_data, new_data = old.model_dump(), new.model_dump()
        for key in ("name", "position", "notes", "notesInFlow", "color"):
            old_data.pop(key, None)
            new_data.pop(key, None)
        if old_data != new_data:
            changes.append({"kind": "node_configuration_changed", "node_id": node_id})
    for edge in sorted(set(candidate.edges) - set(baseline.edges)):
        changes.append({"kind": "edge_added", **edge.record()})
    for edge in sorted(set(baseline.edges) - set(candidate.edges)):
        changes.append({"kind": "edge_removed", **edge.record()})
    if baseline.settings != candidate.settings:
        changes.append({"kind": "workflow_settings_changed"})
    return changes


def verify(candidate, policy, policy_hash, baseline=None, *, strict_unknown=False, fail_on_all=False, document=None):
    findings = evaluate(candidate, policy, document=document)
    previous = evaluate(baseline, policy, document=document) if baseline else []
    if baseline:
        for current, old in zip(findings, previous, strict=True):
            current["regression"] = classify(current, old)
            current["review_required"] |= current["regression"] == "UNKNOWN_IMPACT"
    blocking = [item for item in findings if item["verdict"] == "FAIL" and (not baseline or fail_on_all or item["regression"] == "INTRODUCED")]
    uncertain = [item for item in findings if item["verdict"] in UNKNOWN or item["limitations"] or item["regression"] == "UNKNOWN_IMPACT"]
    exit_code = 1 if blocking else 3 if strict_unknown and uncertain else 0
    configuration = {"strict_unknown": strict_unknown, "fail_on_all_verified_failures": fail_on_all,
                     "max_states": MAX_STATES, "max_counterexamples": MAX_COUNTEREXAMPLES, "max_nodes": MAX_NODES, "max_edges": MAX_EDGES,
                     "max_bytes": MAX_BYTES, "max_depth": MAX_DEPTH, "max_items": MAX_ITEMS}
    identity = {"workflow_hash": candidate.input_hash, "baseline_hash": baseline.input_hash if baseline else None,
                "policy_hash": policy_hash, "verifier_version": __version__, "adapter_version": ADAPTER_VERSION,
                "canonicalization_version": 1, "configuration": configuration}
    if document is not None:
        from .sop import document_reference
        identity["source_document"] = document_reference(document)
    audit = {"schema_version": 1, "audit_id": digest(identity), **identity, "workflow_graph_hash": candidate.graph_hash,
            "baseline_graph_hash": baseline.graph_hash if baseline else None, "policy_id": policy.policy_id,
            "policy_version": policy.policy_version, "declared_fields": policy.fields,
            "model_limitations": MODEL_LIMITATIONS, "findings": findings, "baseline_findings": previous,
            "structural_changes": structural_diff(baseline, candidate) if baseline else [],
            "summary": {"rules_evaluated": len(findings), "blocking_failures": len(blocking),
                        "needs_review": len(uncertain), "exit_code": exit_code}}
    audit["traceability"] = matrix(findings)
    validate_evidence(audit["findings"], candidate)
    if baseline:
        validate_evidence(audit["baseline_findings"], baseline)
    return audit


def validate_evidence(findings, workflow):
    edge_records = {digest(edge.record()) for edge in workflow.edges}
    for item in findings:
        evidence = item["evidence"]
        if any(node_id not in workflow.nodes for node_id in evidence.get("nodes", [])):
            raise RuntimeError("engine emitted a nonexistent node reference")
        for route in evidence.get("counterexamples", []):
            nodes, edges = route["nodes"], route["path_edges"]
            if len(edges) != len(nodes) - 1 or any(node_id not in workflow.nodes for node_id in nodes):
                raise RuntimeError("engine emitted an invalid path")
            for index, edge in enumerate(edges):
                if digest(edge) not in edge_records or (edge["source"], edge["target"]) != tuple(nodes[index:index + 2]):
                    raise RuntimeError("engine emitted an invalid edge reference")
            for branch in route.get("branch_conditions", []):
                validate_parameter(branch, branch["node_id"], workflow)
        if "parameter_pointer" in evidence:
            validate_parameter(evidence, evidence["nodes"][0], workflow)


def validate_parameter(evidence, node_id, workflow):
    if node_id not in workflow.nodes or evidence["parameter_pointer"] != workflow.pointers[node_id] + evidence["condition_pointer"]:
        raise RuntimeError("engine emitted an invalid parameter reference")
    value = workflow.nodes[node_id].model_dump()
    try:
        for part in evidence["condition_pointer"].lstrip("/").split("/"):
            value = value[int(part)] if isinstance(value, list) else value[part]
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise RuntimeError("engine emitted a nonexistent parameter reference") from exc
