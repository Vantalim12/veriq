from dataclasses import replace
import importlib.util
from pathlib import Path
import subprocess

import pytest

from veriq.document_worker import read_sop_isolated
from veriq.hosted_auth import HostedSettings
from veriq.ingestion import InputError
from veriq.sop import read_sop

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("field", ["issuer", "jwks_url"])
def test_production_refuses_clerk_development_hosts(tmp_path, field):
    values = dict(origin="https://veriq.sgp.appwrite.run", issuer="https://clerk.company.test",
                  jwks_url="https://clerk.company.test/.well-known/jwks.json", data_dir=tmp_path,
                  upload_client_id="production-client", environment="production")
    values[field] = "https://large-bluebird-4071.clerk.accounts.dev" + ("/jwks" if field == "jwks_url" else "")
    with pytest.raises(InputError, match="production issuer"):
        HostedSettings(**values)


def test_production_requires_a_client_and_valid_environment(tmp_path):
    valid = HostedSettings("https://veriq.sgp.appwrite.run", "https://clerk.company.test",
        "https://clerk.company.test/.well-known/jwks.json", tmp_path, "production-client", "production")
    assert valid.resource == "https://veriq.sgp.appwrite.run/mcp"
    with pytest.raises(InputError, match="UPLOAD_CLIENT_ID"):
        replace(valid, upload_client_id="")
    with pytest.raises(InputError, match="ENVIRONMENT"):
        replace(valid, environment="prodution")


@pytest.mark.parametrize("source", ["examples/procurement-sop.docx", "tests/fixtures/purchasing-approval-sop.pdf"])
def test_isolated_parser_preserves_extraction_without_runtime_secrets(monkeypatch, source):
    monkeypatch.setenv("VERIQ_APPWRITE_API_KEY", "secret-never-forwarded")
    run = subprocess.run
    def checked(*args, **kwargs):
        assert kwargs["env"] == {"LANG": "C.UTF-8"}
        assert kwargs["close_fds"] and kwargs["timeout"] == 15
        assert args[0][1] == "-I"
        return run(*args, **kwargs)
    monkeypatch.setattr("veriq.document_worker.subprocess.run", checked)
    assert read_sop_isolated(ROOT / source) == read_sop(ROOT / source)


@pytest.mark.parametrize("failure", ["timeout", "crash", "invalid_output"])
def test_parser_failures_are_bounded_and_sanitized(monkeypatch, failure):
    def failed(command, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"], stderr="private")
        return subprocess.CompletedProcess(command, -9 if failure == "crash" else 0)
    monkeypatch.setattr("veriq.document_worker.subprocess.run", failed)
    with pytest.raises(InputError) as error:
        read_sop_isolated(ROOT / "examples/procurement-sop.docx")
    assert "private" not in str(error.value)


def test_isolated_parser_rejects_corrupt_documents(tmp_path):
    path = tmp_path / "bad.pdf"
    path.write_bytes(b"not a PDF")
    with pytest.raises(InputError, match="parser rejected"):
        read_sop_isolated(path)


def acceptance_module():
    spec = importlib.util.spec_from_file_location("veriq_acceptance", ROOT / "deployment/acceptance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
