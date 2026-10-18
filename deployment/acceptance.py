"""Live acceptance checks using synthetic fixtures and two independently issued user tokens."""

import argparse
import json
import os
from pathlib import Path
import sys

import httpx

from veriq.hosted_auth import HostedSettings
from veriq.ingestion import InputError, read_policy, read_workflow
from veriq.verifier import verify

ROOT = Path(__file__).resolve().parents[1]


def require(value, message):
    if not value:
        raise InputError(message)


def run_checks(client, origin, alice, bob, *, root=ROOT):
    uploaded = []
    checks = []
    def request(method, path, token=None, **kwargs):
        headers = kwargs.pop("headers", {})
        if token:
            headers["Authorization"] = "Bearer " + token
        return client.request(method, origin + path, headers=headers, **kwargs)

    def call(name, arguments, token=alice):
        response = request("POST", "/mcp", token, headers={"Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
        require(response.status_code == 200, "authenticated MCP request failed")
        result = response.json().get("result")
        require(isinstance(result, dict), "invalid MCP response")
        return result

    def successful(name, arguments):
        result = call(name, arguments)
        require(not result.get("isError"), "MCP tool failed: " + name)
        return result

    try:
        require(request("GET", "/healthz").json() == {"status": "ok"}, "health check failed")
        denied = request("POST", "/mcp", json={})
        require(denied.status_code == 401 and "resource_metadata=" in denied.headers.get("www-authenticate", ""),
                "anonymous MCP access was not challenged")
        checks.append("health and anonymous denial")
        ids = {}
        for label, kind, relative in [("baseline", "workflow", "examples/purchase-v1.json"),
                ("candidate", "workflow", "examples/purchase-v2.json"),
                ("policy", "policy", "examples/veriq.rules.yaml"),
                ("pdf", "pdf", "tests/fixtures/purchasing-approval-sop.pdf"),
                ("docx", "docx", "examples/procurement-sop.docx")]:
            response = request("POST", "/artifacts/" + kind, alice,
                headers={"Content-Type": "application/octet-stream"}, content=(root / relative).read_bytes())
            require(response.status_code == 201, "fixture upload failed: " + label)
            identifier = response.json()["artifact_id"]
            uploaded.append(identifier)
            ids[label] = identifier
        checks.append("workflow JSON, reviewed demo YAML, SOP PDF and DOCX uploads")
        for label in ("pdf", "docx"):
            document = successful("ingest_sop_document", {"relative_path": ids[label]})["structuredContent"]
            require(bool(document["blocks"]), "SOP extraction returned no text")
        draft = successful("draft_sop_requirements", {"relative_path": ids["pdf"]})["structuredContent"]
        require(len(draft["candidates"]) == 8 and all(c["status"] == "draft" for c in draft["candidates"]),
                "PDF requirement regression check failed")
        checks.append("SOP extraction and eight unapproved requirement candidates")
        policy, policy_hash = read_policy(root / "examples/veriq.rules.yaml")
        baseline = read_workflow(root / "examples/purchase-v1.json")
        passing = successful("verify_workflow_rules", {"workflow": ids["baseline"], "rules": ids["policy"]})["structuredContent"]
        require(passing == verify(baseline, policy, policy_hash), "baseline audit differs from local verifier")
        audit = successful("compare_workflow_versions", {"workflow": ids["candidate"],
            "baseline": ids["baseline"], "rules": ids["policy"]})["structuredContent"]
        require(audit == verify(read_workflow(root / "examples/purchase-v2.json"), policy, policy_hash, baseline),
                "comparison differs from local verifier")
        require(passing["summary"]["exit_code"] == 0 and audit["summary"]["exit_code"] == 1,
                "expected passing baseline and failing changed workflow")
        args = {"audit_id": audit["audit_id"]}
        exported = successful("export_audit_report", args)
        require(json.loads(exported["content"][0]["text"]) == audit, "persisted report differs")
        require(bool(successful("export_audit_report", {**args, "format": "markdown"})["content"]), "Markdown export failed")
        finding_args = {**args, "finding_id": audit["findings"][0]["rule_id"]}
        require(successful("get_audit_finding", finding_args)["structuredContent"] == audit["findings"][0], "finding differs")
        checks.append("baseline, regression, persisted JSON/Markdown reports and finding evidence")
        for name, arguments in [("ingest_n8n_workflow", {"relative_path": ids["candidate"]}),
                ("ingest_sop_document", {"relative_path": ids["pdf"]}),
                ("export_audit_report", args), ("get_audit_finding", finding_args)]:
            require(call(name, arguments, bob).get("isError") is True, "cross-account access was not denied")
        require(request("DELETE", "/artifacts/" + ids["candidate"], bob).status_code == 404,
                "cross-account deletion was not denied")
        checks.append("second-account file, SOP, report, finding and deletion denial")
    finally:
        cleanup_failed = False
        for identifier in uploaded:
            try:
                cleanup_failed |= request("DELETE", "/artifacts/" + identifier, alice).status_code != 200
            except httpx.HTTPError:
                cleanup_failed = True
        require(not cleanup_failed, "acceptance fixture cleanup failed; inputs remain private until expiry")
    require(call("ingest_n8n_workflow", {"relative_path": ids["candidate"]}).get("isError") is True,
            "deleted input remained accessible")
    return {"status": "passed", "checks": checks + ["input deletion"],
            "scope": "Synthetic fixtures; real business-rule approval, browser consent, ChatGPT UI and elapsed TTL require separate live checks."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-development", action="store_true", help="Explicitly test the current Clerk development instance")
    args = parser.parse_args()
    try:
        settings = HostedSettings.from_environment()
        require(args.allow_development or settings.environment == "production", "set VERIQ_ENVIRONMENT=production or explicitly allow development")
        alice, bob = os.environ["VERIQ_SMOKE_ALICE_TOKEN"], os.environ["VERIQ_SMOKE_BOB_TOKEN"]
        require(bool(alice) and bool(bob) and alice != bob, "two independent user tokens are required")
        with httpx.Client(timeout=60, follow_redirects=False, trust_env=False) as client:
            discovery = client.get(settings.origin + "/.well-known/oauth-protected-resource/mcp")
            require(discovery.status_code == 200 and discovery.json().get("resource") == settings.resource
                    and discovery.json().get("authorization_servers") == [settings.issuer], "OAuth resource discovery mismatch")
            print(json.dumps(run_checks(client, settings.origin, alice, bob), indent=2))
        return 0
    except (KeyError, InputError, httpx.HTTPError, ValueError, TypeError):
        # Never echo tokens, provider responses, input text or request URLs containing codes.
        print("Acceptance failed. Check configuration, two-user token scopes, service logs and fixture cleanup.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
