import asyncio
from copy import deepcopy
import json
from pathlib import Path
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("mcp")
pytest.importorskip("jwt")

from test_hosted import settings, signing_key, bearer
from veriq.browser_upload import COOKIE
from veriq.appwrite_function import main, cleanup
from veriq.appwrite_store import AppwriteAPI, AppwriteError, AppwriteStore
from veriq.ingestion import InputError

ROOT = Path(__file__).resolve().parents[1]


class MemoryAppwrite:
    """Service simulator with atomic commits, conflicts and chunked Storage writes."""
    def __init__(self):
        self.tables = {"objects": {}, "quotas": {}}
        self.files = {}
        self.transactions = {}
        self.version = 0
        self.conflict = False
        self.fail_upload = False
        self.calls = []

    def close(self):
        pass

    def request(self, method, path, *, json=None, params=None, **kwargs):
        self.calls.append((method, path, deepcopy(json), deepcopy(kwargs)))
        parts = path.strip("/").split("/")
        if parts[:2] == ["tablesdb", "transactions"]:
            if method == "POST":
                tx = uuid4().hex
                self.transactions[tx] = (self.version, deepcopy(self.tables))
                return {"$id": tx}
            version, tables = self.transactions[parts[2]]
            if json.get("commit"):
                if self.conflict:
                    self.conflict = False
                    raise AppwriteError(409)
                if version != self.version:
                    raise AppwriteError(409)
                self.tables = tables
                self.version += 1
            del self.transactions[parts[2]]
            return {}
        if parts[0] == "storage":
            key = parts[4] if len(parts) > 4 else kwargs.get("data", {}).get("fileId")
            if method == "POST":
                if self.fail_upload:
                    raise AppwriteError(503)
                chunk = kwargs["files"]["file"][1]
                self.files[key] = self.files.get(key, b"") + chunk
                return {"$id": key}
            if key not in self.files:
                raise AppwriteError(404)
            if method == "DELETE":
                del self.files[key]
                return {}
            return self.files[key]
        table = parts[3]
        tx = (json or {}).get("transactionId") or (dict(params or {}).get("transactionId"))
        tables = self.transactions[tx][1] if tx else self.tables
        rows = tables[table]
        key = parts[5] if len(parts) > 5 else (json or {}).get("rowId")
        if method == "GET" and key is None:
            from json import loads
            selected = list(rows.values())
            limit = 25
            for _, encoded in params or []:
                q = loads(encoded)
                attr, values = q.get("attribute"), q.get("values", [])
                if q["method"] == "equal":
                    selected = [r for r in selected if r[attr] in values]
                elif q["method"] == "lessThanEqual":
                    selected = [r for r in selected if r[attr] <= values[0]]
                elif q["method"] == "greaterThan":
                    selected = [r for r in selected if r[attr] > values[0]]
                elif q["method"] in {"orderAsc", "orderDesc"}:
                    selected.sort(key=lambda r: r[attr], reverse=q["method"] == "orderDesc")
                elif q["method"] == "limit":
                    limit = values[0]
            return {"rows": deepcopy(selected[:limit])}
        if method == "POST":
            assert json["permissions"] == []
            if key in rows:
                raise AppwriteError(409)
            rows[key] = {"$id": key, **json["data"]}
        elif key not in rows:
            raise AppwriteError(404)
        elif method == "GET":
            return deepcopy(rows[key])
        elif method == "DELETE":
            del rows[key]
        elif len(parts) == 8:
            column, operation = parts[6:]
            value = rows[key][column] + (json["value"] if operation == "increment" else -json["value"])
            if value > json.get("max", value) or value < json.get("min", value):
                raise AppwriteError(400)
            rows[key][column] = value
        else:
            rows[key].update(json["data"])
        if not tx:
            self.version += 1
        return deepcopy(rows.get(key, {}))


class Response:
    def binary(self, body, status=200, headers=None):
        return SimpleNamespace(body=body, status=status, headers=headers or {})

    def json(self, body, status=200, headers=None):
        return self.binary(json.dumps(body).encode(), status, headers)


@pytest.fixture
def cloud(settings, signing_key, monkeypatch):
    backend = MemoryAppwrite()
    roots = []
    def configured(root):
        roots.append(root)
        return AppwriteStore(root, backend)
    monkeypatch.setattr("veriq.appwrite_function.configured_store", configured)
    monkeypatch.setenv("VERIQ_PUBLIC_ORIGIN", settings.origin)
    monkeypatch.setenv("VERIQ_OAUTH_ISSUER", settings.issuer)
    monkeypatch.setenv("VERIQ_JWKS_URL", settings.jwks_url)

    def invoke(path, *, method="GET", body=b"", user="alice", headers=None, entry=main):
        incoming = {"host": "veriq.test", "accept": "application/json, text/event-stream",
                    "content-type": "application/octet-stream", "x-appwrite-trigger": "http", **(headers or {})}
        if user:
            incoming["authorization"] = bearer(signing_key, settings, user)
        request = SimpleNamespace(path=path, query_string="", method=method, body_binary=body, headers=incoming)
        context = SimpleNamespace(req=request, res=Response(), error=lambda message: None)
        result = asyncio.run(entry(context))
        assert all(not root.exists() for root in roots)
        return result
    return backend, invoke


def uploaded(invoke, kind, filename):
    response = invoke("/artifacts/" + kind, method="POST", body=(ROOT / "examples" / filename).read_bytes())
    assert response.status == 201, response.body
    return json.loads(response.body)["artifact_id"]


def rpc(invoke, method, params=None, user="alice"):
    response = invoke("/mcp", method="POST", user=user, headers={"content-type": "application/json"},
        body=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}).encode())
    assert response.status == 200, response.body
    return json.loads(response.body)["result"]


def test_function_cold_starts_preserve_inputs_audits_and_identity(cloud):
    backend, invoke = cloud
    assert invoke("/healthz", user=None).status == 200
    metadata = invoke("/.well-known/oauth-protected-resource/mcp", user=None)
    assert json.loads(metadata.body)["resource"] == "https://veriq.test/mcp"
    challenge = invoke("/mcp", method="POST", user=None)
    assert challenge.status == 401 and "resource_metadata=" in challenge.headers["www-authenticate"]
    assert invoke("/artifacts/workflow", method="POST", user=None,
                  headers={"x-appwrite-trigger": "schedule", "x-appwrite-key": "untrusted"}).status == 401
    workflow = uploaded(invoke, "workflow", "purchase-v2.json")
    baseline = uploaded(invoke, "workflow", "purchase-v1.json")
    policy = uploaded(invoke, "policy", "veriq.rules.yaml")
    audit = rpc(invoke, "tools/call", {"name": "compare_workflow_versions", "arguments": {
        "workflow": workflow, "baseline": baseline, "rules": policy}})["structuredContent"]
    assert audit["summary"]["exit_code"] == 1
    exported = rpc(invoke, "tools/call", {"name": "export_audit_report", "arguments": {"audit_id": audit["audit_id"]}})
    assert json.loads(exported["content"][0]["text"]) == audit
    for name, args in [("ingest_n8n_workflow", {"relative_path": workflow}),
                       ("export_audit_report", {"audit_id": audit["audit_id"]})]:
        assert rpc(invoke, "tools/call", {"name": name, "arguments": args}, user="bob")["isError"]
    assert invoke("/artifacts/" + workflow, method="DELETE", user="bob").status == 404
    assert invoke("/artifacts/" + workflow, method="DELETE").status == 200
    assert rpc(invoke, "tools/call", {"name": "ingest_n8n_workflow", "arguments": {"relative_path": workflow}})["isError"]
    assert len(backend.files) == 3


def test_cloud_quota_rollback_failed_upload_and_cleanup(cloud, monkeypatch):
    backend, invoke = cloud
    monkeypatch.setattr("veriq.appwrite_store.MAX_USER_FILES", 1)
    backend.conflict = True
    artifact = uploaded(invoke, "workflow", "purchase-v1.json")
    rejected = invoke("/artifacts/workflow", method="POST", body=(ROOT / "examples/purchase-v2.json").read_bytes())
    assert rejected.status == 400
    assert len(backend.files) == 1
    assert backend.tables["quotas"]["artifact-global"]["count"] == 1
    for row in backend.tables["objects"].values():
        row["expires"] = int(time.time()) - 1
    missing = rpc(invoke, "tools/call", {"name": "ingest_n8n_workflow", "arguments": {"relative_path": artifact}})
    assert missing["isError"]
    assert invoke("/", entry=cleanup, user=None).status == 404
    assert backend.files
    assert json.loads(invoke("/", entry=cleanup, user=None, headers={"x-appwrite-trigger": "schedule"}).body) == {"removed": 1}
    assert not backend.files and not backend.tables["objects"]
    assert backend.tables["quotas"]["artifact-global"]["count"] == 0
    backend.fail_upload = True
    assert invoke("/artifacts/workflow", method="POST", body=(ROOT / "examples/purchase-v1.json").read_bytes()).status == 503
    assert backend.tables["quotas"]["artifact-global"]["count"] == 0
    assert not backend.tables["objects"]


def test_cloud_byte_quota_is_atomic(tmp_path, monkeypatch):
    backend = MemoryAppwrite()
    store = AppwriteStore(tmp_path, backend)
    monkeypatch.setattr("veriq.appwrite_store.MAX_USER_BYTES", 1)
    with pytest.raises(InputError, match="quota"):
        store.put(uuid4().hex, "a" * 64, "workflow", b"too big", "file.json", "ref")
    assert not backend.tables["objects"]
    assert all(row["count"] == row["bytes"] == 0 for row in backend.tables["quotas"].values())


def test_audit_eviction_never_removes_an_inflight_reservation(tmp_path):
    backend = MemoryAppwrite()
    store = AppwriteStore(tmp_path, backend)
    owner = "a" * 64
    for number in range(8):
        store.reserve(uuid4().hex, owner, "audit", 100, "sha256:" + f"{number:064x}")
    before = deepcopy(backend.tables["objects"])
    with pytest.raises(InputError, match="quota"):
        store.save_audit(owner, {"audit_id": "sha256:" + "f" * 64})
    assert backend.tables["objects"] == before
    assert backend.tables["quotas"]["audit-global"]["count"] == 8


def test_cloud_audit_expiry_eviction_and_binary_chunks(tmp_path):
    backend = MemoryAppwrite()
    store = AppwriteStore(tmp_path, backend)
    owner = "a" * 64
    for number in range(9):
        store.save_audit(owner, {"audit_id": "sha256:" + f"{number:064x}", "findings": []})
    assert len(backend.files) == 8
    assert backend.tables["quotas"]["audit-global"]["count"] == 8
    with pytest.raises(InputError):
        store.load_audit(owner, "sha256:" + "0" * 64)
    latest = "sha256:" + f"{8:064x}"
    assert store.load_audit(owner, latest)["audit_id"] == latest
    with pytest.raises(InputError):
        store.load_audit("b" * 64, latest)
    for row in backend.tables["objects"].values():
        row["expires"] = 1
    with pytest.raises(InputError):
        store.load_audit(owner, latest)
    store.prune()
    payload = bytes(range(256)) * 24000
    store.upload_blob("chunk-test", payload, "input.pdf")
    assert backend.files["chunk-test"] == payload
    uploads = [call for call in backend.calls if call[1].endswith("/files") and call[0] == "POST"]
    assert uploads[-1][3]["headers"]["Content-Range"].endswith("/" + str(len(payload)))
    assert uploads[-1][3]["headers"]["X-Appwrite-ID"] == "chunk-test"


def test_audits_rotate_per_owner_and_global_pressure_never_deletes_other_users(tmp_path, monkeypatch):
    backend = MemoryAppwrite()
    store = AppwriteStore(tmp_path, backend)
    for owner in ("a" * 64, "b" * 64):
        for number in range(9):
            store.save_audit(owner, {"audit_id": "sha256:" + f"{number:064x}"})
    assert backend.tables["quotas"]["audit-global"]["count"] == 16
    for owner in ("a" * 64, "b" * 64):
        assert store.load_audit(owner, "sha256:" + f"{1:064x}")
        with pytest.raises(InputError):
            store.load_audit(owner, "sha256:" + f"{0:064x}")
    monkeypatch.setattr("veriq.appwrite_store.MAX_TOTAL_AUDITS", 16)
    before = deepcopy(backend.tables)
    blobs = deepcopy(backend.files)
    with pytest.raises(InputError, match="quota"):
        store.save_audit("c" * 64, {"audit_id": "sha256:" + "f" * 64})
    assert backend.tables["objects"] == before["objects"]
    assert backend.files == blobs


@pytest.mark.parametrize("limit", ["bytes", "count"])
def test_rejected_audit_replacement_preserves_existing_reports(tmp_path, monkeypatch, limit):
    backend = MemoryAppwrite()
    store = AppwriteStore(tmp_path, backend)
    owner = "a" * 64
    for number in range(8):
        store.save_audit(owner, {"audit_id": "sha256:" + f"{number:064x}"})
    total = backend.tables["quotas"]["audit-global"]
    if limit == "bytes":
        monkeypatch.setattr("veriq.appwrite_store.MAX_TOTAL_AUDIT_BYTES", total["bytes"])
    else:
        monkeypatch.setattr("veriq.appwrite_store.MAX_TOTAL_AUDITS", total["count"] - 1)
    before = deepcopy(backend.tables)
    blobs = deepcopy(backend.files)
    with pytest.raises(InputError, match="quota"):
        store.save_audit(owner, {"audit_id": "sha256:" + "f" * 64, "padding": "x" * 2000})
    assert backend.tables == before
    assert backend.files == blobs


def test_audit_replacement_can_fill_global_caps_exactly(tmp_path, monkeypatch):
    backend = MemoryAppwrite()
    store = AppwriteStore(tmp_path, backend)
    owner = "a" * 64
    for number in range(8):
        store.save_audit(owner, {"audit_id": "sha256:" + f"{number:064x}"})
    total = deepcopy(backend.tables["quotas"]["audit-global"])
    monkeypatch.setattr("veriq.appwrite_store.MAX_TOTAL_AUDITS", total["count"])
    monkeypatch.setattr("veriq.appwrite_store.MAX_TOTAL_AUDIT_BYTES", total["bytes"])
    result = {"audit_id": "sha256:" + "f" * 64}
    store.save_audit(owner, result)
    assert store.load_audit(owner, result["audit_id"]) == result
    assert backend.tables["quotas"]["audit-global"] == total
    assert len(backend.files) == 8


@pytest.mark.parametrize("failure", ["upload", "finalize"])
def test_failed_audit_replacement_preserves_reports_and_quotas(tmp_path, monkeypatch, failure):
    backend = MemoryAppwrite()
    store = AppwriteStore(tmp_path, backend)
    owner = "a" * 64
    for number in range(8):
        store.save_audit(owner, {"audit_id": "sha256:" + f"{number:064x}"})
    before, blobs = deepcopy(backend.tables), deepcopy(backend.files)
    request = backend.request
    def fail_finalize(method, path, **kwargs):
        payload = kwargs.get("json") or {}
        if payload.get("transactionId") and payload.get("data", {}).get("state") == "ready":
            raise AppwriteError(503)
        return request(method, path, **kwargs)
    if failure == "upload":
        backend.fail_upload = True
    else:
        monkeypatch.setattr(backend, "request", fail_finalize)
    with pytest.raises(AppwriteError):
        store.save_audit(owner, {"audit_id": "sha256:" + "f" * 64})
    assert backend.tables == before
    assert backend.files == blobs
    for number in range(8):
        assert store.load_audit(owner, "sha256:" + f"{number:064x}")


def test_replacement_keeps_old_report_readable_and_retries_transaction_conflicts(tmp_path, monkeypatch):
    backend = MemoryAppwrite()
    store = AppwriteStore(tmp_path, backend)
    owner = "a" * 64
    for number in range(8):
        store.save_audit(owner, {"audit_id": "sha256:" + f"{number:064x}"})
    upload = store.upload_blob
    def staged(*args):
        assert store.load_audit(owner, "sha256:" + "0" * 64)
        assert backend.tables["quotas"]["audit-global"]["count"] == 9
        with pytest.raises(InputError):
            store.save_audit(owner, {"audit_id": "sha256:" + "e" * 64})
        upload(*args)
        backend.conflict = True
    monkeypatch.setattr(store, "upload_blob", staged)
    result = {"audit_id": "sha256:" + "f" * 64}
    store.save_audit(owner, result)
    assert store.load_audit(owner, result["audit_id"]) == result
    assert backend.tables["quotas"]["audit-global"]["count"] == len(backend.files) == 8


def test_retired_audit_cleanup_is_retryable_and_still_counts_against_quota(tmp_path, monkeypatch):
    backend = MemoryAppwrite()
    store = AppwriteStore(tmp_path, backend)
    owner = "a" * 64
    for number in range(8):
        store.save_audit(owner, {"audit_id": "sha256:" + f"{number:064x}"})
    oldest = next(iter(backend.files))
    request = backend.request
    def fail_delete(method, path, **kwargs):
        if method == "DELETE" and path == f"{store.files}/{oldest}":
            raise AppwriteError(503)
        return request(method, path, **kwargs)
    monkeypatch.setattr(backend, "request", fail_delete)
    result = {"audit_id": "sha256:" + "f" * 64}
    store.save_audit(owner, result)
    assert store.load_audit(owner, result["audit_id"]) == result
    assert backend.tables["objects"][oldest]["state"] == "retired"
    assert backend.tables["quotas"]["audit-global"]["count"] == len(backend.files) == 9
    with pytest.raises(InputError):
        store.save_audit(owner, {"audit_id": "sha256:" + "e" * 64})
    monkeypatch.setattr(backend, "request", request)
    assert store.prune() == 1
    assert backend.tables["quotas"]["audit-global"]["count"] == len(backend.files) == 8


def test_lost_replacement_commit_response_does_not_delete_completed_report(tmp_path, monkeypatch):
    backend = MemoryAppwrite()
    store = AppwriteStore(tmp_path, backend)
    owner = "a" * 64
    for number in range(8):
        store.save_audit(owner, {"audit_id": "sha256:" + f"{number:064x}"})
    transaction = store.transaction
    def lost_response(operation):
        result = transaction(operation)
        if operation.__name__ == "finish":
            raise AppwriteError(503)
        return result
    monkeypatch.setattr(store, "transaction", lost_response)
    result = {"audit_id": "sha256:" + "f" * 64}
    with pytest.raises(AppwriteError):
        store.save_audit(owner, result)
    assert store.load_audit(owner, result["audit_id"]) == result
    assert store.prune() == 1
    assert backend.tables["quotas"]["audit-global"]["count"] == len(backend.files) == 8


def test_acceptance_runner_exercises_real_bridge_and_persistent_storage(cloud, settings, signing_key):
    from test_production_readiness import acceptance_module
    backend, invoke = cloud
    def transport(request):
        result = invoke(request.url.path, method=request.method, body=request.content,
                        user=None, headers=dict(request.headers))
        return httpx.Response(result.status, content=result.body, headers=result.headers)
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        result = acceptance_module().run_checks(client, settings.origin,
            bearer(signing_key, settings, "alice")[7:], bearer(signing_key, settings, "bob")[7:])
    assert result["status"] == "passed"
    assert len(result["checks"]) == 6
    assert all(row["category"] == "audit" for row in backend.tables["objects"].values())


def test_appwrite_http_boundary_keeps_json_download_binary_and_secrets_private():
    seen = []
    def handler(request):
        seen.append(request)
        if request.url.path.endswith("/bad"):
            return httpx.Response(403, json={"message": "PRIVATE_KEY_AND_BODY"})
        return httpx.Response(200, json={"workflow": "value"})
    api = AppwriteAPI("https://sgp.cloud.appwrite.io/v1", "project", "private-key",
                      transport=httpx.MockTransport(handler))
    try:
        assert isinstance(api.request("GET", "/download", binary=True), bytes)
        with pytest.raises(AppwriteError) as error:
            api.request("GET", "/bad")
        assert "PRIVATE" not in str(error.value)
        with pytest.raises(AppwriteError):
            api.request("GET", "/download", limit=1)
        assert seen[0].headers["x-appwrite-key"] == "private-key"
        assert str(seen[0].url) == "https://sgp.cloud.appwrite.io/v1/download"
    finally:
        api.close()


def test_function_rejects_oversize_wrong_host_and_missing_configuration(cloud, monkeypatch):
    _, invoke = cloud
    assert invoke("/mcp", method="POST", body=b"x" * (64 * 1024 + 1)).status == 413
    assert invoke("/healthz", headers={"host": "attacker.test"}).status == 400
    assert invoke("/healthz", headers={"origin": "https://attacker.test"}).status == 403
    monkeypatch.delenv("VERIQ_OAUTH_ISSUER")
    assert invoke("/healthz").status == 503


def test_function_forwards_browser_cookie_and_document_size_budget(cloud, settings, signing_key, monkeypatch):
    _, invoke = cloud
    monkeypatch.setenv("VERIQ_UPLOAD_CLIENT_ID", "public-upload-client")
    login = invoke("/upload/login", user=None)
    assert login.status == 303
    assert "code_challenge_method=S256" in login.headers["location"]
    assert "httponly" in login.headers["set-cookie"].lower()
    headers = {"cookie": COOKIE + "=" + bearer(signing_key, settings)[7:], "origin": settings.origin}
    # A valid JSON workflow larger than the MCP request budget must reach the artifact parser.
    workflow = (ROOT / "examples/purchase-v1.json").read_bytes() + b" " * (65 * 1024)
    response = invoke("/upload/artifacts/workflow", method="POST", user=None, body=workflow, headers=headers)
    assert response.status == 201, response.body
    assert invoke("/upload/session", user=None, headers=headers).status == 200
    assert json.loads(invoke("/upload/session", user=None, headers=headers).body)["signed_in"] is True
    assert invoke("/upload/artifacts/workflow", method="POST", user=None, body=workflow,
                  headers={"cookie": headers["cookie"]}).status == 403
    assert invoke("/upload/artifacts/pdf", method="POST", body=b"x" * (10 * 1024 * 1024 + 1),
                  user=None, headers=headers).status == 413
    logout = invoke("/upload/logout", method="POST", user=None, headers=headers)
    assert logout.status == 200 and "Max-Age=0" in logout.headers["set-cookie"]


@pytest.mark.parametrize("endpoint,key", [("http://insecure.test/v1", "key"),
                                         ("https://appwrite.test/wrong-path", "key"),
                                         ("https://appwrite.test/v1", "")])
def test_appwrite_configuration_rejects_unsafe_endpoint_and_missing_key(endpoint, key):
    with pytest.raises(InputError):
        AppwriteAPI(endpoint, "project", key)
