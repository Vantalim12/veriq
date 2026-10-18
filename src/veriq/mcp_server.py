"""Local stdio tools restricted to a caller-selected filesystem root."""

from collections import OrderedDict
from functools import partial, wraps
import time
from pathlib import Path
from typing import Any

import anyio

from .ingestion import InputError, read_policy, read_workflow
from .reporting import json_report, markdown
from .sop import draft_requirements, read_sop
from .verifier import verify


def create_server(root: Path):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise InputError("MCP support requires installation with 'veriq[mcp]'") from exc
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise InputError("MCP root must be an existing directory")
    server = FastMCP("Veriq", instructions="Read-only static evidence. Drafts never approve rules. Static PASS does not prove live approval or compliance.")
    def path(relative, suffixes):
        supplied = Path(relative)
        if supplied.is_absolute():
            raise InputError("MCP inputs must be relative to the configured root")
        resolved = (root / supplied).resolve(strict=True)
        if not resolved.is_relative_to(root) or resolved.suffix.lower() not in suffixes:
            raise InputError("MCP input escapes the root or has an unsupported extension")
        return resolved

    register_tools(server, path)
    return server


def register_tools(server, path, principal=lambda: "local", *, cache_seconds=None, scopes=None, audit_store=None):
    """Share canonical operations while the transport supplies its file/identity boundary."""
    from mcp.types import ToolAnnotations
    annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    metadata = {"securitySchemes": [{"type": "oauth2", "scopes": scopes}]} if scopes else None
    audits = OrderedDict()
    # Serialize tool work to protect the cache and shared download paths without blocking HTTP.
    tool_slots = anyio.CapacityLimiter(1)

    def in_worker(function):
        @wraps(function)
        async def run(*args, **kwargs):
            return await anyio.to_thread.run_sync(partial(function, *args, **kwargs), limiter=tool_slots)
        return run

    def audit(workflow, rules, baseline=None, sop=None, strict_unknown=False, fail_on_all=False):
        candidate = read_workflow(path(workflow, {".json"}))
        policy, policy_hash = read_policy(path(rules, {".yaml", ".yml"}))
        reference = read_workflow(path(baseline, {".json"})) if baseline else None
        document = read_sop(path(sop, {".pdf", ".docx"})) if sop else None
        result = verify(candidate, policy, policy_hash, reference, strict_unknown=strict_unknown,
                        fail_on_all=fail_on_all, document=document)
        json_report(result)
        if audit_store is not None:
            audit_store.save_audit(principal(), result)
            return result
        key = (principal(), result["audit_id"])
        audits[key] = (time.monotonic(), result)
        audits.move_to_end(key)
        while len(audits) > 8:
            audits.popitem(last=False)
        return result

    def stored(audit_id):
        if audit_store is not None:
            return audit_store.load_audit(principal(), audit_id)
        key = (principal(), audit_id)
        if key not in audits:
            raise InputError("audit unavailable; rerun verification (only the last eight audits are retained)")
        created, result = audits[key]
        if cache_seconds is not None and time.monotonic() - created >= cache_seconds:
            del audits[key]
            raise InputError("audit expired; rerun verification")
        return result

    @server.tool(annotations=annotations, meta=metadata)
    @in_worker
    def ingest_sop_document(relative_path: str) -> dict[str, Any]:
        """Read a text SOP input reference, preserving locations and input hash."""
        return read_sop(path(relative_path, {".pdf", ".docx"}))

    @server.tool(annotations=annotations, meta=metadata)
    @in_worker
    def ingest_n8n_workflow(relative_path: str) -> dict[str, Any]:
        """Inspect normalized workflow identities and edges without disclosing parameters/credentials."""
        from .semantics import node_problem
        workflow = read_workflow(path(relative_path, {".json"}))
        return {"workflow_hash": workflow.input_hash, "graph_hash": workflow.graph_hash,
                "nodes": [{"id": n.id, "type": n.type, "typeVersion": n.typeVersion, "limitation": node_problem(n)}
                          for n in sorted(workflow.nodes.values(), key=lambda n: n.id)],
                "edges": [e.record() for e in workflow.edges]}

    @server.tool(annotations=annotations, meta=metadata)
    @in_worker
    def verify_workflow_rules(workflow: str, rules: str, sop: str | None = None,
                              strict_unknown: bool = False, fail_on_all: bool = False) -> dict[str, Any]:
        """Run the canonical verifier against a supplied reviewed policy. Never approve or edit rules."""
        return audit(workflow, rules, sop=sop, strict_unknown=strict_unknown, fail_on_all=fail_on_all)

    @server.tool(annotations=annotations, meta=metadata)
    @in_worker
    def compare_workflow_versions(workflow: str, baseline: str, rules: str, sop: str | None = None,
                                  strict_unknown: bool = False, fail_on_all: bool = False) -> dict[str, Any]:
        """Compare revisions with the same policy and engine used by the CLI."""
        return audit(workflow, rules, baseline, sop, strict_unknown, fail_on_all)

    @server.tool(annotations=annotations, meta=metadata)
    @in_worker
    def get_audit_finding(audit_id: str, finding_id: str) -> dict[str, Any]:
        """Return exact canonical evidence for a finding from this session."""
        result = next((f for f in stored(audit_id)["findings"] if f["rule_id"] == finding_id), None)
        if result is None:
            raise InputError("finding unavailable")
        return result

    @server.tool(annotations=annotations, meta=metadata)
    @in_worker
    def export_audit_report(audit_id: str, format: str = "json") -> str:
        """Return a stored audit as JSON or escaped Markdown without writing files."""
        result = stored(audit_id)
        if format not in {"json", "markdown"}:
            raise InputError("format must be json or markdown")
        return markdown(result) if format == "markdown" else json_report(result)

    @server.tool(annotations=annotations, meta=metadata)
    @in_worker
    def draft_sop_requirements(relative_path: str) -> dict[str, Any]:
        """Draft source-validated candidates with source requirement IDs; verification_instructions are separate.

        Interpretations need human review. This tool cannot approve policy or call a model.
        """
        return draft_requirements(read_sop(path(relative_path, {".pdf", ".docx"}))).model_dump()

    return server
