import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from veriq.ingestion import read_policy, read_workflow
from veriq.reporting import json_report, markdown
from veriq.verifier import verify

ROOT = Path(__file__).resolve().parents[1]


def test_oversized_report_stops_before_exhausting_process_memory(tmp_path):
    pytest.importorskip("resource")
    script = textwrap.dedent("""
        from copy import deepcopy
        import json
        from pathlib import Path
        import resource
        import sys
        import yaml
        from veriq.ingestion import read_policy, read_workflow
        from veriq.reporting import write_reports
        from veriq.verifier import verify

        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024**2, 256 * 1024**2))
        root, output = map(Path, sys.argv[1:])
        data = json.loads((root / 'examples/purchase-v1.json').read_text())
        threshold = next(node for node in data['nodes'] if node['id'] == 'threshold')
        threshold['parameters'] = {'conditions': {'string': [{
            'value1': '={{ $json.body.status }}', 'operation': 'equal', 'value2': 'x' * 700_000}]}}
        workflow = output / 'workflow.json'
        workflow.write_text(json.dumps(data))
        policy = yaml.safe_load((root / 'examples/veriq.rules.yaml').read_text())
        policy['fields'] = {'body.status': 'string'}
        template = policy['rules'][1]
        template['condition'] = {'field': 'body.status', 'operator': 'eq', 'value': 'approved'}
        policy['rules'] = [{**deepcopy(template), 'id': f'REQ-{index}'} for index in range(100)]
        rules = output / 'rules.yaml'
        rules.write_text(yaml.safe_dump(policy))
        parsed, policy_hash = read_policy(rules)
        audit = verify(read_workflow(workflow), parsed, policy_hash)
        directory = output / 'reports'
        directory.mkdir()
        for name in ('audit.json', 'audit.md'):
            (directory / name).write_text('previous report')
        try:
            write_reports(audit, directory, [workflow, rules])
        except ValueError as exc:
            assert 'output limit' in str(exc), str(exc)
        else:
            raise AssertionError('oversized report accepted')
        assert sorted(path.name for path in directory.iterdir()) == ['audit.json', 'audit.md']
        assert all(path.read_text() == 'previous report' for path in directory.iterdir())
    """)
    result = subprocess.run([sys.executable, "-c", script, str(ROOT), str(tmp_path)],
                            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_markdown_enforces_utf8_byte_limit(monkeypatch):
    rules, policy_hash = read_policy(ROOT / "examples/veriq.rules.yaml")
    audit = verify(read_workflow(ROOT / "examples/purchase-v1.json"), rules, policy_hash)
    audit["findings"][0]["title"] = "界" * 100
    output = markdown(audit)
    monkeypatch.setattr("veriq.reporting.MAX_REPORT_BYTES", len(output.encode("utf-8")))
    assert markdown(audit) == output
    monkeypatch.setattr("veriq.reporting.MAX_REPORT_BYTES", len(output.encode("utf-8")) - 1)
    with pytest.raises(ValueError, match="output limit"):
        markdown(audit)


def test_json_stops_serialization_at_limit(monkeypatch):
    monkeypatch.setattr("veriq.reporting.MAX_REPORT_BYTES", 100)
    with pytest.raises(ValueError, match="output limit"):
        json_report({"first": "x" * 200, "unvisited": object()})
