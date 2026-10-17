"""Small standard-library CLI; the verifier is reusable without this interface."""

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .ingestion import InputError, load_json, load_policy, read_bytes, read_policy, read_workflow
from .reporting import MAX_REPORT_BYTES, MAX_REPORT_DEPTH, write_artifact, write_reports
from .semantics import ADAPTER_VERSION, node_problem, read_condition, UnknownSemantics
from .verifier import verify


def parser():
    result = argparse.ArgumentParser(prog="veriq", description="Read-only, bounded static n8n workflow verification")
    result.add_argument("--version", action="version", version=__version__)
    commands = result.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="inspect supported graph structure without executing it")
    inspect.add_argument("--workflow", type=Path, required=True)
    check = commands.add_parser("verify", help="check approved rules and optionally compare revisions")
    check.add_argument("--workflow", type=Path, required=True)
    check.add_argument("--rules", type=Path, required=True)
    check.add_argument("--baseline", type=Path)
    check.add_argument("--sop", type=Path, help="validate policy citations against this exact SOP revision")
    check.add_argument("--output-dir", type=Path, default=Path("reports"))
    check.add_argument("--strict-unknown", action="store_true")
    check.add_argument("--fail-on-all-verified-failures", action="store_true")
    check.add_argument("--warnings-only", action="store_true", help="preview rollout: retain audit gate outcome but return 0 for finding-based exits")
    explain = commands.add_parser("explain", help="read a finding from a stored JSON report")
    explain.add_argument("--report", type=Path, required=True)
    explain.add_argument("--finding", required=True)
    rules = commands.add_parser("rules", help="draft and explicitly approve source-backed rules")
    authoring = rules.add_subparsers(dest="rules_command", required=True)
    draft = authoring.add_parser("draft", help="extract draft requirements; never creates approval")
    draft.add_argument("--sop", type=Path, required=True)
    draft.add_argument("--output", type=Path, required=True)
    draft.add_argument("--model", help="opt in to a locally installed Ollama model on 127.0.0.1:11434")
    approve = authoring.add_parser("approve", help="apply an explicit human review file and validate mappings")
    approve.add_argument("--sop", type=Path, required=True)
    approve.add_argument("--draft", type=Path, required=True)
    approve.add_argument("--review", type=Path, required=True)
    approve.add_argument("--output", type=Path, required=True)
    serve = commands.add_parser("mcp", help="serve read-only tools over local stdio")
    serve.add_argument("--root", type=Path, required=True, help="restrict readable files to this directory")
    package = commands.add_parser("plugin", help="build the remote plugin ZIP from deployment metadata")
    package.add_argument("--config", type=Path, required=True)
    package.add_argument("--output", type=Path, required=True)
    package.add_argument("--repo-root", type=Path, default=Path("."))
    commands.add_parser("serve", help="serve OAuth-protected HTTP MCP behind an HTTPS reverse proxy")
    return result


def run(args):
    if args.command == "plugin":
        from .plugin_package import build_plugin
        build_plugin(args.config, args.output, args.repo_root)
        print("VERIQ: built plugin ZIP; endpoint, publisher details and review materials still require validation before submission.")
        return 0
    if args.command == "serve":
        from .hosted import serve
        serve()
        return 0
    if args.command == "rules":
        import yaml
        from .sop import approve_draft, draft_requirements, read_draft, read_review, read_sop
        document = read_sop(args.sop)
        inputs = [args.sop]
        if args.rules_command == "draft":
            draft = draft_requirements(document, args.model)
            payload = draft.model_dump_json(indent=2) + "\n"
            load_json(payload.encode("utf-8"))
        else:
            policy = approve_draft(read_draft(args.draft), read_review(args.review), document)
            payload = yaml.safe_dump(policy.model_dump(exclude_none=True), sort_keys=False, allow_unicode=True)
            load_policy(payload.encode("utf-8"))
            inputs.extend([args.draft, args.review])
        write_artifact(payload, args.output, inputs)
        if args.rules_command == "draft":
            print(f"Draft hash for review: {draft.content_hash}")
        print(f"VERIQ: wrote {args.rules_command} artifact; preserve the source, review file and policy in version control.")
        return 0
    if args.command == "mcp":
        from .mcp_server import create_server
        create_server(args.root).run(transport="stdio")
        return 0
    if args.command == "inspect":
        workflow = read_workflow(args.workflow)
        nodes = []
        for node in sorted(workflow.nodes.values(), key=lambda item: item.id):
            problem = node_problem(node)
            if not problem and node.type.endswith(".if"):
                try:
                    read_condition(node, {})
                except UnknownSemantics as exc:
                    problem = str(exc) + "; verify can supply declared field types from a policy"
            nodes.append({"id": node.id, "type": node.type, "typeVersion": node.typeVersion, "limitation": problem})
        print(json.dumps({"workflow_hash": workflow.input_hash, "graph_hash": workflow.graph_hash,
                          "adapter_version": ADAPTER_VERSION, "nodes": nodes,
                          "edges": [edge.record() for edge in workflow.edges]}, sort_keys=True, indent=2, ensure_ascii=True))
        return 0
    if args.command == "explain":
        audit = load_json(read_bytes(args.report, MAX_REPORT_BYTES), max_items=1_000_000, max_depth=MAX_REPORT_DEPTH)
        if not isinstance(audit, dict) or type(audit.get("schema_version")) is not int or audit["schema_version"] != 1 or not isinstance(audit.get("findings"), list):
            raise InputError("not a supported audit report")
        matches = [item for item in audit["findings"] if isinstance(item, dict) and item.get("rule_id") == args.finding]
        if not matches:
            raise InputError("finding ID not present in report")
        print(json.dumps(matches[0], sort_keys=True, indent=2, ensure_ascii=True))
        return 0
    candidate = read_workflow(args.workflow)
    baseline = read_workflow(args.baseline) if args.baseline else None
    policy, policy_hash = read_policy(args.rules)
    from .sop import read_sop
    document = read_sop(args.sop) if args.sop else None
    audit = verify(candidate, policy, policy_hash, baseline, strict_unknown=args.strict_unknown,
                   fail_on_all=args.fail_on_all_verified_failures, document=document)
    inputs = [args.workflow, args.rules] + ([args.baseline] if args.baseline else []) + ([args.sop] if args.sop else [])
    write_reports(audit, args.output_dir, inputs)
    summary = audit["summary"]
    print(f"VERIQ: {summary['rules_evaluated']} rules; {summary['blocking_failures']} blocking failures; {summary['needs_review']} review items; gate exit {summary['exit_code']}")
    for item in audit["findings"]:
        print(f"[{item['verdict']}] {item['rule_id']} ({item['regression'] or 'standalone'}): {item['reason']!a}")
    if args.warnings_only and summary["exit_code"]:
        print("Warnings-only preview: findings retain their verdicts; process exit is 0.")
        return 0
    return summary["exit_code"]


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        return run(args)
    except InputError as exc:
        print(f"VERIQ ERROR: {exc}; no completed result.", file=sys.stderr)
        return 2
    except ImportError:
        print("VERIQ ERROR: optional command dependencies are unavailable; install veriq with the sop, mcp or hosted extra.", file=sys.stderr)
        return 2
    except (UnicodeError, OSError, ValueError):
        print("VERIQ ERROR: input, policy, or report output is invalid/unavailable; no completed result. Check paths, limits, policy schema, and output permissions.", file=sys.stderr)
        return 2
    except Exception:
        print("VERIQ ERROR: internal verification error; no completed result.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
