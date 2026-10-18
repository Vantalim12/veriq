"""Safe human-readable reports and complete-file output replacement."""

import html
from io import StringIO
from itertools import chain
import json
import os
from pathlib import Path
import tempfile

from .ingestion import InputError, MAX_BYTES, MAX_DEPTH

MAX_REPORT_BYTES = 16 * 1024 * 1024
MAX_USER_AUDITS = 8
MAX_TOTAL_AUDITS = 1000
MAX_TOTAL_AUDIT_BYTES = 512 * 1024 * 1024
# Reports wrap accepted source metadata in finding and traceability envelopes.
MAX_REPORT_DEPTH = MAX_DEPTH + 8


def bounded_text(chunks):
    size = 0
    with StringIO() as stream:
        for chunk in chunks:
            size += len(chunk.encode("utf-8"))
            if size > MAX_REPORT_BYTES:
                raise InputError("report exceeds the 16 MiB output limit")
            stream.write(chunk)
        return stream.getvalue()


def json_report(value):
    encoder = json.JSONEncoder(sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False)
    return bounded_text(chain(encoder.iterencode(value), ("\n",)))


def text(value):
    value = "".join(char if char.isprintable() else " " for char in str(value))
    value = html.escape(value, quote=False)
    for char in ("\\", "`", "*", "_", "[", "]", "|", "#", "!"):
        value = value.replace(char, "\\" + char)
    return value


def markdown(audit):
    return bounded_text(line + "\n" for line in _markdown_lines(audit))


def _markdown_lines(audit):
    summary = audit["summary"]
    yield from ["# Veriq audit", "", f"Audit: {text(audit['audit_id'])}", "",
             f"Rules evaluated: {summary['rules_evaluated']} · Blocking failures: {summary['blocking_failures']} · Needs review: {summary['needs_review']} · Exit: {summary['exit_code']}", "",
             "## Model boundary", ""]
    yield from ("- " + text(item) for item in audit["model_limitations"])
    yield from ["", "Declared field assumptions: " + text(json.dumps(audit["declared_fields"], sort_keys=True)), "",
                  "## Input identity", "",
                  f"- Candidate: {text(audit['workflow_hash'])}",
                  f"- Baseline: {text(audit['baseline_hash'] or 'None — standalone check; change impact not assessed')}",
                  f"- Policy: {text(audit['policy_hash'])}",
                  f"- Engine: {text(audit['verifier_version'])}; adapters: {text(audit['adapter_version'])}",
                  f"- SOP: {text((audit.get('source_document') or {}).get('document_hash', 'Not supplied'))}", "",
                  "## Rule results", "", "| Rule | Verdict | Comparison | Severity |", "|---|---|---|---|"]
    for item in audit["findings"]:
        yield "| " + " | ".join(text(item.get(key) or "—") for key in ("rule_id", "verdict", "regression", "severity")) + " |"
    for item in audit["findings"]:
        yield from ["", f"## {text(item['rule_id'])}: {text(item['title'])}", "", text(item["reason"]), ""]
        evidence = item["evidence"]
        if evidence.get("counterexample_path"):
            yield "Counterexample: " + text(" → ".join(evidence["counterexample_path"]))
            yield ""
            for edge in evidence["path_edges"]:
                yield f"- {text(edge['source'])} output {edge['output_index']} → {text(edge['target'])} input {edge['input_index']} ({text(edge['channel'])})"
            if evidence.get("when"):
                yield "Applicable when: " + text(json.dumps(evidence["when"], sort_keys=True))
            for branch in evidence.get("branch_conditions", []):
                yield "- Branch evidence: " + text(json.dumps(branch, sort_keys=True))
        if evidence.get("parameter_pointer"):
            yield from ["Parameter: " + text(evidence["parameter_pointer"]), "",
                          "Expected: " + text(json.dumps(evidence["expected"], sort_keys=True)), "",
                          "Observed: " + text(json.dumps(evidence["observed"], sort_keys=True))]
        if evidence.get("introduced_counterexamples"):
            yield from ["", "Introduced routes:"]
            yield from ("- " + text(" → ".join(path["nodes"])) for path in evidence["introduced_counterexamples"])
        for limitation in item["limitations"]:
            yield "- Coverage / review: " + text(limitation)
        if item["verdict"] != "PASS":
            yield from ["", "Reviewer action: inspect the approved mapping and evidence; correct the workflow or propose a reviewed policy change. Verify external behavior separately."]
    if audit.get("traceability"):
        yield from ["", "## SOP traceability", "", "| Rule | Source location | Quote | Citation | Verdict |", "|---|---|---|---|---|"]
        for row in audit["traceability"]:
            source = row["source"] or {}
            citation = source.get("citation") or {}
            location = citation.get("block_id", "—")
            if citation.get("section"):
                location += ": " + str(citation["section"])
            status = "validated" if source.get("validated") else "unvalidated" if source else "hand-authored"
            yield "| " + " | ".join(text(value) for value in (row["rule_id"], location, citation.get("quote", "—"), status, row["verdict"])) + " |"
    if audit["structural_changes"]:
        yield from ["", "## Structural changes", ""]
        yield from ("- " + text(json.dumps(item, sort_keys=True)) for item in audit["structural_changes"])


def write_reports(audit, directory: Path, inputs):
    destinations = [directory / "audit.json", directory / "audit.md"]
    input_paths = {path.resolve() for path in inputs}
    if any(path.resolve() in input_paths for path in destinations):
        raise ValueError("report output would overwrite an input file")
    payloads = [json_report(audit), markdown(audit)]
    directory.mkdir(parents=True, exist_ok=True)
    staged = []
    try:
        for payload in payloads:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as stream:
                staged.append(Path(stream.name))
                os.chmod(stream.name, 0o600)
                stream.write(payload)
        for temporary, destination in zip(staged, destinations, strict=True):
            os.replace(temporary, destination)
    finally:
        for temporary in staged:
            temporary.unlink(missing_ok=True)


def write_artifact(payload: str, destination: Path, inputs):
    """Create authoring artifacts exclusively; never replace a source or existing review."""
    if destination.resolve() in {path.resolve() for path in inputs}:
        raise ValueError("artifact output would overwrite an input file")
    if len(payload.encode("utf-8")) > MAX_BYTES:
        raise InputError("authoring artifact exceeds the 2 MiB input limit; split the SOP or policy into smaller parts")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
