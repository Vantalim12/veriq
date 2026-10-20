import importlib.util
import json
from pathlib import Path
import tarfile

import pytest

from veriq.ingestion import InputError

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "deployment/appwrite" / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_function_package_excludes_inputs_secrets_and_preserves_existing_archive(tmp_path):
    package = module("package").package
    output = tmp_path / "function.tar.gz"
    package(ROOT, output)
    before = output.read_bytes()
    with tarfile.open(output) as archive:
        names = archive.getnames()
        assert "requirements.txt" in names
        assert "src/veriq/appwrite_function.py" in names
        assert "deployment/appwrite/main.py" in names
        assert "deployment/appwrite/cleanup.py" in names
        assert {"src/veriq/web/upload.html", "src/veriq/web/upload.css", "src/veriq/web/upload.js",
                "src/veriq/web/sign-in.html", "src/veriq/web/sign-in.js", "src/veriq/web/favicon.png"} <= set(names)
        assert all(name in {"README.md", "pyproject.toml", "constraints.txt", "requirements.txt",
                           "deployment/appwrite/main.py", "deployment/appwrite/cleanup.py",
                           "src/veriq/web/upload.html", "src/veriq/web/upload.css", "src/veriq/web/upload.js",
                           "src/veriq/web/sign-in.html", "src/veriq/web/sign-in.js", "src/veriq/web/favicon.png"}
                   or (name.startswith("src/veriq/") and name.endswith(".py")) for name in names)
        assert all(member.isfile() for member in archive.getmembers())
        assert not any(name.startswith(("examples/", "reports/", ".env", "tests/")) for name in names)
    assert output.stat().st_mode & 0o077 == 0
    with pytest.raises(InputError):
        package(ROOT, output)
    assert output.read_bytes() == before


def test_private_resource_spec_and_no_public_cleanup_entrypoint():
    spec = json.loads((ROOT / "deployment/appwrite/resources.json").read_text())
    for resource in [spec["bucket"], spec["database"], *spec["tables"]]:
        assert resource["enabled"] is False
        assert resource.get("permissions", []) == []
    assert spec["bucket"]["encryption"] is True
    api, cleanup = spec["functions"]
    assert api["execute"] == ["any"]
    assert cleanup["execute"] == [] and cleanup["schedule"] == "*/5 * * * *"
    assert all(f["timeout"] < 600 and f["runtime"] == "python-3.12" for f in spec["functions"])
    assert not any("key" in key.lower() for key in spec["functions"][0])


def test_provision_preserves_existing_resources_and_rejects_public_permissions():
    pytest.importorskip("httpx")
    pytest.importorskip("mcp")
    pytest.importorskip("jwt")
    provision = module("provision")
    from veriq.appwrite_store import AppwriteError
    class API:
        def __init__(self):
            self.resources = {}
            self.writes = 0
        def request(self, method, path, *, json=None):
            if method == "GET":
                if path not in self.resources:
                    raise AppwriteError(404)
                return self.resources[path]
            assert method == "POST"
            self.writes += 1
            identifier = next(json[key] for key in ("bucketId", "databaseId", "tableId", "functionId") if key in json)
            resource = dict(json)
            if "permissions" in resource:
                resource["$permissions"] = resource.pop("permissions")
            self.resources[path + "/" + identifier] = resource
            return resource
    api = API()
    spec = json.loads((ROOT / "deployment/appwrite/resources.json").read_text())
    provision.provision(api, spec)
    writes = api.writes
    provision.provision(api, spec)
    assert api.writes == writes == 6
    api.resources["/storage/buckets/veriq-private"]["$permissions"] = ['read("any")']
    with pytest.raises(InputError, match="permissions"):
        provision.provision(api, spec)
    assert api.writes == writes
