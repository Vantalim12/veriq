"""Appwrite Functions bridge to the existing stateless HTTP application."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from .appwrite_store import AppwriteAPI, AppwriteStore
from .hosted import create_app
from .hosted_auth import HostedSettings
from .ingestion import InputError
from .sop import MAX_SOP_BYTES


def configured_store(root):
    try:
        api = AppwriteAPI(os.environ["APPWRITE_FUNCTION_API_ENDPOINT"],
            os.environ["APPWRITE_FUNCTION_PROJECT_ID"], os.environ["VERIQ_APPWRITE_API_KEY"])
    except KeyError as exc:
        raise InputError("configure Appwrite endpoint, project and private server API key") from exc
    try:
        return AppwriteStore(root, api, os.environ.get("VERIQ_APPWRITE_DATABASE", "veriq"),
                             os.environ.get("VERIQ_APPWRITE_BUCKET", "veriq-private"))
    except BaseException:
        api.close()
        raise


async def dispatch(context, settings, store):
    request = context.req
    path = request.path
    if not path.startswith("/") or path.startswith("//") or "?" in path or "#" in path:
        return context.res.json({"error": "invalid request path"}, 400)
    body = request.body_binary
    limit = MAX_SOP_BYTES if path.startswith("/artifacts/") else 64 * 1024
    if not isinstance(body, bytes) or len(body) > limit:
        return context.res.json({"error": "input exceeds the byte limit"}, 413,
                                {"cache-control": "no-store"})
    allowed = {"authorization", "content-type", "accept", "origin", "host", "mcp-protocol-version",
               "mcp-session-id", "last-event-id"}
    headers = {key.lower(): value for key, value in request.headers.items() if key.lower() in allowed}
    url = settings.origin + path
    if request.query_string:
        url += "?" + request.query_string
    app = create_app(settings, store=store, audit_store=store, cleanup=False)
    # shortcut: Appwrite buffers stateless JSON responses; use a streaming host if persistent SSE is required.
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            response = await client.request(request.method, url, headers=headers, content=body)
    response_headers = {key: value for key, value in response.headers.items()
                        if key not in {"content-length", "transfer-encoding", "connection"}}
    return context.res.binary(response.content, response.status_code, response_headers)


async def main(context):
    try:
        with TemporaryDirectory(prefix="veriq-") as directory:
            settings = HostedSettings.from_environment()
            store = configured_store(Path(directory))
            try:
                return await dispatch(context, settings, store)
            finally:
                store.api.close()
    except (InputError, OSError):
        context.error("Veriq configuration or private storage unavailable")
        return context.res.json({"error": "service unavailable"}, 503, {"cache-control": "no-store"})


async def cleanup(context):
    """Deploy separately with no client execute permissions and a five-minute schedule."""
    # Appwrite supplies execution metadata; a generated domain must not turn cleanup into a public route.
    if context.req.headers.get("x-appwrite-trigger") != "schedule":
        return context.res.json({"error": "not found"}, 404)
    try:
        with TemporaryDirectory(prefix="veriq-cleanup-") as directory:
            store = configured_store(Path(directory))
            try:
                removed = store.prune()
            finally:
                store.api.close()
        return context.res.json({"removed": removed})
    except (InputError, OSError):
        context.error("Veriq scheduled cleanup failed; check private storage configuration")
        return context.res.json({"error": "cleanup unavailable"}, 503)
