import base64
from dataclasses import replace
import hashlib
from io import BytesIO
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("mcp")
pytest.importorskip("jwt")
from starlette.testclient import TestClient

from test_hosted import ROOT, bearer, rpc, settings, signing_key
from veriq.browser_upload import COOKIE
from veriq.hosted import create_app
from veriq.hosted_auth import READ_SCOPE, UPLOAD_SCOPE


@pytest.fixture
def browser(settings, signing_key, monkeypatch):
    settings = replace(settings, upload_client_id="public-upload-client")
    calls = []
    original_client = httpx.AsyncClient
    def exchange(request):
        assert str(request.url) == "https://identity.test/oauth/token"
        assert "authorization" not in request.headers
        params = parse_qs(request.content.decode())
        assert params["grant_type"] == ["authorization_code"]
        assert params["client_id"] == [settings.upload_client_id]
        assert params["redirect_uri"] == [settings.origin + "/upload/callback"]
        assert params["resource"] == [settings.resource]
        assert "client_secret" not in params
        calls.append(params)
        return httpx.Response(200, json={"access_token": bearer(signing_key, settings, scope=UPLOAD_SCOPE)[7:],
                                         "token_type": "Bearer"})
    monkeypatch.setattr("veriq.browser_upload.httpx.AsyncClient",
                        lambda **kwargs: original_client(transport=httpx.MockTransport(exchange), **kwargs))
    with TestClient(create_app(settings), base_url=settings.origin) as client:
        yield client, settings, calls


def sign_in(client, settings):
    response = client.get("/upload/login", follow_redirects=False)
    assert response.status_code == 303
    params = parse_qs(urlsplit(response.headers["location"]).query)
    assert params["scope"] == [UPLOAD_SCOPE]
    assert params["resource"] == [settings.resource]
    assert params["code_challenge_method"] == ["S256"]
    assert params["redirect_uri"] == [settings.origin + "/upload/callback"]
    assert all(flag in response.headers["set-cookie"].lower() for flag in ("secure", "httponly", "samesite=lax", "path=/"))
    proof = client.cookies[COOKIE].split(".")[3]
    expected = base64.urlsafe_b64encode(hashlib.sha256(proof.encode()).digest()).decode().rstrip("=")
    assert params["code_challenge"] == [expected]
    query = urlencode({"code": "one-time-code", "state": params["state"][0], "iss": settings.issuer})
    response = client.get("/upload/callback?" + query, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/upload"
    assert client.get("/upload/session").json()["signed_in"] is True
    return proof


def test_browser_pkce_uploads_share_identity_with_mcp_and_isolate_other_users(browser, signing_key):
    client, settings, calls = browser
    assert client.get("/upload/session").json()["signed_in"] is False
    proof = sign_in(client, settings)
    assert calls[0]["code_verifier"] == [proof]
    headers = {"Origin": settings.origin, "Content-Type": "application/octet-stream"}
    ids = {}
    for kind, filename in [("workflow", "purchase-v2.json"), ("policy", "veriq.rules.yaml")]:
        result = client.post("/upload/artifacts/" + kind, content=(ROOT / "examples" / filename).read_bytes(), headers=headers)
        assert result.status_code == 201, result.text
        ids[kind] = result.json()["artifact_id"]
    audit = rpc(client, bearer(signing_key, settings), "tools/call", {"name": "verify_workflow_rules", "arguments": {
        "workflow": ids["workflow"], "rules": ids["policy"]}})
    assert "structuredContent" in audit
    denied = rpc(client, bearer(signing_key, settings, "bob"), "tools/call", {
        "name": "ingest_n8n_workflow", "arguments": {"relative_path": ids["workflow"]}})
    assert denied["isError"] is True
    # Cookie credentials never authorize the public API or MCP endpoints.
    assert client.post("/artifacts/workflow", headers=headers, content=b"{}").status_code == 401
    assert client.post("/mcp", json={}).status_code == 401
    assert client.get("/upload/callback?code=forged&state=forged", follow_redirects=False).status_code == 303
    assert client.get("/upload/session").json()["signed_in"] is True
    assert client.post("/upload/logout", headers={"Origin": settings.origin}).status_code == 200
    assert client.get("/upload/session").json()["signed_in"] is False
    assert client.post("/upload/artifacts/workflow", content=b"{}", headers=headers).status_code == 401


def test_browser_accepts_pdf_and_docx_through_the_existing_parsers(browser):
    client, settings, _ = browser
    sign_in(client, settings)
    import fitz
    from docx import Document
    with fitz.open() as document:
        document.new_page().insert_text((72, 72), "Approve every purchase before sending it.")
        pdf = document.tobytes()
    document = Document()
    document.add_paragraph("Approve every purchase before sending it.")
    stream = BytesIO()
    document.save(stream)
    for kind, content in [("pdf", pdf), ("docx", stream.getvalue())]:
        response = client.post("/upload/artifacts/" + kind, content=content,
                              headers={"Origin": settings.origin, "Content-Type": "application/octet-stream"})
        assert response.status_code == 201, response.text


@pytest.mark.parametrize("change", ["state", "issuer", "duplicate", "expired", "missing", "denied"])
def test_oauth_callback_rejects_unbound_or_failed_responses_without_exchange(browser, change):
    client, settings, calls = browser
    response = client.get("/upload/login", follow_redirects=False)
    params = parse_qs(urlsplit(response.headers["location"]).query)
    query = {"code": "secret-code", "state": params["state"][0], "iss": settings.issuer}
    if change == "state":
        query["state"] = "forged"
    elif change == "issuer":
        query["iss"] = "https://attacker.test"
    elif change == "missing":
        client.cookies.clear()
    elif change == "expired":
        parts = client.cookies[COOKIE].split(".")
        parts[1] = str(int(time.time()) - 601)
        client.cookies.set(COOKIE, ".".join(parts), domain="veriq.test", path="/")
    elif change == "denied":
        query["error"] = "access_denied"
    encoded = urlencode(query) + ("&state=another" if change == "duplicate" else "")
    response = client.get("/upload/callback?" + encoded, follow_redirects=False)
    assert response.headers["location"] == "/upload?login=failed"
    assert "secret-code" not in response.text
    assert not calls
    assert client.get("/upload/session").json()["signed_in"] is False


@pytest.mark.parametrize("claims,status", [({"scope": READ_SCOPE}, 403), ({"aud": "https://attacker.test/mcp"}, 401),
                                           ({"iss": "https://attacker.test"}, 401), ({"exp": 1}, 401)])
def test_browser_cookie_validation_preserves_existing_token_boundaries(browser, signing_key, claims, status):
    client, settings, _ = browser
    client.cookies.set(COOKIE, bearer(signing_key, settings, **claims)[7:], domain="veriq.test", path="/")
    assert client.get("/upload/session").json()["signed_in"] is False
    assert client.post("/upload/artifacts/workflow", content=b"{}", headers={
        "Origin": settings.origin, "Content-Type": "application/octet-stream"}).status_code == status


def test_browser_csrf_invalid_files_and_no_directory_traversal(browser):
    client, settings, _ = browser
    sign_in(client, settings)
    for origin in (None, "https://attacker.test", "null"):
        headers = {"Origin": origin} if origin else {}
        assert client.post("/upload/artifacts/workflow", content=b"{}", headers=headers).status_code == 403
        assert client.post("/upload/logout", headers=headers).status_code == 403
    headers = {"Origin": settings.origin, "Content-Type": "application/octet-stream"}
    assert client.post("/upload/artifacts/workflow", content=b"bad", headers=headers).status_code == 400
    assert client.post("/upload/artifacts/workflow", content=b"x" * (2 * 1024 * 1024 + 1), headers=headers).status_code == 413
    assert client.post("/upload/artifacts/unknown", content=b"{}", headers=headers).status_code == 400
    assert client.get("/upload/assets/hosted_auth.py").status_code == 404
    page = client.get("/upload")
    assert page.status_code == 200
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert page.headers["cache-control"] == "no-store"
    assert 'href="/upload/assets/favicon.png"' in page.text
    from veriq.semantics import SUPPORTED
    assert "{{COMPATIBILITY_NODES}}" not in page.text
    for kind, version in SUPPORTED.items():
        assert f"{kind.removeprefix('n8n-nodes-base.')} v{version}" in page.text
    assert "img-src 'self'" in page.headers["content-security-policy"]
    favicon = client.get("/upload/assets/favicon.png")
    assert favicon.status_code == 200 and favicon.headers["content-type"] == "image/png"
    assert favicon.content.startswith(b"\x89PNG\r\n\x1a\n")
    for name in ("upload.css", "upload.js"):
        assert client.get("/upload/assets/" + name).status_code == 200


def test_unconfigured_upload_login_fails_closed(settings):
    with TestClient(create_app(settings), base_url=settings.origin) as client:
        assert client.get("/upload").status_code == 200
        assert client.get("/upload/session").json() == {"configured": False, "signed_in": False}
        assert client.get("/upload/login", follow_redirects=False).status_code == 503


def test_upload_reports_unknown_node_versions_without_claiming_verification(browser):
    import json
    client, settings, _ = browser
    sign_in(client, settings)
    workflow = json.loads((ROOT / "examples/purchase-v1.json").read_text())
    workflow["nodes"][0]["typeVersion"] = 999
    response = client.post("/upload/artifacts/workflow", content=json.dumps(workflow).encode(),
        headers={"Origin": settings.origin, "Content-Type": "application/octet-stream"})
    assert response.status_code == 201
    coverage = response.json()["compatibility"]
    assert coverage["node_issues"][0]["node_id"] == workflow["nodes"][0]["id"]
    assert coverage["node_issues"][0]["typeVersion"] == 999
    assert "preflight" in coverage["note"]


@pytest.mark.parametrize("failure", ["unavailable", "timeout", "malformed", "oversize", "wrong_audience", "missing_scope"])
def test_failed_token_exchange_is_sanitized_and_never_creates_a_session(settings, signing_key, monkeypatch, failure):
    settings = replace(settings, upload_client_id="public-upload-client")
    original_client = httpx.AsyncClient
    def exchange(request):
        if failure == "unavailable":
            return httpx.Response(503, text="PRIVATE_PROVIDER_ERROR")
        if failure == "timeout":
            raise httpx.ReadTimeout("PRIVATE_PROVIDER_ERROR", request=request)
        if failure == "malformed":
            return httpx.Response(200, text="PRIVATE_PROVIDER_ERROR")
        if failure == "oversize":
            return httpx.Response(200, content=b"x" * (32 * 1024 + 1))
        claims = {"aud": "https://attacker.test/mcp"} if failure == "wrong_audience" else {"scope": READ_SCOPE}
        return httpx.Response(200, json={"access_token": bearer(signing_key, settings, **claims)[7:], "token_type": "Bearer"})
    monkeypatch.setattr("veriq.browser_upload.httpx.AsyncClient",
                        lambda **kwargs: original_client(transport=httpx.MockTransport(exchange), **kwargs))
    with TestClient(create_app(settings), base_url=settings.origin) as client:
        response = client.get("/upload/login", follow_redirects=False)
        params = parse_qs(urlsplit(response.headers["location"]).query)
        response = client.get("/upload/callback?" + urlencode({
            "code": "private-code", "state": params["state"][0], "iss": settings.issuer,
        }), follow_redirects=False)
        assert response.headers["location"] == "/upload?login=failed"
        assert "PRIVATE_PROVIDER_ERROR" not in response.text and "private-code" not in response.text
        assert "Max-Age=0" in response.headers["set-cookie"]
        assert client.get("/upload/session").json()["signed_in"] is False


def test_policy_upload_explains_validation_failure_and_allows_corrected_retry(browser):
    client, settings, _ = browser
    sign_in(client, settings)
    headers = {"Origin": settings.origin, "Content-Type": "application/octet-stream"}
    import yaml
    policy = yaml.safe_load((ROOT / "examples/veriq.rules.yaml").read_text())
    for rule in policy["rules"]:
        del rule["approved"]
    response = client.post("/upload/artifacts/policy", content=yaml.safe_dump(policy).encode(), headers=headers)
    assert response.status_code == 400
    assert "approval" in response.json()["error"]
    assert "quota" not in response.json()["error"]
    response = client.post("/upload/artifacts/policy", content=(ROOT / "examples/veriq.rules.yaml").read_bytes(), headers=headers)
    assert response.status_code == 201, response.text
