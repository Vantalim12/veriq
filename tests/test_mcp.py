import asyncio
import json
import os
from pathlib import Path
import shutil
import sys

import pytest

pytest.importorskip("mcp")

from veriq.ingestion import read_policy, read_workflow
from veriq.mcp_server import create_server
from veriq.verifier import verify

ROOT = Path(__file__).resolve().parents[1]


def test_mcp_tools_match_core_and_confine_paths(tmp_path):
    for name in ("purchase-v1.json", "purchase-v2.json", "veriq.rules.yaml"):
        shutil.copyfile(ROOT / "examples" / name, tmp_path / name)
    (tmp_path / "escape.json").symlink_to(ROOT / "examples/purchase-v1.json")

    async def check():
        server = create_server(tmp_path)
        tools = await server.list_tools()
        assert {tool.name for tool in tools} == {"ingest_sop_document", "ingest_n8n_workflow", "verify_workflow_rules",
            "compare_workflow_versions", "get_audit_finding", "export_audit_report", "draft_sop_requirements"}
        assert all(tool.annotations.readOnlyHint and not tool.annotations.destructiveHint for tool in tools)
        arguments = {"workflow": "purchase-v2.json", "baseline": "purchase-v1.json", "rules": "veriq.rules.yaml"}
        result = await server.call_tool("compare_workflow_versions", arguments)
        # FastMCP returns (content blocks, structured result) for typed tools.
        audit = result[1] if isinstance(result, tuple) else json.loads(result[0].text)
        policy, policy_hash = read_policy(tmp_path / "veriq.rules.yaml")
        expected = verify(read_workflow(tmp_path / "purchase-v2.json"), policy, policy_hash, read_workflow(tmp_path / "purchase-v1.json"))
        assert audit == expected
        finding = await server.call_tool("get_audit_finding", {"audit_id": audit["audit_id"], "finding_id": "REQ-004"})
        assert (finding[1] if isinstance(finding, tuple) else json.loads(finding[0].text)) == expected["findings"][0]
        for path in ("../outside.json", str(ROOT / "examples/purchase-v1.json"), "escape.json"):
            with pytest.raises(Exception):
                await server.call_tool("ingest_n8n_workflow", {"relative_path": path})
        with pytest.raises(Exception):
            await server.call_tool("get_audit_finding", {"audit_id": "unknown", "finding_id": "REQ-004"})
        assert sorted(p.name for p in tmp_path.iterdir()) == ["escape.json", "purchase-v1.json", "purchase-v2.json", "veriq.rules.yaml"]
    asyncio.run(check())


def test_mcp_stdio_protocol_round_trip():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    import anyio

    async def check():
        parameters = StdioServerParameters(command=sys.executable,
            args=["-m", "veriq", "mcp", "--root", str(ROOT / "examples")],
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
        with anyio.fail_after(20):
            async with stdio_client(parameters) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    assert len(tools.tools) == 7
                    result = await session.call_tool("verify_workflow_rules", {"workflow": "purchase-v2.json", "rules": "veriq.rules.yaml"})
                    assert not result.isError
                    audit = result.structuredContent
                    assert audit["summary"]["exit_code"] == 1
                    exported = await session.call_tool("export_audit_report", {"audit_id": audit["audit_id"]})
                    assert not exported.isError
                    assert json.loads(exported.content[0].text) == audit
                    error = await session.call_tool("ingest_n8n_workflow", {"relative_path": "../pyproject.toml"})
                    assert error.isError
    asyncio.run(check())


def test_mcp_rejects_oversized_audit_before_caching(monkeypatch):
    policy, policy_hash = read_policy(ROOT / "examples/veriq.rules.yaml")
    audit = verify(read_workflow(ROOT / "examples/purchase-v1.json"), policy, policy_hash)
    monkeypatch.setattr("veriq.reporting.MAX_REPORT_BYTES", 100)

    async def check():
        server = create_server(ROOT / "examples")
        with pytest.raises(Exception, match="output limit"):
            await server.call_tool("verify_workflow_rules", {"workflow": "purchase-v1.json", "rules": "veriq.rules.yaml"})
        with pytest.raises(Exception, match="audit unavailable"):
            await server.call_tool("get_audit_finding", {"audit_id": audit["audit_id"], "finding_id": "REQ-004"})

    asyncio.run(check())
