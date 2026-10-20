import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import time
import threading
from types import SimpleNamespace

import pytest

pytest.importorskip("mcp")
jwt = pytest.importorskip("jwt")
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

from veriq.artifacts import ArtifactStore, KINDS
from veriq.hosted import create_app
from veriq.hosted_auth import HostedSettings, JWTVerifier, READ_SCOPE, UPLOAD_SCOPE
from veriq.ingestion import InputError, read_policy, read_workflow
from veriq.verifier import verify

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("token", ["", "test-domain-challenge_token-123"])
def test_domain_challenge_is_public_plain_text(tmp_path, monkeypatch, token):
    monkeypatch.setenv("VERIQ_PUBLIC_ORIGIN", "https://veriq.test")
    monkeypatch.setenv("VERIQ_OAUTH_ISSUER", "https://identity.test/")
    monkeypatch.setenv("VERIQ_JWKS_URL", "https://identity.test/jwks")
    monkeypatch.setenv("VERIQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VERIQ_OPENAI_DOMAIN_TOKEN", token)
    config = HostedSettings.from_environment()
    with TestClient(create_app(config), base_url=config.origin) as client:
        response = client.get("/.well-known/openai-apps-challenge")
        assert response.status_code == (200 if token else 404)
        if token:
            assert response.text == token
            assert response.headers["content-type"].startswith("text/plain")
        assert client.post("/mcp", json={}).status_code == 401


@pytest.fixture
def settings(tmp_path):
    return HostedSettings("https://veriq.test", "https://identity.test/", "https://identity.test/jwks", tmp_path / "data")


@pytest.fixture
def signing_key(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(jwt.PyJWKClient, "get_signing_key_from_jwt", lambda self, token: SimpleNamespace(key=key.public_key()))
    return key


def bearer(key, settings, subject="alice", **updates):
    claims = {"iss": settings.issuer, "aud": settings.resource, "sub": subject, "iat": int(time.time()),
              "exp": int(time.time()) + 3600, "scope": f"{READ_SCOPE} {UPLOAD_SCOPE}", "client_id": "chatgpt"}
    claims.update(updates)
    return "Bearer " + jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})


@pytest.mark.parametrize("changes", [{"aud": "https://another-resource.test/mcp"}, {"iss": "https://other-issuer.test/"},
                                      {"exp": 1}, {"sub": ""}, {"scope": [READ_SCOPE]}, {"iat": int(time.time()) + 10000}])
def test_jwt_rejects_invalid_claims(settings, signing_key, changes):
    token = bearer(signing_key, settings, **changes).removeprefix("Bearer ")
    assert asyncio.run(JWTVerifier(settings).verify_token(token)) is None


def test_jwt_rejects_bad_signature_and_unsigned(settings, signing_key):
    verifier = JWTVerifier(settings)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert asyncio.run(verifier.verify_token(bearer(other, settings).split(" ")[1])) is None
    assert asyncio.run(verifier.verify_token("garbage")) is None
    good = asyncio.run(verifier.verify_token(bearer(signing_key, settings).split(" ")[1]))
    assert good.subject == "alice" and good.resource == settings.resource


def upload(client, auth, kind, name):
    result = client.post("/artifacts/" + kind, content=(ROOT / "examples" / name).read_bytes(),
                         headers={"Authorization": auth, "Content-Type": "application/octet-stream"})
    assert result.status_code == 201, result.text
    assert "/" not in result.json()["artifact_id"]
    return result.json()["artifact_id"]


def rpc(client, auth, method, params=None):
    result = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                         headers={"Authorization": auth, "Accept": "application/json, text/event-stream"})
    assert result.status_code == 200, result.text
    return result.json()["result"]


def test_hosted_auth_upload_verification_and_tenant_isolation(settings, signing_key):
    alice, bob = [bearer(signing_key, settings, user) for user in ("alice", "bob")]
    with TestClient(create_app(settings), base_url=settings.origin) as client:
        unauthenticated = client.post("/mcp", json={})
        assert unauthenticated.status_code == 401
        assert "resource_metadata=" in unauthenticated.headers["www-authenticate"]
        metadata = client.get("/.well-known/oauth-protected-resource/mcp")
        assert metadata.status_code == 200
        assert metadata.json()["resource"] == settings.resource
        assert metadata.json()["authorization_servers"] == [settings.issuer]
        assert client.post("/artifacts/workflow", content=b"{}", headers={"Content-Type": "application/octet-stream"}).status_code == 401
        limited = bearer(signing_key, settings, scope=READ_SCOPE)
        assert client.post("/artifacts/workflow", content=b"{}", headers={"Authorization": limited}).status_code == 403
        assert client.get("/healthz").status_code == 200
        assert client.get("/healthz", headers={"Host": "attacker.test"}).status_code == 400
        assert client.get("/healthz", headers={"Origin": "https://attacker.test"}).status_code == 403
        workflow = upload(client, alice, "workflow", "purchase-v2.json")
        baseline = upload(client, alice, "workflow", "purchase-v1.json")
        policy = upload(client, alice, "policy", "veriq.rules.yaml")
        tools = rpc(client, alice, "tools/list")["tools"]
        assert len(tools) == 7
        assert all(t["securitySchemes"] == [{"type": "oauth2", "scopes": [READ_SCOPE]}] for t in tools)
        audit = rpc(client, alice, "tools/call", {"name": "compare_workflow_versions", "arguments": {
            "workflow": workflow, "baseline": baseline, "rules": policy}})["structuredContent"]
        rules, policy_hash = read_policy(ROOT / "examples/veriq.rules.yaml")
        expected = verify(read_workflow(ROOT / "examples/purchase-v2.json"), rules, policy_hash, read_workflow(ROOT / "examples/purchase-v1.json"))
        assert audit == expected
        assert audit["summary"]["exit_code"] == 1
        for reference in (workflow, "../purchase-v2.json", "/etc/passwd", "https://example.test/workflow.json"):
            result = rpc(client, bob, "tools/call", {"name": "ingest_n8n_workflow", "arguments": {"relative_path": reference}})
            assert result["isError"] is True
        inaccessible = rpc(client, bob, "tools/call", {"name": "get_audit_finding", "arguments": {"audit_id": audit["audit_id"], "finding_id": "REQ-004"}})
        assert inaccessible["isError"] is True
        own = rpc(client, alice, "tools/call", {"name": "get_audit_finding", "arguments": {"audit_id": audit["audit_id"], "finding_id": "REQ-004"}})
        assert own["structuredContent"] == audit["findings"][0]
        assert client.delete("/artifacts/" + workflow, headers={"Authorization": bob}).status_code == 404
        assert client.delete("/artifacts/" + workflow, headers={"Authorization": alice}).status_code == 200
        assert rpc(client, alice, "tools/call", {"name": "ingest_n8n_workflow", "arguments": {"relative_path": workflow}})["isError"]
        assert metadata.headers["cache-control"] == "no-store"


def test_upload_invalid_size_format_and_cleanup(settings, signing_key, monkeypatch):
    auth = bearer(signing_key, settings)
    with TestClient(create_app(settings), base_url=settings.origin) as client:
        headers = {"Authorization": auth, "Content-Type": "application/octet-stream"}
        assert client.post("/artifacts/workflow", content=b"not JSON", headers=headers).status_code == 400
        assert client.post("/artifacts/evil", content=b"bad", headers=headers).status_code == 400
        assert client.post("/artifacts/workflow", content=b"{}", headers={"Authorization": auth}).status_code == 415
        monkeypatch.setitem(KINDS, "workflow", (".json", 3, read_workflow))
        assert client.post("/artifacts/workflow", content=b"1234", headers=headers).status_code == 413
        assert client.post("/artifacts/workflow", content=iter([b"12", b"34"]), headers=headers).status_code == 413
        assert list(settings.data_dir.glob("*/*")) == []


def test_health_and_upload_remain_responsive_during_verification(settings, signing_key, monkeypatch):
    started, release, finished = (threading.Event() for _ in range(3))

    def blocked_verify(*args, **kwargs):
        started.set()
        try:
            if not release.wait(10):
                raise TimeoutError("test did not release verification")
            return verify(*args, **kwargs)
        finally:
            finished.set()

    monkeypatch.setattr("veriq.mcp_server.verify", blocked_verify)
    alice, bob = [bearer(signing_key, settings, user) for user in ("alice", "bob")]
    with TestClient(create_app(settings), base_url=settings.origin) as client:
        workflow = upload(client, alice, "workflow", "purchase-v2.json")
        policy = upload(client, alice, "policy", "veriq.rules.yaml")
        with ThreadPoolExecutor(max_workers=1) as workers:
            pending = workers.submit(rpc, client, alice, "tools/call", {
                "name": "verify_workflow_rules", "arguments": {"workflow": workflow, "rules": policy}})
            try:
                assert started.wait(5), "verification did not start"
                assert client.get("/healthz").status_code == 200
                upload(client, bob, "workflow", "purchase-v1.json")
                assert not finished.is_set(), "other HTTP requests waited for verification"
            finally:
                release.set()
            audit = pending.result(timeout=5)["structuredContent"]
        assert audit["summary"]["exit_code"] == 1
        arguments = {"audit_id": audit["audit_id"], "finding_id": "REQ-004"}
        assert rpc(client, alice, "tools/call", {"name": "get_audit_finding", "arguments": arguments})[
            "structuredContent"] == audit["findings"][0]
        assert rpc(client, bob, "tools/call", {"name": "get_audit_finding", "arguments": arguments})["isError"]


def test_hosted_sop_draft_returns_complete_requirements_and_separate_instructions(settings, signing_key):
    auth = bearer(signing_key, settings)
    with TestClient(create_app(settings), base_url=settings.origin) as client:
        uploaded = client.post("/artifacts/pdf", content=(ROOT / "tests/fixtures/purchasing-approval-sop.pdf").read_bytes(),
                               headers={"Authorization": auth, "Content-Type": "application/octet-stream"})
        assert uploaded.status_code == 201
        draft = rpc(client, auth, "tools/call", {"name": "draft_sop_requirements", "arguments": {
            "relative_path": uploaded.json()["artifact_id"]}})["structuredContent"]
        assert [candidate["requirement_id"] for candidate in draft["candidates"]] == [f"REQ-{n:03}" for n in range(1, 9)]
        assert draft["generator"] == "heuristic-2"
        assert "MAY be processed" in draft["candidates"][4]["source"]["quote"]
        assert "not external persistence" in draft["candidates"][5]["source"]["quote"]
        assert len(draft["verification_instructions"]) == 3
        assert client.delete("/artifacts/" + uploaded.json()["artifact_id"], headers={"Authorization": auth}).status_code == 200


def test_artifact_expiry_quotas_and_private_permissions(tmp_path, monkeypatch):
    store = ArtifactStore(tmp_path / "data")
    owner = "a" * 64
    with store.temporary(owner, "workflow") as path:
        path.write_bytes((ROOT / "examples/purchase-v1.json").read_bytes())
        result = store.commit(owner, "workflow", path)
    stored = store.resolve(owner, result["artifact_id"], {".json"})
    assert stored.stat().st_mode & 0o077 == 0
    assert stored.parent.stat().st_mode & 0o077 == 0
    with pytest.raises(InputError):
        store.resolve("b" * 64, result["artifact_id"], {".json"})
    monkeypatch.setattr("veriq.artifacts.MAX_USER_FILES", 1)
    with store.temporary(owner, "workflow") as path:
        path.write_bytes(stored.read_bytes())
        with pytest.raises(InputError, match="quota"):
            store.commit(owner, "workflow", path)
    os.utime(stored, (1, 1))
    with pytest.raises(InputError, match="expired"):
        store.resolve(owner, result["artifact_id"], {".json"})
    store.prune()
    assert not stored.exists()


@pytest.mark.parametrize("origin", ["http://veriq.test", "https://user:password@veriq.test", "https://veriq.test/", "https://veriq.test/path", "https://veriq.test?query=1"])
def test_hosted_config_rejects_unsafe_public_origin(tmp_path, origin):
    with pytest.raises(InputError):
        HostedSettings(origin, "https://identity.test/", "https://identity.test/jwks", tmp_path)


def test_oauth_discovery_preserves_exact_issuer_without_trailing_slash(tmp_path):
    settings = HostedSettings("https://veriq.test", "https://identity.test", "https://identity.test/jwks", tmp_path)
    with TestClient(create_app(settings), base_url=settings.origin) as client:
        response = client.get("/.well-known/oauth-protected-resource/mcp")
        assert response.json()["authorization_servers"] == ["https://identity.test"]
        assert set(response.json()["scopes_supported"]) == {READ_SCOPE, UPLOAD_SCOPE}
