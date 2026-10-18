"""OAuth-protected Streamable HTTP MCP and private raw-file upload endpoints."""

from contextlib import asynccontextmanager
import logging
from urllib.parse import urlsplit

import anyio
from mcp.server.auth.middleware.bearer_auth import RequireAuthMiddleware
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, request_response

from .artifacts import ArtifactStore, KINDS
from .hosted_auth import HostedSettings, JWTVerifier, READ_SCOPE, UPLOAD_SCOPE, principal
from .ingestion import InputError, read_workflow
from .semantics import workflow_compatibility
from .mcp_server import register_tools
from .browser_upload import upload_routes
from .document_worker import read_sop_isolated


class HostedMCP(FastMCP):
    async def list_tools(self):
        tools = await super().list_tools()
        for tool in tools:
            tool.securitySchemes = [{"type": "oauth2", "scopes": [READ_SCOPE]}]
        return tools


def create_app(settings: HostedSettings, *, store=None, audit_store=None, cleanup=True):
    if store is None:
        store = ArtifactStore(settings.data_dir)
    server = HostedMCP("Veriq", instructions=(
        "Read-only static verification. Supply artifact_id values returned by authenticated uploads, never server paths or URLs. "
        "The legacy relative_path argument also takes an artifact_id. "
        f"Upload workflows, SOPs and reviewed rules at {settings.origin}/upload using the same Clerk account, or through the artifact API. "
        "Drafts never approve rules; PASS does not prove live authorization or compliance."),
        stateless_http=True, json_response=True, max_request_body_size=64 * 1024,
        auth=AuthSettings(issuer_url=settings.issuer, resource_server_url=settings.resource,
                          required_scopes=[READ_SCOPE], validate_token_resource=True),
        token_verifier=JWTVerifier(settings),
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
            allowed_hosts=[urlsplit(settings.origin).netloc], allowed_origins=[settings.origin]))
    register_tools(server, lambda reference, suffixes: store.resolve(principal(), reference, suffixes),
                   principal, cache_seconds=3600, scopes=[READ_SCOPE], audit_store=audit_store,
                   document_reader=read_sop_isolated)
    app = server.streamable_http_app()
    upload_slots = anyio.Semaphore(2)
    metadata_url = settings.origin + "/.well-known/oauth-protected-resource/mcp"

    async def upload(request: Request, *, owner=None):
        kind = request.path_params["kind"]
        if kind not in KINDS:
            return JSONResponse({"error": "unsupported artifact kind"}, status_code=400)
        if request.headers.get("content-type", "").split(";")[0] != "application/octet-stream":
            return JSONResponse({"error": "send the raw file with Content-Type: application/octet-stream"}, status_code=415)
        limit = KINDS[kind][1]
        try:
            length = request.headers.get("content-length")
            if length is not None and (int(length) < 0 or int(length) > limit):
                return JSONResponse({"error": "input exceeds the byte limit"}, status_code=413)
            owner = owner or principal()
            async with upload_slots:
                with anyio.fail_after(30):
                    with store.temporary(owner, kind) as temporary:
                        size = 0
                        with temporary.open("wb") as output:
                            async for chunk in request.stream():
                                size += len(chunk)
                                if size > limit:
                                    return JSONResponse({"error": "input exceeds the byte limit"}, status_code=413)
                                output.write(chunk)
                        compatibility = None
                        if kind == "workflow":
                            compatibility = await anyio.to_thread.run_sync(
                                lambda: workflow_compatibility(read_workflow(temporary)))
                        result = await anyio.to_thread.run_sync(store.commit, owner, kind, temporary)
                        if compatibility is not None:
                            result["compatibility"] = compatibility
            return JSONResponse(result, status_code=201)
        except TimeoutError:
            return JSONResponse({"error": "upload timed out"}, status_code=408)
        except InputError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except (ValueError, UnicodeError):
            return JSONResponse({"error": "invalid input; check file encoding and format"}, status_code=400)
        except OSError:
            return JSONResponse({"error": "artifact storage unavailable"}, status_code=503)

    async def delete(request: Request):
        try:
            await anyio.to_thread.run_sync(store.delete, principal(), request.path_params["artifact_id"])
            return JSONResponse({"deleted": True})
        except (InputError, OSError):
            return JSONResponse({"error": "artifact unavailable"}, status_code=404)

    async def health(request):
        return JSONResponse({"status": "ok"})

    async def resource_metadata(request):
        # Preserve the issuer exactly; URL normalization can change OAuth issuer identity.
        return JSONResponse({"resource": settings.resource, "authorization_servers": [settings.issuer],
                             "scopes_supported": [READ_SCOPE, UPLOAD_SCOPE]})

    for route in app.routes:
        if route.path.startswith("/.well-known/oauth-protected-resource"):
            route.app = request_response(resource_metadata)

    app.routes.extend([
        Route("/artifacts/{kind}", RequireAuthMiddleware(request_response(upload), [UPLOAD_SCOPE], metadata_url), methods=["POST"]),
        Route("/artifacts/{artifact_id}", RequireAuthMiddleware(request_response(delete), [UPLOAD_SCOPE], metadata_url), methods=["DELETE"]),
        Route("/healthz", health),
    ])
    app.routes.extend(upload_routes(settings, upload))
    original_lifespan = app.router.lifespan_context

    async def cleanup_files():
        while True:
            try:
                await anyio.to_thread.run_sync(store.prune)
            except OSError:
                logging.getLogger(__name__).error("artifact cleanup failed; check private volume permissions")
            await anyio.sleep(60)

    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application):
            async with anyio.create_task_group() as tasks:
                if cleanup:
                    tasks.start_soon(cleanup_files)
                try:
                    yield
                finally:
                    tasks.cancel_scope.cancel()
    app.router.lifespan_context = lifespan

    async def private_responses(request, call_next):
        if request.headers.get("origin") and request.headers["origin"] != settings.origin:
            return JSONResponse({"error": "origin not allowed"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    app.add_middleware(BaseHTTPMiddleware, dispatch=private_responses)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlsplit(settings.origin).hostname])
    return app


def serve():
    import uvicorn
    settings = HostedSettings.from_environment()
    # shortcut: one process owns the file quotas and audit cache; use shared storage before scaling workers.
    uvicorn.run(create_app(settings), host="0.0.0.0", port=8000, workers=1, access_log=False,
                proxy_headers=False, limit_concurrency=20, timeout_keep_alive=5)
