import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from veriq.cli import main
from veriq.ingestion import read_policy, read_workflow
from veriq.reporting import markdown, write_reports
from veriq.verifier import verify

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def test_cli_round_trip_and_repeatable_artifacts(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    command = [sys.executable, "-m", "veriq", "verify", "--workflow", str(EXAMPLES / "purchase-v2.json"),
               "--baseline", str(EXAMPLES / "purchase-v1.json"), "--rules", str(EXAMPLES / "veriq.rules.yaml"), "--output-dir", str(tmp_path)]
    first = subprocess.run(command, env=env, capture_output=True, text=True, timeout=20)
    assert first.returncode == 1, first.stderr
    assert "INTRODUCED" in first.stdout
    before = [(tmp_path / name).read_bytes() for name in ("audit.json", "audit.md")]
    second = subprocess.run(command, env=env, capture_output=True, text=True, timeout=20)
    assert second.returncode == 1
    assert before == [(tmp_path / name).read_bytes() for name in ("audit.json", "audit.md")]
    explain = subprocess.run([sys.executable, "-m", "veriq", "explain", "--report", str(tmp_path / "audit.json"), "--finding", "REQ-004"], env=env, capture_output=True, text=True, timeout=20)
    assert explain.returncode == 0, explain.stderr
    assert json.loads(explain.stdout)["evidence"]["counterexample_path"][-1] == "fulfillment"
    assert (tmp_path / "audit.json").stat().st_mode & 0o077 == 0


def test_inspection_does_not_echo_credentials(tmp_path, capsys):
    data = json.loads((EXAMPLES / "purchase-v1.json").read_text())
    data["nodes"][0]["parameters"]["secret"] = "SYNTHETIC_SECRET_NEVER_PRINT"
    path = tmp_path / "workflow.json"
    path.write_text(json.dumps(data))
    assert main(["inspect", "--workflow", str(path)]) == 0
    assert "SYNTHETIC_SECRET_NEVER_PRINT" not in capsys.readouterr().out


def test_invalid_input_returns_2_without_creating_reports(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("invalid")
    output = tmp_path / "reports"
    assert main(["verify", "--workflow", str(path), "--rules", str(EXAMPLES / "veriq.rules.yaml"), "--output-dir", str(output)]) == 2
    assert "ERROR" in capsys.readouterr().err
    assert not output.exists()


def test_warnings_only_preserves_canonical_failure(tmp_path):
    assert main(["verify", "--workflow", str(EXAMPLES / "purchase-v2.json"), "--rules", str(EXAMPLES / "veriq.rules.yaml"), "--output-dir", str(tmp_path), "--warnings-only"]) == 0
    audit = json.loads((tmp_path / "audit.json").read_text())
    assert audit["findings"][0]["verdict"] == "FAIL"
    assert audit["summary"]["exit_code"] == 1


def test_report_destination_cannot_overwrite_an_input(tmp_path):
    rules, policy_hash = read_policy(EXAMPLES / "veriq.rules.yaml")
    workflow = read_workflow(EXAMPLES / "purchase-v1.json")
    audit = verify(workflow, rules, policy_hash)
    protected = tmp_path / "protected.json"
    protected.write_text("original data")
    (tmp_path / "audit.json").symlink_to(protected)
    with pytest.raises(ValueError, match="overwrite an input"):
        write_reports(audit, tmp_path, [protected])
    assert protected.read_text() == "original data"


def test_markdown_escapes_untrusted_titles_and_identifiers():
    rules, policy_hash = read_policy(EXAMPLES / "veriq.rules.yaml")
    audit = verify(read_workflow(EXAMPLES / "purchase-v1.json"), rules, policy_hash)
    audit["findings"][0]["title"] = '<script>alert(1)</script> [fake](javascript:alert(1))\n# injected'
    output = markdown(audit)
    assert "<script>" not in output
    assert "&lt;script&gt;" in output
    assert "[fake](javascript:" not in output
    assert "\n# injected" not in output


def test_output_failure_returns_2_even_with_known_violation(tmp_path):
    output = tmp_path / "not-a-directory"
    output.write_text("keep me")
    assert main(["verify", "--workflow", str(EXAMPLES / "purchase-v2.json"), "--rules", str(EXAMPLES / "veriq.rules.yaml"), "--output-dir", str(output)]) == 2
    assert output.read_text() == "keep me"


def test_explain_reads_report_with_deep_accepted_metadata(tmp_path, capsys):
    data = yaml.safe_load((EXAMPLES / "veriq.rules.yaml").read_text())
    nested = "leaf"
    for _ in range(28):
        nested = {"value": nested}
    data["rules"][0]["source"] = {"value": nested}
    policy_path = tmp_path / "rules.yaml"
    policy_path.write_text(yaml.safe_dump(data))
    rules, policy_hash = read_policy(policy_path)
    audit = verify(read_workflow(EXAMPLES / "purchase-v1.json"), rules, policy_hash)
    write_reports(audit, tmp_path, [policy_path])
    assert main(["explain", "--report", str(tmp_path / "audit.json"), "--finding", "REQ-004"]) == 0
    assert json.loads(capsys.readouterr().out)["source"]["citation"] == data["rules"][0]["source"]


def test_explain_keeps_a_bounded_report_depth(tmp_path, capsys):
    from veriq.reporting import MAX_REPORT_DEPTH
    path = tmp_path / "report.json"
    path.write_text("[" * (MAX_REPORT_DEPTH + 1) + "]" * (MAX_REPORT_DEPTH + 1))
    assert main(["explain", "--report", str(path), "--finding", "REQ-004"]) == 2
    assert "nesting limit" in capsys.readouterr().err
