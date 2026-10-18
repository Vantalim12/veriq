"""Same-origin upload UI and Clerk public-client OAuth with PKCE."""

import base64
import hashlib
import hmac
from importlib.resources import files
import json
import secrets
import time
from urllib.parse import urlencode

import httpx
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from .hosted_auth import JWTVerifier, UPLOAD_SCOPE, principal

COOKIE = "__Host-veriq_upload"
LOGIN_SECONDS = 600
SESSION_SECONDS = 3600
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; "
       "base-uri 'none'; frame-ancestors 'none'; form-action 'self'")


def upload_routes(settings, upload):
    verifier = JWTVerifier(settings)
    callback = settings.origin + "/upload/callback"
    issuer = settings.issuer.rstrip("/")

    def cookie(response, value, seconds):
        response.set_cookie(COOKIE, value, max_age=seconds, secure=True, httponly=True,
                            samesite="lax", path="/")
        return response

    def finish(value="", seconds=0, failed=False):
        response = RedirectResponse("/upload" + ("?login=failed" if failed else ""), status_code=303)
        return cookie(response, value, seconds)

    async def asset(request):
        name = request.path_params.get("name", "upload.html")
        types = {"upload.html": "text/html", "upload.css": "text/css", "upload.js": "text/javascript", "favicon.png": "image/png"}
        if name not in types:
            return Response(status_code=404)
        return Response(files("veriq").joinpath("web", name).read_bytes(), media_type=types[name],
                        headers={"Content-Security-Policy": CSP, "Referrer-Policy": "no-referrer"})

    async def login(request):
        if not settings.upload_client_id:
            return JSONResponse({"error": "browser login is not configured"}, status_code=503)
        state, proof = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(proof.encode()).digest()).decode().rstrip("=")
        query = urlencode({"response_type": "code", "client_id": settings.upload_client_id,
                           "redirect_uri": callback, "scope": UPLOAD_SCOPE, "resource": settings.resource,
                           "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})
        response = RedirectResponse(issuer + "/oauth/authorize?" + query, status_code=303)
        return cookie(response, f"login.{int(time.time())}.{state}.{proof}", LOGIN_SECONDS)

    async def complete_login(request):
        query = request.query_params
        transaction = request.cookies.get(COOKIE, "").split(".")
        if not settings.upload_client_id or len(transaction) != 4 or transaction[0] != "login":
            return RedirectResponse("/upload?login=failed", status_code=303)
        _, issued, state, proof = transaction
        if (not issued.isascii() or not issued.isdigit() or len(issued) > 12
                or not 0 <= time.time() - int(issued) <= LOGIN_SECONDS
                or len(state) != 43 or len(proof) != 43
                or any(len(query.getlist(key)) != 1 for key in ("code", "state", "iss"))
                or not hmac.compare_digest(query.get("state", "").encode(), state.encode())
                or query.get("iss") != settings.issuer or query.get("error")
                or not 1 <= len(query.get("code", "")) <= 2048):
            # An unsolicited callback must not clear an existing browser session.
            return RedirectResponse("/upload?login=failed", status_code=303)
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                # No refresh token: browser upload sessions require a fresh login after expiry.
                async with client.stream("POST", issuer + "/oauth/token", data={
                    "grant_type": "authorization_code", "client_id": settings.upload_client_id,
                    "code": query["code"], "code_verifier": proof, "redirect_uri": callback,
                    "resource": settings.resource,
                }) as response:
                    if response.status_code != 200:
                        return finish(failed=True)
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 32 * 1024:
                            return finish(failed=True)
            payload = json.loads(body)
            token = payload.get("access_token")
            if payload.get("token_type", "").lower() != "bearer" or not isinstance(token, str) or len(token) > 3500:
                return finish(failed=True)
            access = await verifier.verify_token(token)
            if access is None or UPLOAD_SCOPE not in access.scopes:
                return finish(failed=True)
            seconds = min(SESSION_SECONDS, int(access.expires_at - time.time()))
            if seconds <= 0:
                return finish(failed=True)
            return finish(token, seconds)
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            return finish(failed=True)

    async def session(request):
        access = await verifier.verify_token(request.cookies.get(COOKIE, ""))
        signed_in = access is not None and UPLOAD_SCOPE in access.scopes
        return JSONResponse({"configured": bool(settings.upload_client_id), "signed_in": signed_in})

    async def browser_upload(request):
        if request.headers.get("origin") != settings.origin:
            return JSONResponse({"error": "upload from the Veriq page"}, status_code=403)
        access = await verifier.verify_token(request.cookies.get(COOKIE, ""))
        if access is None:
            return JSONResponse({"error": "Your upload session expired. Sign in again."}, status_code=401)
        if UPLOAD_SCOPE not in access.scopes:
            return JSONResponse({"error": "Upload permission is required. Sign in again."}, status_code=403)
        return await upload(request, owner=principal(access))

    async def logout(request):
        if request.headers.get("origin") != settings.origin:
            return JSONResponse({"error": "origin not allowed"}, status_code=403)
        return cookie(JSONResponse({"signed_in": False}), "", 0)

    return [Route("/upload", asset), Route("/upload/assets/{name}", asset),
            Route("/upload/login", login), Route("/upload/callback", complete_login),
            Route("/upload/session", session), Route("/upload/logout", logout, methods=["POST"]),
            Route("/upload/artifacts/{kind}", browser_upload, methods=["POST"])]
