import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from pydantic import ValidationError

pytest.importorskip("mcp")
pytest.importorskip("jwt")

from veriq.cli import main
from veriq.ingestion import InputError
from veriq.plugin_package import build_plugin

ROOT = Path(__file__).resolve().parents[1]


def test_plugin_zip_is_repeatable_and_contains_only_public_package_files(tmp_path):
    config = ROOT / "deployment/plugin.example.json"
    first, second = tmp_path / "one.zip", tmp_path / "two.zip"
    build_plugin(config, first, ROOT)
    build_plugin(config, second, ROOT)
    assert first.read_bytes() == second.read_bytes()
    assert first.stat().st_mode & 0o077 == 0
    with ZipFile(first) as archive:
        assert sorted(archive.namelist()) == ["assets/icon.png", "mcp.json", "plugin.json", "skills/veriq-auditor/SKILL.md"]
        plugin = json.loads(archive.read("plugin.json"))
        server = json.loads(archive.read("mcp.json"))["mcpServers"]["veriq"]
        assert server["url"] == "https://veriq.example.com/mcp"
        auth = server["extensions"]["com.openai"]["auth"]
        assert auth["type"] == "oauth" and auth["client"]["tokenEndpointAuthMethod"] == "none"
        assert auth["baseScopes"] == ["veriq:read"]
        assert plugin["extensions"]["com.openai"]["interface"]["privacyPolicyURL"].startswith("https://")
    with pytest.raises(InputError, match="new path"):
        build_plugin(config, first, ROOT)


@pytest.mark.parametrize("update", [{"client_secret": "SENSITIVE"}, {"origin": "http://unsafe.example.com"},
                                    {"support_url": "https://user:password@example.com"}, {"publisher": "   "}])
def test_plugin_rejects_credentials_and_invalid_metadata(tmp_path, update):
    config = json.loads((ROOT / "deployment/plugin.example.json").read_text())
    config.update(update)
    source, output = tmp_path / "config.json", tmp_path / "plugin.zip"
    source.write_text(json.dumps(config))
    with pytest.raises((InputError, ValidationError)):
        build_plugin(source, output, ROOT)
    assert not output.exists()


def test_plugin_cli_builds_and_preserves_existing_output(tmp_path):
    path = tmp_path / "plugin.zip"
    args = ["plugin", "--config", str(ROOT / "deployment/plugin.example.json"), "--repo-root", str(ROOT), "--output", str(path)]
    assert main(args) == 0
    before = path.read_bytes()
    assert main(args) == 2
    assert path.read_bytes() == before


def test_serve_fails_closed_without_oauth_settings(monkeypatch, capsys):
    for key in ("VERIQ_PUBLIC_ORIGIN", "VERIQ_OAUTH_ISSUER", "VERIQ_JWKS_URL"):
        monkeypatch.delenv(key, raising=False)
    assert main(["serve"]) == 2
    assert "configure VERIQ_PUBLIC_ORIGIN" in capsys.readouterr().err
